"""Tests for server/skugga_server.py: the HTTP API and its protections
(spec section 6), against a real server on a free local port."""
import http.client
import json
import random
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import rules  # noqa: E402
from game import COUNTDOWN_MS, Game, load_clips  # noqa: E402
from skugga_server import Server, host_allowed  # noqa: E402

CLIPS = load_clips(ROOT / "data")
CATEGORIES = rules.load_categories(ROOT / "data" / "categories.json")


class Clock:
    def __init__(self):
        self.t = 5_000_000

    def __call__(self):
        return self.t


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A small fake web/ tree, so the test doesn't depend on the phone page.
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "web" / "play").mkdir(parents=True)
        (root / "web" / "js").mkdir()
        (root / "web" / "play" / "index.html").write_text("<!doctype html><title>t</title>")
        (root / "web" / "play" / "play.js").write_text("export {};")
        (root / "web" / "js" / "display.js").write_text("export {};")
        (root / "web" / "js" / "viewer.js").write_text("export {};")   # not served
        (root / "secret.txt").write_text("nope")
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.clock = Clock()
        game = Game(CLIPS, CATEGORIES, rng=random.Random(3))
        self.server = Server(("127.0.0.1", 0), game, clock=self.clock, root=self.root)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, *, host=None, ctype="application/json", raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        if data is not None:
            headers["Content-Type"] = ctype
            headers["Content-Length"] = str(len(data))
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        try:
            parsed = json.loads(payload)
        except ValueError:
            parsed = payload
        return resp.status, parsed, resp

    def post(self, path, body, **kw):
        return self.request("POST", path, body, **kw)


class TestHostCheck(ServerTest):
    def test_allowed_hosts(self):
        names = {"localhost", "mybox", "mybox.local"}
        for h in ["127.0.0.1", "127.0.0.1:8765", "192.168.1.20:8765", "[::1]:8765", "::1",
                  "localhost:8765", "MyBox", "mybox.local:8765"]:
            self.assertTrue(host_allowed(h, names), h)
        for h in [None, "", "evil.example", "evil.example:8765", "127.0.0.1.evil.example",
                  "mybox.evil.example"]:
            self.assertFalse(host_allowed(h, names), h)

    def test_other_hosts_refused(self):
        status, body, _ = self.request("GET", "/state", host="attacker.example")
        self.assertEqual((status, body), (403, {"error": "bad_host"}))
        status, *_ = self.post("/join", {"name": "Ana"}, host="attacker.example")
        self.assertEqual(status, 403)

    def test_ip_host_accepted(self):
        status, body, _ = self.request("GET", "/state")
        self.assertEqual((status, body["status"]), (200, "lobby"))


class TestPostChecks(ServerTest):
    def test_json_only(self):
        status, body, _ = self.post("/join", None, raw=b'{"name":"Ana"}', ctype="text/plain")
        self.assertEqual((status, body["error"]), (415, "json_only"))

    def test_size_limit(self):
        status, body, _ = self.post("/join", {"name": "x" * 2000})
        self.assertEqual((status, body["error"]), (413, "too_large"))

    def test_bad_json(self):
        for raw in [b"{nope", b"[1,2]", b'"text"']:
            status, body, _ = self.post("/join", None, raw=raw)
            self.assertEqual((status, body["error"]), (400, "bad_json"), raw)

    def test_unknown_route_and_methods(self):
        self.assertEqual(self.post("/admin", {})[0], 404)
        self.assertEqual(self.request("PUT", "/join", {})[0], 405)
        self.assertEqual(self.request("DELETE", "/state")[0], 405)


class TestStaticFiles(ServerTest):
    def test_page_and_scripts_served_with_headers(self):
        status, body, resp = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", resp.getheader("Content-Security-Policy"))
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.getheader("Cache-Control"), "no-store")
        self.assertEqual(self.request("GET", "/play.js")[0], 200)

    def test_nothing_else_reachable(self):
        for path in ["/secret.txt", "/../secret.txt", "/%2e%2e/secret.txt", "/js/viewer.js", "/js/display.js",
                     "/web/play/index.html", "/data/clips/index.json", "/data/categories.json",
                     "/server/game.py", "//etc/passwd"]:
            self.assertEqual(self.request("GET", path)[0], 404, path)


class TestGameOverHttp(ServerTest):
    def test_join_start_reveal_guess(self):
        _, a, _ = self.post("/join", {"name": "Ana"})
        _, b, _ = self.post("/join", {"name": "Ben"})
        self.assertEqual(self.post("/start", {"token": b["token"]})[0], 403)   # not leader
        self.assertEqual(self.post("/start", {"token": "forged"})[0], 403)
        self.assertEqual(self.post("/start", {"token": a["token"]})[0], 200)
        self.clock.t += COUNTDOWN_MS

        _, st, _ = self.request("GET", f"/state?token={a['token']}")
        rnd = st["round"]
        self.assertEqual((st["status"], rnd["dotsShown"]), ("reveal", 1))
        self.assertNotIn("answer", st)
        game_round = self.server.game.round
        raw_state = json.dumps(st)
        self.assertNotIn(game_round.clip.id, raw_state)
        self.assertNotIn(game_round.clip.description, raw_state)

        # dot 0 is revealed, dot 1 isn't yet
        status, track, _ = self.request("GET", f"/round/{rnd['id']}/marker/0?token={a['token']}")
        self.assertEqual((status, track["marker"]), (200, 0))
        self.assertEqual(len(track["track"]), 2 * rnd["frameCount"])
        self.assertEqual(self.request("GET", f"/round/{rnd['id']}/marker/1?token={a['token']}")[0], 403)
        self.assertEqual(self.request("GET", f"/round/{rnd['id']}/marker/0?token=forged")[0], 403)
        self.assertEqual(self.request("GET", f"/round/{rnd['id']}/marker/0")[0], 403)

        # Ben can't guess as Ana; a correct guess ends the round with points
        answer = game_round.clip.category
        self.assertEqual(self.post("/guess", {"token": "forged", "roundId": rnd["id"],
                                              "guess": answer})[0], 403)
        status, res, _ = self.post("/guess", {"token": b["token"], "roundId": rnd["id"], "guess": answer})
        self.assertEqual((status, res), (200, {"correct": True}))
        _, st, _ = self.request("GET", f"/state?token={a['token']}")
        self.assertEqual(st["status"], "answer")
        self.assertEqual((st["answer"]["category"], st["answer"]["winner"], st["answer"]["points"]),
                         (answer, "Ben", 15))

    def test_reconnect_returns_same_player(self):
        _, a, _ = self.post("/join", {"name": "Ana"})
        _, again, _ = self.post("/join", {"name": "whatever", "token": a["token"]})
        self.assertEqual(again, a)


if __name__ == "__main__":
    unittest.main()
