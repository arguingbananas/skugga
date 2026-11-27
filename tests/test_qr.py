"""Tests for server/qr.py. They read each symbol back independently of how
it was drawn: the format bits (both copies), the codewords in placement
order, the Reed-Solomon check of every block, and the byte-mode payload."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import qr  # noqa: E402


def format_word(level_mask: int) -> int:
    rem = level_mask
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return (level_mask << 10 | rem) ^ 0x5412


def function_map(ver: int) -> list[list[bool]]:
    """Which modules aren't data: rebuilt from the standard's layout rules."""
    n = ver * 4 + 17
    f = [[False] * n for _ in range(n)]

    def box(x0, y0, w, h):
        for y in range(max(y0, 0), min(y0 + h, n)):
            for x in range(max(x0, 0), min(x0 + w, n)):
                f[y][x] = True

    box(0, 0, 9, 9)                       # finders, separators, format bits
    box(n - 8, 0, 8, 9)
    box(0, n - 8, 9, 8)
    box(6, 0, 1, n)                       # timing
    box(0, 6, n, 1)
    if ver >= 2:
        pos = qr._alignment_positions(ver)
        corners = {(pos[0], pos[0]), (pos[0], pos[-1]), (pos[-1], pos[0])}   # the finders
        for ay in pos:
            for ax in pos:
                if (ax, ay) not in corners:
                    box(ax - 2, ay - 2, 5, 5)
    if ver >= 7:                          # version bits
        box(n - 11, 0, 3, 6)
        box(0, n - 11, 6, 3)
    return f


def read_codewords(m: list[list[bool]], mask: int, ver: int) -> list[int]:
    n = len(m)
    f = function_map(ver)
    bits = []
    col = n - 1
    up = True
    while col > 0:
        if col == 6:
            col -= 1
        ys = range(n - 1, -1, -1) if up else range(n)
        for y in ys:
            for x in (col, col - 1):
                if not f[y][x]:
                    bits.append(m[y][x] ^ qr.MASKS[mask](x, y))
        up = not up
        col -= 2
    words = []
    for i in range(0, len(bits) - 7, 8):
        words.append(int("".join("1" if b else "0" for b in bits[i:i + 8]), 2))
    return words


def gf_pow2(e: int) -> int:
    x = 1
    for _ in range(e):
        x = qr._gf_mul(x, 2)
    return x


def syndromes_zero(block: list[int], ecc: int) -> bool:
    for i in range(ecc):
        a, s = gf_pow2(i), 0
        for c in block:
            s = qr._gf_mul(s, a) ^ c
        if s:
            return False
    return True


def decode(m: list[list[bool]]) -> tuple[str, int]:
    """The text in a symbol, and its mask; fails the test on any error."""
    n = len(m)
    ver = (n - 17) // 4
    word = 0
    for i, (x, y) in enumerate([(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)]
                               + [(14 - i, 8) for i in range(9, 15)]):
        word |= m[y][x] << i
    word2 = 0
    for i, (x, y) in enumerate([(n - 1 - i, 8) for i in range(8)] + [(8, n - 15 + i) for i in range(8, 15)]):
        word2 |= m[y][x] << i
    assert word == word2, "format copies differ"
    mask = next(k for k in range(8) if format_word(k) == word)   # level M is 00
    assert m[n - 8][8], "dark module"
    words = read_codewords(m, mask, ver)[:qr._raw_modules(ver) // 8]
    nb, ecc = qr.NUM_BLOCKS[ver - 1], qr.ECC_PER_BLOCK[ver - 1]
    total = len(words)
    short = total // nb - ecc
    nshort = nb - total % nb
    lens = [short + (0 if i < nshort else 1) for i in range(nb)]
    data = [[] for _ in range(nb)]
    k = 0
    for i in range(short + 1):
        for b in range(nb):
            if i < lens[b]:
                data[b].append(words[k])
                k += 1
    for b in range(nb):
        block = data[b] + [words[k + i * nb + b] for i in range(ecc)]
        assert syndromes_zero(block, ecc), f"block {b} fails Reed-Solomon"
    stream = "".join(f"{w:08b}" for d in data for w in d)
    assert stream[:4] == "0100", "byte mode"
    cbits = 8 if ver <= 9 else 16
    length = int(stream[4:4 + cbits], 2)
    body = stream[4 + cbits:4 + cbits + 8 * length]
    return bytes(int(body[i:i + 8], 2) for i in range(0, len(body), 8)).decode(), mask


class TestQr(unittest.TestCase):
    def test_capacities_match_the_standard(self):
        # ISO/IEC 18004 table 7, level M, data codewords for versions 1..10
        self.assertEqual([qr.data_capacity(v) for v in range(1, 11)],
                         [16, 28, 44, 64, 86, 108, 124, 154, 182, 216])

    def test_round_trip_every_version_and_mask(self):
        texts = ["http://192.168.1.20:8765/", "a", "héllo ✓"]
        for v in range(1, 11):
            texts.append(("http://x/" + "abcdefghij" * 30)[:qr.data_capacity(v) - (2 if v <= 9 else 3)])
        for text in texts:
            for mask in range(8):
                with self.subTest(text=text[:20], mask=mask):
                    m = qr.encode(text, mask=mask)
                    self.assertEqual(decode(m), (text, mask))

    def test_smallest_version_chosen(self):
        self.assertEqual(len(qr.encode("http://192.168.1.20:8765/")), 25)   # version 2
        self.assertEqual(len(qr.encode("x" * 14)), 21)                      # version 1, full

    def test_too_long(self):
        with self.assertRaises(ValueError):
            qr.encode("x" * 214)

    def test_penalty_picks_the_lowest(self):
        text = "http://10.0.0.7:8765/"
        best = qr.encode(text)
        self.assertEqual(qr.penalty(best), min(qr.penalty(qr.encode(text, mask=k)) for k in range(8)))

    def test_renderings(self):
        m = qr.encode("http://192.168.1.20:8765/")
        lines = qr.terminal(m).split("\n")
        self.assertEqual(len(lines), (25 + 4 + 1) // 2)
        self.assertTrue(all(len(line) == 29 for line in lines))
        self.assertTrue(qr.terminal(m, color=True).startswith("\x1b[97;40m"))
        s = qr.svg(m)
        self.assertTrue(s.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 33 33"'))


if __name__ == "__main__":
    unittest.main()
