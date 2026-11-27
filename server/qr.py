"""A small QR code encoder, so phones can scan the join address.

Standard library only. It does just what the game needs: byte-mode text,
error correction level M, versions 1 to 10 (up to 213 bytes, plenty for a
URL), with the mask chosen by the standard penalty rules (ISO/IEC 18004).

    m = encode("http://192.168.1.20:8765/")   # list of rows, True = dark
    print(terminal(m))                         # for a terminal
    svg(m)                                     # an SVG image, as text
"""
from __future__ import annotations

# Level M, versions 1..10: error correction codewords per block, and blocks.
ECC_PER_BLOCK = [10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
NUM_BLOCKS = [1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
MAX_VERSION = len(ECC_PER_BLOCK)
FORMAT_LEVEL_M = 0  # the two level bits: L=01, M=00, Q=11, H=10


# --- Reed-Solomon over GF(256), polynomial 0x11D

def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


# --- sizes

def _raw_modules(ver: int) -> int:
    """Modules left for data and error correction after the function patterns."""
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def data_capacity(ver: int) -> int:
    """Data codewords (bytes) in a level-M symbol of this version."""
    return _raw_modules(ver) // 8 - ECC_PER_BLOCK[ver - 1] * NUM_BLOCKS[ver - 1]


def _alignment_positions(ver: int) -> list[int]:
    if ver == 1:
        return []
    n = ver // 7 + 2
    size = ver * 4 + 17
    step = (ver * 8 + n * 3 + 5) // (n * 4 - 4) * 2
    return [6] + [size - 7 - i * step for i in range(n - 2, -1, -1)]


# --- the bit stream

def _codewords(data: bytes, ver: int) -> list[int]:
    bits: list[int] = []

    def put(value: int, n: int) -> None:
        bits.extend((value >> i) & 1 for i in range(n - 1, -1, -1))

    put(0b0100, 4)                              # byte mode
    put(len(data), 8 if ver <= 9 else 16)       # character count
    for b in data:
        put(b, 8)
    cap = data_capacity(ver) * 8
    put(0, min(4, cap - len(bits)))             # terminator
    put(0, -len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < cap // 8:
        words.append(pad)
        pad ^= 0xEC ^ 0x11

    # Split into blocks, add error correction, interleave.
    nblocks, ecc = NUM_BLOCKS[ver - 1], ECC_PER_BLOCK[ver - 1]
    total = _raw_modules(ver) // 8
    short_len = total // nblocks - ecc           # data bytes in a short block
    nshort = nblocks - total % nblocks
    divisor = _rs_divisor(ecc)
    blocks, k = [], 0
    for i in range(nblocks):
        n = short_len + (0 if i < nshort else 1)
        blocks.append((words[k:k + n], _rs_remainder(words[k:k + n], divisor)))
        k += n
    out = []
    for i in range(short_len + 1):
        out.extend(d[i] for d, _ in blocks if i < len(d))
    for i in range(ecc):
        out.extend(e[i] for _, e in blocks)
    return out


# --- the matrix

class _Matrix:
    def __init__(self, ver: int):
        self.ver = ver
        self.size = ver * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def set(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.fixed[y][x] = True

    def function_patterns(self) -> None:
        size = self.size
        for i in range(size):                   # timing
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):   # finders
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        d = max(abs(dx), abs(dy))
                        self.set(x, y, d not in (2, 4))
        pos = _alignment_positions(self.ver)
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue                    # those corners have finders
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format_bits(0)                     # reserve; drawn for real later
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = size - 11 + i % 3, i // 3
                self.set(a, b, bit)
                self.set(b, a, bit)

    def format_bits(self, mask: int) -> None:
        data = FORMAT_LEVEL_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        size = self.size
        bit = [(bits >> i) & 1 == 1 for i in range(15)]
        for i in range(6):
            self.set(8, i, bit[i])
        self.set(8, 7, bit[6])
        self.set(8, 8, bit[7])
        self.set(7, 8, bit[8])
        for i in range(9, 15):
            self.set(14 - i, 8, bit[i])
        for i in range(8):
            self.set(size - 1 - i, 8, bit[i])
        for i in range(8, 15):
            self.set(8, size - 15 + i, bit[i])
        self.set(8, size - 8, True)             # the dark module

    def place(self, words: list[int]) -> None:
        size, i = self.size, 0
        nbits = len(words) * 8
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = (right + 1) & 2 == 0
                    y = size - 1 - vert if upward else vert
                    if not self.fixed[y][x] and i < nbits:
                        self.dark[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if not self.fixed[y][x] and MASKS[mask](x, y):
                    self.dark[y][x] = not self.dark[y][x]


MASKS = [
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


def penalty(rows: list[list[bool]]) -> int:
    """The standard's penalty score for a finished symbol (lower is better)."""
    size = len(rows)
    score = 0
    lines = rows + [list(col) for col in zip(*rows)]
    finder_like = ([True, False, True, True, True, False, True, False, False, False, False],
                   [False, False, False, False, True, False, True, True, True, False, True])
    for line in lines:
        run, prev = 0, None
        for v in line:                          # rule 1: runs of 5 or more
            if v == prev:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run, prev = 1, v
        if run >= 5:
            score += run - 2
        for i in range(size - 10):              # rule 3: finder-like patterns
            if line[i:i + 11] in finder_like:
                score += 40
    for y in range(size - 1):                   # rule 2: 2x2 blocks
        for x in range(size - 1):
            if rows[y][x] == rows[y][x + 1] == rows[y + 1][x] == rows[y + 1][x + 1]:
                score += 3
    dark = sum(map(sum, rows))                  # rule 4: balance of dark
    total = size * size
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    return score + k * 10


def encode(text: str, *, mask: int | None = None) -> list[list[bool]]:
    """The QR code for text, as rows of modules (True = dark), no quiet zone."""
    data = text.encode("utf-8")
    for ver in range(1, MAX_VERSION + 1):
        if len(data) + (2 if ver <= 9 else 3) <= data_capacity(ver):
            break
    else:
        raise ValueError(f"too long for a QR code here ({len(data)} bytes)")
    words = _codewords(data, ver)
    best = None
    for m in range(8) if mask is None else [mask]:
        mx = _Matrix(ver)
        mx.function_patterns()
        mx.place(words)
        mx.apply_mask(m)
        mx.format_bits(m)
        score = penalty(mx.dark)
        if best is None or score < best[0]:
            best = (score, mx.dark)
    return best[1]


def terminal(rows: list[list[bool]], quiet: int = 2, *, color: bool = False) -> str:
    """Text for a terminal, two modules per character with half blocks.

    Light modules (and the quiet zone) are drawn as blocks, so it reads
    correctly on the usual dark background. With color, each line is also
    set to white on black, so it reads correctly on a light terminal too."""
    size = len(rows)
    n = size + 2 * quiet

    def light(x: int, y: int) -> bool:
        x, y = x - quiet, y - quiet
        return not (0 <= x < size and 0 <= y < size and rows[y][x])

    out = []
    for y in range(0, n, 2):
        line = "".join(
            "█" if top and bottom else "▀" if top else "▄" if bottom else " "
            for top, bottom in ((light(x, y), y + 1 < n and light(x, y + 1)) for x in range(n)))
        out.append(f"\x1b[97;40m{line}\x1b[0m" if color else line)
    return "\n".join(out)


def svg(rows: list[list[bool]], quiet: int = 4) -> str:
    """An SVG image of the code, dark modules on white, one unit per module."""
    n = len(rows) + 2 * quiet
    path = []
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            if row[x]:
                start = x
                while x < len(row) and row[x]:
                    x += 1
                path.append(f"M{start + quiet} {y + quiet}h{x - start}v1h{start - x}z")
            else:
                x += 1
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" '
            f'shape-rendering="crispEdges"><rect width="{n}" height="{n}" fill="#fff"/>'
            f'<path fill="#000" d="{"".join(path)}"/></svg>')
