"""Start the real game server for tests/game.smoke.mjs.

Test-only: shorter timings and 3 rounds, so a whole game takes about 20
seconds, and a GET /test/answer route that tells the test the current
round's category. That route exists only here, never in
server/skugga_server.py. Binds to 127.0.0.1 on a free port and prints the
port on the first line.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import game  # noqa: E402
import qr  # noqa: E402
import rules  # noqa: E402
from skugga_server import Handler, Server  # noqa: E402

rules.DOT_INTERVAL_MS = 200
rules.GRACE_MS = 1000
game.COUNTDOWN_MS = 1000
game.ANSWER_MS = 1500
ROUNDS = 3


class TestHandler(Handler):
    def do_GET(self):
        if self.path == "/test/answer":
            g = self.server.game
            with self.server.lock:
                g.tick(self.server.clock())
                r = g.round
                self._json({"status": g.status, "round": r.number if r else 0,
                            "category": r.clip.category if r else None})
            return
        super().do_GET()


def main() -> None:
    g = game.Game(game.load_clips(ROOT / "data"),
                  rules.load_categories(ROOT / "data" / "categories.json"), rounds=ROUNDS)
    server = Server(("127.0.0.1", 0), g)
    server.join_svg = qr.svg(qr.encode(f"http://127.0.0.1:{server.server_address[1]}/")).encode()
    server.RequestHandlerClass = TestHandler
    print(server.server_address[1], flush=True)
    try:
        server.serve_forever(poll_interval=0.05)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
