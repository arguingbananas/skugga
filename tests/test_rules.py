"""Unit tests for server/rules.py (spec sections 2 to 4).

    python3 -m unittest discover -s tests
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import rules  # noqa: E402
from rules import (  # noqa: E402
    GuessChecker, dots_shown, full_figure_at, load_categories, normalize,
    points_for, round_deadline, round_end_reason, within_one_edit,
)

CATEGORIES = load_categories(ROOT / "data" / "categories.json")


class TestTiming(unittest.TestCase):
    def test_dots_before_start(self):
        self.assertEqual(dots_shown(999, 1000), 0)

    def test_five_dots_at_start(self):
        self.assertEqual(dots_shown(1000, 1000), 5)

    def test_dot_added_every_interval(self):
        t0 = 10_000
        self.assertEqual(dots_shown(t0 + 699, t0), 5)
        self.assertEqual(dots_shown(t0 + 700, t0), 6)
        self.assertEqual(dots_shown(t0 + 25 * 700, t0), 30)

    def test_full_figure_at_18_2_s_and_stays(self):
        t0 = 0
        self.assertEqual(full_figure_at(t0), 18_200)
        self.assertEqual(dots_shown(18_199, t0), 30)
        self.assertEqual(dots_shown(18_200, t0), 31)
        self.assertEqual(dots_shown(10 ** 9, t0), 31)

    def test_deadline_is_grace_after_full_figure(self):
        self.assertEqual(round_deadline(0), 23_200)


class TestScoring(unittest.TestCase):
    def test_points_fall_from_27_to_1(self):
        self.assertEqual([points_for(d) for d in range(5, 32)], list(range(27, 0, -1)))

    def test_no_dots_no_points(self):
        self.assertEqual(points_for(0), 0)

    def test_grace_period_scores_like_full_figure(self):
        self.assertEqual(points_for(dots_shown(22_000, 0)), 1)


class TestRoundEnd(unittest.TestCase):
    def test_running(self):
        self.assertIsNone(round_end_reason(5_000, 0, answered=False, players_in=3))

    def test_answered_wins_over_everything(self):
        self.assertEqual(round_end_reason(99_999, 0, answered=True, players_in=0), "answered")

    def test_everyone_out(self):
        self.assertEqual(round_end_reason(5_000, 0, answered=False, players_in=0), "all_out")

    def test_timeout_exactly_at_deadline(self):
        self.assertIsNone(round_end_reason(23_199, 0, answered=False, players_in=2))
        self.assertEqual(round_end_reason(23_200, 0, answered=False, players_in=2), "timeout")


class TestHelpers(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("  Jumping-JACKS!!  "), "jumping jacks")
        self.assertEqual(normalize("it's a  walk."), "it s a walk")

    def test_within_one_edit(self):
        self.assertTrue(within_one_edit("running", "runnig"))    # deletion
        self.assertTrue(within_one_edit("running", "runninng"))  # insertion
        self.assertTrue(within_one_edit("running", "runming"))   # change
        self.assertFalse(within_one_edit("running", "rnnig"))    # two edits
        self.assertFalse(within_one_edit("walk", "walking"))


class TestGuessChecker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.check = GuessChecker(CATEGORIES)

    def assertMatches(self, guess, expected):
        self.assertEqual(self.check.matches(guess), set(expected), f"guess {guess!r}")

    def test_category_names(self):
        self.assertMatches("walk", ["walk"])
        self.assertMatches("Jumping Jacks", ["jumping jacks"])

    def test_synonyms_and_phrases_in_sentences(self):
        self.assertMatches("a person walking", ["walk"])
        self.assertMatches("they're jogging!", ["run"])
        self.assertMatches("climbing a ladder", ["climb"])

    def test_typo_forgiven_for_long_words(self):
        self.assertMatches("runnig", ["run"])
        self.assertMatches("cartweel", ["cartwheel"])

    def test_no_typo_forgiveness_for_short_words(self):
        self.assertMatches("wlk", [])      # "walk" is under 5 letters
        self.assertMatches("jumo", [])

    def test_exact_word_beats_typo(self):
        # "mopping" (sweep) is one edit from "hopping" (jump): exact wins.
        self.assertMatches("mopping", ["sweep"])
        self.assertMatches("hopping", ["jump"])

    def test_longer_phrase_wins(self):
        self.assertMatches("star jump", ["jumping jacks"])
        self.assertMatches("star jumps", ["jumping jacks"])
        self.assertMatches("bouncing a ball", ["basketball"])
        self.assertMatches("kicking a ball", ["kick"])

    def test_two_categories_is_wrong(self):
        self.assertMatches("walk or run", ["walk", "run"])
        self.assertFalse(self.check.is_correct("walk or run", "walk"))

    def test_is_correct(self):
        self.assertTrue(self.check.is_correct("Sneaking around", "sneak"))
        self.assertFalse(self.check.is_correct("sneaking", "limp"))
        self.assertFalse(self.check.is_correct("", "walk"))
        self.assertFalse(self.check.is_correct("?!", "walk"))

    def test_word_inside_other_word_does_not_match(self):
        self.assertMatches("walkie talkie", [])   # "walk" only as a whole word
        self.assertMatches("this", [])            # not "hi" + "s"

    def test_word_forms(self):
        for guess, category in [("walks", "walk"), ("walked", "walk"), ("walker", "walk"),
                                ("runs", "run"), ("runner", "run"), ("jogger", "run"),
                                ("jumps", "jump"), ("kicks", "kick"), ("waves", "wave"),
                                ("dancer", "dance"), ("boxer", "boxing"), ("punches", "boxing"),
                                ("hopped", "jump"), ("golfer", "golf"), ("tiptoes", "sneak")]:
            self.assertMatches(guess, [category])

    def test_word_forms_in_phrases(self):
        self.assertMatches("climbs a ladder", ["climb"])
        self.assertMatches("doing cartwheels", ["cartwheel"])
        self.assertMatches("goose stepping", ["march"])

    def test_short_words_keep_their_form(self):
        self.assertMatches("his", [])             # under 4 letters: never "hi"
        self.assertMatches("hi", ["wave"])

    def test_filler_words_ignored(self):
        self.assertMatches("bouncing ball", ["basketball"])
        self.assertMatches("climbing the ladder", ["climb"])
        self.assertMatches("the", [])

    def test_typo_inside_a_phrase(self):
        self.assertMatches("jumpin jacks", ["jumping jacks"])

    def test_irregular_forms_are_synonyms(self):
        for guess, category in [("ran", "run"), ("sat", "sit"), ("threw", "throw"),
                                ("drank", "drink"), ("snuck", "sneak")]:
            self.assertMatches(guess, [category])

    def test_specific_phrase_beats_its_parts(self):
        self.assertMatches("walking with a limp", ["limp"])
        self.assertMatches("skipping", ["jump"])   # not a typo of "sipping" (drink)

    def test_long_guesses_are_cut(self):
        self.assertMatches("x " * 30 + "walk", [])


class TestCategoryData(unittest.TestCase):
    """Rules for data/categories.json (spec section 4)."""

    def test_no_term_in_two_categories(self):
        # Compared as the checker reads them: base forms, no filler words.
        check = GuessChecker(CATEGORIES)
        seen = {}
        for category, synonyms in CATEGORIES.items():
            for term in [category, *synonyms]:
                key = check.base_words(normalize(term).split())
                if seen.get(key) == category:
                    continue                  # "jacks" and "jack": the same term
                self.assertNotIn(key, seen, f"{term!r} is in {seen.get(key)!r} and {category!r}")
                seen[key] = category

    def test_every_term_alone_matches_only_its_category(self):
        check = GuessChecker(CATEGORIES)
        for category, synonyms in CATEGORIES.items():
            for term in [category, *synonyms]:
                with self.subTest(term=term):
                    self.assertEqual(check.matches(term), {category})

    def test_terms_fit_in_a_guess(self):
        for category, synonyms in CATEGORIES.items():
            for term in [category, *synonyms]:
                self.assertLessEqual(len(term), rules.MAX_GUESS_CHARS, term)

    def test_every_clip_category_has_synonyms_entry(self):
        import json
        index = json.loads((ROOT / "data" / "clips" / "index.json").read_text())
        for clip in index["clips"]:
            self.assertIn(clip["category"], CATEGORIES, clip["id"])


class TestRevealOrderMatchesViewer(unittest.TestCase):
    def test_same_order_as_display_js(self):
        js = (ROOT / "web" / "js" / "display.js").read_text()
        block = re.search(r"REVEAL_ORDER = \[(.*?)\];", js, re.S).group(1)
        self.assertEqual(tuple(re.findall(r'"(\w+)"', block)), rules.REVEAL_ORDER)

    def test_order_covers_all_markers(self):
        import json
        markers = json.loads((ROOT / "data" / "clips" / "index.json").read_text())["markers"]
        self.assertEqual(sorted(rules.REVEAL_ORDER), sorted(markers))
        self.assertEqual(len(rules.REVEAL_ORDER), rules.TOTAL_DOTS)


if __name__ == "__main__":
    unittest.main()
