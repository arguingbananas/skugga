#!/usr/bin/env python3
"""Skugga game server: run it on one computer, play on phones on the same Wi-Fi.

    python3 server/skugga_server.py [port]      # default port 8765

Then open the address it prints on each phone. Standard library only.

It assumes a trusted home network: no HTTPS and no password. Within that, it
keeps players from acting as each other (each player has a token), accepts
only small JSON POSTs, refuses requests whose Host header isn't an address or
this computer's name (so other websites can't reach it through a player's
browser), and serves only the phone page, its scripts and the API. See
docs/game-spec.md, section 6.6.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules  # noqa: E402
from game import Game, GameError, load_clips  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 8765
MAX_BODY = 1024
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
         ".webmanifest": "application/manifest+json"}
MARKER_PATH = re.compile(r"^/round/([0-9a-f]{16})/marker/([0-9]{1,2})$")


def now_ms() -> int:
    return int(time.time() * 1000)


def static_files(root: Path) -> dict[str, Path]:
    """Every file the server may send, by URL path. Requests for anything
    else get 404, so no path can reach the rest of the repository."""
    files = {}
    play = root / "web" / "play"
    if play.is_dir():
        for f in play.rglob("*"):
            if f.is_file() and f.suffix in TYPES:
                files["/" + f.relative_to(play).as_posix()] = f
    if "/index.html" in files:
        files["/"] = files["/index.html"]
    return files


def host_allowed(host_header: str | None, own_names: set[str]) -> bool:
    """True for an IP address, localhost, or this computer's own name."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    if host.startswith("["):                      # [IPv6]:port
        host = host[1:host.find("]")] if "]" in host else ""
    elif host.count(":") == 1:                    # name:port or IPv4:port
        host = host.rsplit(":", 1)[0]
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return host in own_names


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, game: Game, *, clock=now_ms, root: Path = ROOT):
        super().__init__(address, Handler)
        self.game = game
        self.clock = clock
        self.lock = threading.Lock()
        self.files = static_files(root)
        name = socket.gethostname().lower()
        self.own_names = {"localhost", name, name + ".local"}


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = "skugga"
    sys_version = ""

    # --- responses

    def _headers(self, code: int, ctype: str, length: int) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                             "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                             "base-uri 'none'; form-action 'none'")
        self.end_headers()

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, separators=(",", ":")).encode()
        self._headers(code, "application/json", len(body))
        self.wfile.write(body)

    def _error(self, code: int, error: str) -> None:
        self._json({"error": error}, code)

    def log_message(self, format, *args):
        pass  # quiet: no request logs with player names or guesses

    # --- request checks

    def _checked(self) -> bool:
        if not host_allowed(self.headers.get("Host"), self.server.own_names):
            self._error(403, "bad_host")
            return False
        return True

    def _query(self) -> dict[str, str]:
        q = parse_qs(urlsplit(self.path).query, max_num_fields=5)
        return {k: v[0] for k, v in q.items()}

    def _body(self) -> dict | None:
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self._error(415, "json_only")
            return None
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._error(411, "length_required")
            return None
        if not 0 <= length <= MAX_BODY:
            self._error(413, "too_large")
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeDecodeError):
            self._error(400, "bad_json")
            return None
        if not isinstance(body, dict):
            self._error(400, "bad_json")
            return None
        return body

    # --- routes

    def do_GET(self):
        if not self._checked():
            return
        path = urlsplit(self.path).path
        q = self._query()
        g, now = self.server.game, self.server.clock()
        try:
            if path == "/state":
                with self.server.lock:
                    g.touch(now, q.get("token"))
                    g.tick(now)
                    self._json(g.state(now, q.get("token")))
                return
            m = MARKER_PATH.match(path)
            if m:
                with self.server.lock:
                    g.touch(now, q.get("token"))
                    g.tick(now)
                    track = g.track(now, q.get("token"), m.group(1), int(m.group(2)))
                self._json({"marker": int(m.group(2)), "track": track})
                return
        except GameError as e:
            self._error(e.status, e.code)
            return
        f = self.server.files.get(path)
        if f is None:
            self._error(404, "not_found")
            return
        body = f.read_bytes()
        self._headers(200, TYPES[f.suffix], len(body))
        self.wfile.write(body)

    def do_POST(self):
        if not self._checked():
            return
        path = urlsplit(self.path).path
        if path not in ("/join", "/start", "/guess", "/again"):
            self._error(404, "not_found")
            return
        body = self._body()
        if body is None:
            return
        g, now = self.server.game, self.server.clock()
        try:
            with self.server.lock:
                g.touch(now, body.get("token"))
                g.tick(now)
                if path == "/join":
                    p = g.join(now, body.get("name"), body.get("token"))
                    result = {"token": p.token, "playerId": p.id}
                elif path == "/start":
                    g.start(now, body.get("token"))
                    result = {"ok": True}
                elif path == "/guess":
                    correct = g.guess(now, body.get("token"), body.get("roundId"), body.get("guess"))
                    result = {"correct": correct}
                else:
                    g.again(now, body.get("token"))
                    result = {"ok": True}
        except GameError as e:
            self._error(e.status, e.code)
            return
        self._json(result)

    def do_PUT(self):
        self._error(405, "method_not_allowed")

    do_DELETE = do_PATCH = do_OPTIONS = do_PUT


def lan_address() -> str | None:
    """This computer's address on the local network (no traffic is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # messages show up at once, even redirected
    port = int(argv[0]) if argv else DEFAULT_PORT
    clips = load_clips(ROOT / "data")
    categories = rules.load_categories(ROOT / "data" / "categories.json")
    server = Server(("0.0.0.0", port), Game(clips, categories))
    if "/" not in server.files:
        print("Note: the phone page (web/play/) isn't built yet; only the API works.")
    print(f"Skugga: {len(clips)} clips, {server.game.total_rounds} rounds per game.")
    print(f"  On this computer: http://localhost:{port}/")
    lan = lan_address()
    if lan:
        print(f"  On your phones:   http://{lan}:{port}/   (same Wi-Fi)")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
