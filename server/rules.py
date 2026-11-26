"""Skugga's game rules as pure functions: checking guesses, reveal timing,
scoring and when a round ends. See docs/game-spec.md, sections 2 to 4.

Standard library only. Nothing here does I/O except load_categories(), so
the server and the tests can use these functions directly.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# --- Reveal timing and scoring (spec section 3) ---------------------------

TOTAL_DOTS = 15
DOT_INTERVAL_MS = 1300
GRACE_MS = 5000

# Dots are added in this order, least telling first. Must match the viewer's
# REVEAL_ORDER in web/js/display.js (a test checks this).
REVEAL_ORDER = (
    "lankle", "rwrist", "head", "rknee", "lelbow", "pelvis", "rankle", "lwrist",
    "lknee", "relbow", "neck", "rhip", "lshoulder", "lhip", "rshoulder",
)


def dots_shown(now_ms: int, t0_ms: int) -> int:
    """How many dots are showing at server time now_ms, for a reveal that
    started at t0_ms: 0 before the start, then 1, rising by one every
    DOT_INTERVAL_MS, up to TOTAL_DOTS."""
    if now_ms < t0_ms:
        return 0
    return min(TOTAL_DOTS, 1 + (now_ms - t0_ms) // DOT_INTERVAL_MS)


def points_for(dots: int) -> int:
    """Points for the first correct guess with `dots` showing: 16 minus the
    dots, so 15 at one dot and 1 at the full figure. 0 if nothing shows."""
    if dots <= 0:
        return 0
    return TOTAL_DOTS + 1 - min(dots, TOTAL_DOTS)


def full_figure_at(t0_ms: int) -> int:
    """Server time at which the last dot appears."""
    return t0_ms + (TOTAL_DOTS - 1) * DOT_INTERVAL_MS


def round_deadline(t0_ms: int) -> int:
    """Server time at which an unanswered round ends."""
    return full_figure_at(t0_ms) + GRACE_MS


def round_end_reason(now_ms: int, t0_ms: int, *, answered: bool, players_in: int) -> str | None:
    """Why the round is over, or None if it isn't (spec section 2.5).

    answered: someone has guessed correctly.
    players_in: players present (not away) who haven't guessed wrong yet.
    """
    if answered:
        return "answered"
    if players_in <= 0:
        return "all_out"
    if now_ms >= round_deadline(t0_ms):
        return "timeout"
    return None


# --- Checking guesses (spec section 4) ------------------------------------

MAX_GUESS_CHARS = 40
TYPO_MIN_LETTERS = 5
FORM_MIN_LETTERS = 4
FILLER_WORDS = frozenset({"a", "an", "the"})
SUFFIXES = ("ing", "ed", "er", "es", "s")

_NOT_WORD = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r" +")


def normalize(text: str) -> str:
    """Lowercase; anything but letters, digits and spaces becomes a space;
    spaces collapsed; trimmed."""
    text = _NOT_WORD.sub(" ", text.lower())
    return _SPACES.sub(" ", text).strip()


def within_one_edit(a: str, b: str) -> bool:
    """True if a and b differ by at most one inserted, deleted or changed
    character."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def word_forms(word: str):
    """The word, then what it might be with an ending taken off: "walks" ->
    "walk", "dancer" -> "dance", "running" -> "run". Words under
    FORM_MIN_LETTERS letters, and bases under 3, are left alone ("his" is
    never "hi")."""
    yield word
    if len(word) < FORM_MIN_LETTERS:
        return
    for suffix in SUFFIXES:
        if word.endswith(suffix):
            base = word[:-len(suffix)]
            if len(base) < 3:
                continue
            yield base
            yield base + "e"
            if base[-1] == base[-2]:
                yield base[:-1]


@dataclass(frozen=True)
class _Match:
    start: int  # first guess word covered
    end: int    # one past the last guess word covered
    category: str

    def inside(self, other: "_Match") -> bool:
        """Strictly inside other's span (shorter, and covered by it)."""
        return (other.start <= self.start and self.end <= other.end
                and (other.end - other.start) > (self.end - self.start))


class GuessChecker:
    """Checks guesses against the categories and their synonyms."""

    def __init__(self, categories: dict[str, list[str]]):
        raw_terms = [(normalize(term).split(), category)
                     for category, synonyms in categories.items()
                     for term in [category, *synonyms]]
        # Every word that appears in a name or synonym, as written.
        self.known_words = {w for words, _ in raw_terms for w in words}
        # Each name and synonym as a tuple of base words (see base()),
        # without filler words. Duplicates within a category are dropped.
        self.terms: list[tuple[tuple[str, ...], str]] = []
        for words, category in raw_terms:
            key = (self.base_words(words), category)
            if key[0] and key not in self.terms:
                self.terms.append(key)
        # Known words long enough to forgive one typo.
        self.typo_words = sorted(w for w in self.known_words if len(w) >= TYPO_MIN_LETTERS)
        self.categories = list(categories)

    def base(self, word: str) -> str | None:
        """The shortest form of a word (word_forms) that is a known word, so
        "walks", "walking" and "walker" all read as "walk". None if no form
        is known."""
        known = [f for f in word_forms(word) if f in self.known_words]
        return min(known, key=len) if known else None

    def base_words(self, words: list[str]) -> tuple[str, ...]:
        return tuple(self.base(w) or w for w in words if w not in FILLER_WORDS)

    def _readings(self, word: str) -> set[str]:
        """What a guess word can stand for, as base words: its own base if it
        has one (exact wins, so it is never typo-matched), otherwise the bases
        of known words one typo away, if it is long enough. Empty if none."""
        b = self.base(word)
        if b is not None:
            return {b}
        if len(word) < TYPO_MIN_LETTERS:
            return set()
        return {self.base(w) for w in self.typo_words if within_one_edit(word, w)}

    def matches(self, guess: str) -> set[str]:
        """The categories a guess names, after the spec's rules."""
        words = [w for w in normalize(guess[:MAX_GUESS_CHARS]).split() if w not in FILLER_WORDS]
        readings = [self._readings(w) for w in words]
        found: list[_Match] = []
        # Names and synonyms, as whole words, in any of their forms.
        for term, category in self.terms:
            n = len(term)
            for i in range(len(words) - n + 1):
                if all(term[k] in readings[i + k] for k in range(n)):
                    found.append(_Match(i, i + n, category))
        # A match inside a longer one doesn't count ("jump" in "star jump").
        kept = [m for m in found if not any(m.inside(o) for o in found)]
        return {m.category for m in kept}

    def is_correct(self, guess: str, answer: str) -> bool:
        """Correct only if the guess names exactly one category, the answer."""
        return self.matches(guess) == {answer}


def load_categories(path: str | Path) -> dict[str, list[str]]:
    """Read data/categories.json: {category: [synonyms...]}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["categories"]
