"""Tests for server/game.py: the game with a fake clock (spec sections 2, 5, 6)."""
import json
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import rules  # noqa: E402
from game import (  # noqa: E402
    ANSWER_MS, AWAY_MS, COUNTDOWN_MS, MAX_PLAYERS, Game, GameError, clean_name,
    load_clips, make_round_view,
)

CLIPS = load_clips(ROOT / "data")
CATEGORIES = rules.load_categories(ROOT / "data" / "categories.json")
INTERVAL = rules.DOT_INTERVAL_MS


class GameTest(unittest.TestCase):
    def setUp(self):
        self.g = Game(CLIPS, CATEGORIES, rng=random.Random(1))
        self.now = 1_000_000

    def join(self, name):
        return self.g.join(self.now, name).token

    def advance(self, ms):
        self.now += ms
        self.g.tick(self.now)

    def started(self, n=3):
        tokens = [self.join(f"P{i}") for i in range(n)]
        self.g.start(self.now, tokens[0])
        self.advance(COUNTDOWN_MS)
        self.assertEqual(self.g.status, "reveal")
        return tokens

    def answer(self):
        return self.g.round.clip.category

    def wrong(self):
        return next(c for c in CATEGORIES if c != self.answer())

    def guess(self, token, text):
        return self.g.guess(self.now, token, self.g.round.id, text)

    def assertRefused(self, code, fn, *args):
        with self.assertRaises(GameError) as e:
            fn(*args)
        self.assertEqual(e.exception.code, code)


class TestLobby(GameTest):
    def test_first_player_leads_and_needs_two(self):
        a = self.join("Ana")
        self.assertTrue(self.g.state(self.now, a)["you"]["leader"])
        self.assertRefused("too_few_players", self.g.start, self.now, a)
        b = self.join("Ben")
        self.assertRefused("not_leader", self.g.start, self.now, b)
        self.g.start(self.now, a)
        self.assertEqual(self.g.status, "countdown")

    def test_names(self):
        self.assertEqual(clean_name("  Ana   Lee "), "Ana Lee")
        self.assertEqual(clean_name("Ben​\x07"), "Ben")
        for bad in ["", "   ", "x" * 17, None, 5, "\x00\x01"]:
            with self.assertRaises(GameError):
                clean_name(bad)
        self.join("Ana")
        self.assertRefused("name_taken", self.g.join, self.now, "ANA")

    def test_full_at_max_players(self):
        for i in range(MAX_PLAYERS):
            self.join(f"P{i}")
        self.assertRefused("full", self.g.join, self.now, "Late")

    def test_newcomer_takes_longest_away_place_when_full(self):
        tokens = [self.join(f"P{i}") for i in range(MAX_PLAYERS)]
        self.g.touch(self.now + 1, tokens[1])      # P0 and P1 go away; P0 left first
        self.now += AWAY_MS + 2
        for t in tokens[2:]:
            self.g.touch(self.now, t)
        late = self.g.join(self.now, "Late")
        names = [p["name"] for p in self.g.state(self.now, late.token)["players"]]
        self.assertNotIn("P0", names)
        self.assertIn("P1", names)
        self.assertEqual(len(names), MAX_PLAYERS)
        self.assertRefused("bad_token", self.g.start, self.now, tokens[0])
        self.g.join(self.now, "P0")                # the name is free again (P1's place)
        self.assertRefused("full", self.g.join, self.now, "Another")

    def test_replaced_player_still_named_in_answer(self):
        tokens = self.started(2)
        for i in range(2, MAX_PLAYERS):
            self.join(f"W{i}")                     # waiting for the next game
        self.guess(tokens[1], self.wrong())
        self.now += AWAY_MS + 1                    # P1 goes away; the rest check in
        for p in self.g.players:
            if p.token != tokens[1]:
                self.g.touch(self.now, p.token)
        self.g.join(self.now, "Late")
        self.guess(tokens[0], self.answer())
        guesses = self.g.state(self.now, tokens[0])["answer"]["guesses"]
        self.assertEqual([g["name"] for g in guesses], ["P1", "P0"])

    def test_reconnect_with_token_keeps_player(self):
        a = self.join("Ana")
        p = self.g.join(self.now, "anything", a)
        self.assertEqual((p.name, p.token), ("Ana", a))
        self.assertEqual(len(self.g.players), 1)

    def test_bad_token(self):
        self.assertRefused("bad_token", self.g.start, self.now, "nope")
        self.assertRefused("bad_token", self.g.start, self.now, None)

    def test_joining_during_game_waits_for_next(self):
        tokens = self.started(2)
        late = self.g.join(self.now, "Late")
        self.assertTrue(late.waiting)
        self.assertRefused("waiting_for_next_game", self.guess, late.token, self.answer())
        # the late player doesn't count toward "everyone out"
        for t in tokens:
            self.guess(t, self.wrong())
        self.g.tick(self.now)
        self.assertEqual(self.g.round.end_reason, "all_out")


