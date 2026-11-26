#!/usr/bin/env python3
"""Render a contact sheet PNG of built clips (side view), for curation.

    python3 pipeline/preview.py OUT.png [id ...]   # default: every clip

One row per clip, 8 evenly spaced frames, white dots on black, with all
frames of a row sharing one scale so motion through space stays visible.
Standard library only (writes PNG with zlib).
"""
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ROOT / "data" / "clips"
CELL, COLS, DOT = 96, 8, 2


def png(path: Path, w: int, h: int, px: bytearray) -> None:
    raw = b"".join(b"\0" + bytes(px[y * w:(y + 1) * w]) for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main(argv):
    out = Path(argv[0])
    index = json.loads((CLIPS / "index.json").read_text())["clips"]
    ids = argv[1:] or [c["id"] for c in index]
    w, h = CELL * COLS, CELL * len(ids)
    px = bytearray(w * h)
    for row, cid in enumerate(ids):
        clip = json.loads((CLIPS / f"{cid}.json").read_text())
        fr = clip["frames"]
        picks = [fr[round(i * (len(fr) - 1) / (COLS - 1))] for i in range(COLS)]
        # side view: screen x = world x (forward), screen y = world y (up); per-frame centring on x
        span = max(max(f[1::3]) for f in fr) * 1.15 or 1
        for col, f in enumerate(picks):
            xs, ys = f[0::3], f[1::3]
            cx = (max(xs) + min(xs)) / 2
            for x, y in zip(xs, ys):
                sx = int(col * CELL + CELL / 2 + (x - cx) / span * CELL)
                sy = int(row * CELL + CELL - 4 - y / span * (CELL - 8))
                for dy in range(-DOT, DOT + 1):
                    for dx in range(-DOT, DOT + 1):
                        if dx * dx + dy * dy <= DOT * DOT and 0 <= sx + dx < w and row * CELL <= sy + dy < (row + 1) * CELL:
                            px[(sy + dy) * w + sx + dx] = 255
        for x in range(w):  # row separator
            px[((row + 1) * CELL - 1) * w + x] = 60
    png(out, w, h, px)
    print(f"wrote {out} ({len(ids)} rows)")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