class TestRound(GameTest):
    def test_countdown_then_one_dot(self):
        a = self.join("Ana"); self.join("Ben")
        self.g.start(self.now, a)
        self.assertRefused("round_not_open", self.g.guess, self.now, a, self.g.round.id, "walk")
        self.advance(COUNTDOWN_MS)
        self.assertEqual(self.g.state(self.now, a)["round"]["dotsShown"], rules.START_DOTS)

    def test_correct_guess_scores_by_dots(self):
        a, b, _ = self.started()
        self.advance(4 * INTERVAL)  # 9 dots showing
        self.assertTrue(self.guess(b, self.answer()))
        self.assertEqual(self.g.status, "answer")
        self.assertEqual(self.g.round.points, 23)
        self.assertEqual(self.g.by_token[b].score, 23)
        self.assertEqual(self.g.round.end_reason, "answered")

    def test_synonym_counts(self):
        a, *_ = self.started()
        synonym = CATEGORIES[self.answer()][0]
        self.assertTrue(self.guess(a, f"I think {synonym}!"))

    def test_wrong_guess_puts_you_out(self):
        a, b, c = self.started()
        self.assertFalse(self.guess(a, self.wrong()))
        self.assertRefused("already_guessed", self.guess, a, self.answer())
        self.assertEqual(self.g.status, "reveal")
        st = self.g.state(self.now, b)
        self.assertEqual([p["out"] for p in st["players"]], [True, False, False])

    def test_everyone_out_ends_round(self):
        tokens = self.started()
        for t in tokens:
            self.guess(t, self.wrong())
        self.g.tick(self.now)
        self.assertEqual((self.g.status, self.g.round.end_reason), ("answer", "all_out"))
        self.assertEqual(self.g.round.points, 0)

    def test_timeout_after_grace(self):
        self.started()
        self.advance(rules.round_deadline(0) - 1)
        self.assertEqual(self.g.status, "reveal")
        self.advance(1)
        self.assertEqual((self.g.status, self.g.round.end_reason), ("answer", "timeout"))

    def test_wrong_round_id_or_long_guess(self):
        a, *_ = self.started()
        self.assertRefused("round_not_open", self.g.guess, self.now, a, "0" * 16, "walk")
        self.assertRefused("guess_too_long", self.guess, a, "w" * 41)
        self.assertRefused("bad_guess", self.guess, a, 42)

    def test_answer_shown_then_next_round(self):
        a, *_ = self.started()
        self.guess(a, self.answer())
        first = self.g.round.id
        self.advance(ANSWER_MS - 1)
        self.assertEqual(self.g.status, "answer")
        self.advance(1)
        self.assertEqual((self.g.status, self.g.round.number), ("countdown", 2))
        self.assertNotEqual(self.g.round.id, first)
        self.assertTrue(all(p.guess is None for p in self.g.players))


class TestDealing(GameTest):
    """Rounds are dealt from decks, so games don't repeat each other."""

    def games(self, n):
        plans = []
        for _ in range(n):
            self.g._plan_game()
            plans.append(list(self.g.plan))
        return plans

    def test_every_category_before_any_repeats(self):
        all_categories = {c.category for c in CLIPS}
        for seed in range(20):
            self.g = Game(CLIPS, CATEGORIES, rng=random.Random(seed))
            g1, g2 = self.games(2)
            for game in (g1, g2):
                self.assertEqual(len({c.category for c in game}), 10)   # no repeats in a game
            # 20 rounds over 19 categories: every one of them, before any twice
            first_19 = [c.category for c in g1 + g2][:len(all_categories)]
            self.assertEqual(set(first_19), all_categories)

    def test_every_clip_of_a_category_before_any_repeats(self):
        dealt: dict[str, list[str]] = {}
        for game in self.games(40):
            for clip in game:
                dealt.setdefault(clip.category, []).append(clip.id)
        for category, ids in dealt.items():
            n = len({c.id for c in CLIPS if c.category == category})
            for start in range(0, len(ids) - n + 1, n):
                self.assertEqual(len(set(ids[start:start + n])), n, category)


class TestWholeGame(GameTest):
    def test_ten_rounds_distinct_categories_then_final_and_again(self):
        a, b = self.started(2)
        seen = []
        for n in range(1, 11):
            self.assertEqual((self.g.round.number, self.g.status), (n, "reveal"))
            seen.append(self.answer())
            self.guess(a, self.answer())          # 27 points each, at 5 dots
            self.advance(ANSWER_MS)
            if n < 10:
                self.advance(COUNTDOWN_MS)
        self.assertEqual(self.g.status, "final")
        self.assertEqual(len(set(seen)), 10)
        self.assertEqual(self.g.by_token[a].score, 270)
        self.assertRefused("not_leader", self.g.again, self.now, b)
        self.g.again(self.now, a)
        self.assertEqual((self.g.status, self.g.by_token[a].score), ("countdown", 0))

    def test_catches_up_when_nobody_asks(self):
        self.started(2)
        self.advance(10 * 60 * 1000)   # ten minutes of silence
        self.assertEqual(self.g.status, "final")


class TestAwayAndLeader(GameTest):
    def test_leader_moves_when_away(self):
        a = self.join("Ana")
        self.now += 1
        b = self.join("Ben")
        self.now += AWAY_MS + 1
        self.g.state(self.now, b)  # Ben checks in, Ana doesn't
        self.assertTrue(self.g.state(self.now, b)["you"]["leader"])
        self.g.state(self.now, a)  # Ana back: leader again
        self.assertTrue(self.g.state(self.now, a)["you"]["leader"])

    def sleep_all(self):
        """Every phone last checked in more than AWAY_MS ago."""
        for p in self.g.players:
            p.last_seen = self.now - AWAY_MS - 1

    def test_nobody_present_ends_by_clock_not_all_out(self):
        self.started(2)
        self.sleep_all()
        self.advance(1000)
        self.assertEqual(self.g.status, "reveal")   # not ended as "everyone out"
        self.advance(rules.round_deadline(0))
        self.assertEqual(self.g.round.end_reason, "timeout")

    def test_returning_player_is_not_away_during_catch_up(self):
        a, b = self.started(2)
        self.guess(b, self.wrong())          # Ben is out (and present)
        self.g.by_token[a].last_seen = self.now - AWAY_MS - 1   # Ana's phone asleep
        self.now += 1000
        self.g.touch(self.now, a)            # Ana's phone wakes up
        self.g.tick(self.now)
        self.assertEqual(self.g.status, "reveal")   # Ana can still guess
        self.assertTrue(self.guess(a, self.answer()))

    def test_away_players_dont_block_all_out(self):
        a, b, c = self.started()
        self.now += AWAY_MS + 1
        self.g.state(self.now, a)
        self.g.state(self.now, b)
        self.guess(a, self.wrong())
        self.guess(b, self.wrong())
        self.g.tick(self.now)
        self.assertEqual(self.g.round.end_reason, "all_out")


class TestSecrecy(GameTest):
    """Spec section 5: phones get nothing that names the clip, and no dot
    before it's revealed."""

    def test_state_during_reveal_has_no_answer(self):
        a, b, _ = self.started()
        self.guess(b, self.wrong())
        text = json.dumps(self.g.state(self.now, a))
        clip = self.g.round.clip
        for secret in (clip.id, clip.description, f'"{clip.category}"', self.wrong()):
            self.assertNotIn(secret, text)
        self.assertNotIn("answer", self.g.state(self.now, a))
        for p in self.g.state(self.now, a)["players"]:
            self.assertNotIn("token", p)

    def test_answer_revealed_after_round(self):
        a, b, _ = self.started()
        self.guess(b, self.wrong())
        self.guess(a, self.answer())
        ans = self.g.state(self.now, a)["answer"]
        self.assertEqual(ans["category"], self.answer())
        self.assertEqual([g["correct"] for g in ans["guesses"]], [False, True])

    def test_tracks_only_once_revealed(self):
        a, *_ = self.started()
        rid = self.g.round.id
        first = rules.START_DOTS                     # dots 0..4 show from the start
        self.assertEqual(len(self.g.track(self.now, a, rid, first - 1)), 2 * self.g.round.view.frame_count)
        self.assertRefused("not_revealed_yet", self.g.track, self.now, a, rid, first)
        self.advance(INTERVAL)
        self.g.track(self.now, a, rid, first)
        self.assertRefused("not_revealed_yet", self.g.track, self.now, a, rid, first + 1)
        self.assertRefused("bad_token", self.g.track, self.now, "x", rid, 0)
        self.assertRefused("no_such_round", self.g.track, self.now, a, "0" * 16, 0)
        self.assertRefused("no_such_marker", self.g.track, self.now, a, rid, rules.TOTAL_DOTS)
        self.guess(a, self.answer())                 # answer phase: all dots
        self.g.track(self.now, a, rid, rules.TOTAL_DOTS - 1)

    def test_no_tracks_during_countdown(self):
        a = self.join("Ana"); self.join("Ben")
        self.g.start(self.now, a)
        self.assertRefused("no_such_round", self.g.track, self.now, a, self.g.round.id, 0)


class TestRoundView(unittest.TestCase):
    def test_transform_keeps_shape_and_varies(self):
        clip = next(c for c in CLIPS if c.id == "02_01")
        v1 = make_round_view(clip, random.Random(1))
        v2 = make_round_view(clip, random.Random(2))
        self.assertEqual(len(v1.tracks), 31)
        self.assertEqual(v1.frame_count, len(clip.frames))
        self.assertNotEqual(v1.tracks, v2.tracks)
        pelvis = rules.REVEAL_ORDER.index("pelvis")
        self.assertTrue(all(x == 0 for x in v1.tracks[pelvis][0::2]))  # kept in place
        head = rules.REVEAL_ORDER.index("head")
        self.assertGreater(min(v1.tracks[head][1::2]), 1200)  # head stays high (mm)
        # heights are untouched by the view angle and mirror
        ys = lambda v, k: sorted(v.tracks[k][1::2])
        self.assertEqual(ys(v1, head), ys(v2, head))


if __name__ == "__main__":
    unittest.main()
