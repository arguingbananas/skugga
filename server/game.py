"""The game: players, lobby, rounds and guesses, held in memory.

See docs/game-spec.md, sections 2, 5 and 6. Everything takes the current
server time in milliseconds as an argument (`now`), so the whole game can
be tested without real waiting. The HTTP layer (skugga_server.py) calls
these methods under one lock.
"""
from __future__ import annotations

import json
import math
import random
import secrets
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import rules

COUNTDOWN_MS = 3000
ANSWER_MS = 5000
AWAY_MS = 30_000
ROUNDS = 10
MIN_PLAYERS = 2
MAX_PLAYERS = 8
MAX_NAME_CHARS = 16
MAX_AZIMUTH_DEG = 30


class GameError(Exception):
    """A request the game refuses. `status` is the HTTP status to answer."""

    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


# --- Clips -----------------------------------------------------------------

@dataclass(frozen=True)
class Clip:
    id: str
    category: str
    description: str
    fps: float
    markers: tuple[str, ...]
    frames: tuple[tuple[int, ...], ...]  # per frame: x, y, z for each marker, mm


def load_clips(data_dir: Path) -> list[Clip]:
    index = json.loads((data_dir / "clips" / "index.json").read_text(encoding="utf-8"))
    clips = []
    for entry in index["clips"]:
        raw = json.loads((data_dir / "clips" / entry["file"]).read_text(encoding="utf-8"))
        clips.append(Clip(raw["id"], raw["category"], raw["description"], raw["fps"],
                          tuple(raw["markers"]), tuple(tuple(f) for f in raw["frames"])))
    return clips


@dataclass(frozen=True)
class RoundView:
    """A round's clip as phones receive it: one 2D track per marker, in
    reveal order, after a random view angle, mirror and start frame, with the
    figure kept in place over the pelvis. Nothing in it names the clip."""
    fps: float
    frame_count: int
    tracks: tuple[tuple[int, ...], ...]  # per marker: x0, y0, x1, y1, ... (mm)
    min_x: int
    max_x: int
    max_y: int


def make_round_view(clip: Clip, rng: random.Random) -> RoundView:
    a = math.radians(rng.uniform(-MAX_AZIMUTH_DEG, MAX_AZIMUTH_DEG))
    direction = rng.choice((-1, 1))  # mirror: moving left or right
    start = rng.randrange(len(clip.frames))
    frames = clip.frames[start:] + clip.frames[:start]
    cos, sin = math.cos(a), math.sin(a)
    pelvis = clip.markers.index("pelvis")
    order = [clip.markers.index(name) for name in rules.REVEAL_ORDER]

    tracks: list[list[int]] = [[] for _ in order]
    min_x = max_x = max_y = 0
    for frame in frames:
        px, pz = frame[pelvis * 3], frame[pelvis * 3 + 2]
        for k, m in enumerate(order):
            x, y, z = frame[m * 3] - px, frame[m * 3 + 1], frame[m * 3 + 2] - pz
            sx = round(direction * (x * cos - z * sin))
            tracks[k] += (sx, y)
            min_x, max_x, max_y = min(min_x, sx), max(max_x, sx), max(max_y, y)
    return RoundView(clip.fps, len(frames), tuple(tuple(t) for t in tracks), min_x, max_x, max_y)


# --- Players and rounds ------------------------------------------------------

@dataclass
class Player:
    id: int
    name: str
    token: str
    joined_at: int
    last_seen: int
    score: int = 0
    waiting: bool = False      # joined during a game; plays from the next one
    guess: str | None = None   # this round's guess, if any
    guess_correct: bool = False

    def away(self, now: int) -> bool:
        return now - self.last_seen > AWAY_MS


@dataclass
class Round:
    number: int                # 1-based
    clip: Clip
    id: str                    # random; all phones see of the clip's identity
    view: RoundView
    t0: int                    # reveal starts (after the countdown)
    ended_at: int | None = None
    end_reason: str | None = None
    winner_id: int | None = None
    points: int = 0
    guesses: list[tuple[int, str, bool]] = field(default_factory=list)  # player id, text, correct


def clean_name(name: object) -> str:
    """A display name: printable characters only, spaces collapsed, 1 to 16
    characters. Raises GameError for anything else."""
    if not isinstance(name, str):
        raise GameError(400, "bad_name")
    name = "".join(c for c in unicodedata.normalize("NFC", name)
                   if unicodedata.category(c)[0] not in "CZ" or c == " ")
    name = " ".join(name.split())
    if not 1 <= len(name) <= MAX_NAME_CHARS:
        raise GameError(400, "bad_name")
    return name


class Game:
    def __init__(self, clips: list[Clip], categories: dict[str, list[str]], *,
                 rng: random.Random | None = None, rounds: int = ROUNDS):
        self.clips = clips
        self.checker = rules.GuessChecker(categories)
        self.rng = rng or random.SystemRandom()
        self.total_rounds = min(rounds, len({c.category for c in clips}))
        self.players: list[Player] = []
        self.by_token: dict[str, Player] = {}
        self.left_names: dict[int, str] = {}   # players whose place was given away
        self._next_id = 1
        self.status = "lobby"
        self.round: Round | None = None
        self.plan: list[Clip] = []

    # --- helpers

    def player(self, token: object) -> Player:
        p = self.by_token.get(token) if isinstance(token, str) else None
        if p is None:
            raise GameError(403, "bad_token")
        return p

    def leader(self, now: int) -> Player | None:
        """The earliest-joined present player, preferring those not waiting."""
        present = [p for p in self.players if not p.away(now)]
        playing = [p for p in present if not p.waiting]
        return (playing or present or [None])[0]

    def _players_in(self, now: int) -> int:
        """Present players who can still guess. If nobody is present at all
        (every phone asleep), nobody has guessed wrong either, so report one:
        the round then ends by the clock, not as 'everyone out'."""
        present = [p for p in self.players if not p.waiting and not p.away(now)]
        if not present:
            return 1
        return sum(1 for p in present if p.guess is None)

    def touch(self, now: int, token: object) -> None:
        """Note that a phone checked in. Call before tick(), so a returning
        player isn't treated as away while the game catches up."""
        p = self.by_token.get(token) if isinstance(token, str) else None
        if p is not None:
            p.last_seen = now

    def _plan_game(self) -> None:
        by_category: dict[str, list[Clip]] = {}
        for clip in self.clips:
            by_category.setdefault(clip.category, []).append(clip)
        categories = self.rng.sample(sorted(by_category), self.total_rounds)
        self.plan = [self.rng.choice(by_category[c]) for c in categories]

    def _start_round(self, number: int, now: int) -> None:
        clip = self.plan[number - 1]
        self.round = Round(number, clip, secrets.token_hex(8),
                           make_round_view(clip, self.rng), now + COUNTDOWN_MS)
        for p in self.players:
            p.guess, p.guess_correct = None, False
        self.status = "countdown"

    def _end_round(self, now: int, reason: str) -> None:
        self.round.ended_at, self.round.end_reason = now, reason
        self.status = "answer"

    # --- time passing

    def tick(self, now: int) -> None:
        """Advance countdown -> reveal -> answer -> next round or final, as
        far as `now` allows (several steps if nobody asked for a while)."""
        for _ in range(4 * ROUNDS + 4):  # bounded: 3 steps per round at most
            r = self.round
            if self.status == "countdown" and now >= r.t0:
                self.status = "reveal"
            elif self.status == "reveal":
                reason = rules.round_end_reason(now, r.t0, answered=r.winner_id is not None,
                                                players_in=self._players_in(now))
                if reason is None:
                    return
                end = min(now, rules.round_deadline(r.t0)) if reason == "timeout" else now
                self._end_round(end, reason)
            elif self.status == "answer" and now >= r.ended_at + ANSWER_MS:
                if r.number < self.total_rounds:
                    self._start_round(r.number + 1, r.ended_at + ANSWER_MS)
                else:
                    self.status = "final"
            else:
                return

    # --- actions

    def join(self, now: int, name: object, token: object = None) -> Player:
        if isinstance(token, str) and token in self.by_token:
            p = self.by_token[token]       # reconnecting
            p.last_seen = now
            return p
        name = clean_name(name)
        if any(p.name.casefold() == name.casefold() for p in self.players):
            raise GameError(409, "name_taken")
        if len(self.players) >= MAX_PLAYERS:
            away = [q for q in self.players if q.away(now)]
            if not away:
                raise GameError(409, "full")
            self._remove(min(away, key=lambda q: q.last_seen))
        p = Player(self._next_id, name, secrets.token_urlsafe(16), now, now,
                   waiting=self.status != "lobby")
        self._next_id += 1
        self.players.append(p)
        self.by_token[p.token] = p
        return p

    def _remove(self, p: Player) -> None:
        """Give an away player's place to someone new. Their name stays in
        this round's answer; their phone, if it comes back, must join again."""
        self.players.remove(p)
        del self.by_token[p.token]
        self.left_names[p.id] = p.name

    def _require_leader(self, now: int, token: object) -> Player:
        p = self.player(token)
        if p is not self.leader(now):
            raise GameError(403, "not_leader")
        return p

    def start(self, now: int, token: object) -> None:
        self._require_leader(now, token)
        if self.status != "lobby":
            raise GameError(409, "not_in_lobby")
        if sum(1 for p in self.players if not p.away(now)) < MIN_PLAYERS:
            raise GameError(409, "too_few_players")
        self._plan_game()
        self._start_round(1, now)

    def again(self, now: int, token: object) -> None:
        self._require_leader(now, token)
        if self.status != "final":
            raise GameError(409, "not_final")
        for p in self.players:
            p.score, p.waiting = 0, False
        self._plan_game()
        self._start_round(1, now)

    def guess(self, now: int, token: object, round_id: object, text: object) -> bool:
        p = self.player(token)
        p.last_seen = now
        if not isinstance(text, str) or not isinstance(round_id, str):
            raise GameError(400, "bad_guess")
        if len(text) > rules.MAX_GUESS_CHARS:
            raise GameError(400, "guess_too_long")
        r = self.round
        if self.status != "reveal" or r is None or round_id != r.id:
            raise GameError(409, "round_not_open")
        if p.waiting:
            raise GameError(409, "waiting_for_next_game")
        if p.guess is not None:
            raise GameError(409, "already_guessed")
        correct = self.checker.is_correct(text, r.clip.category)
        p.guess, p.guess_correct = text, correct
        r.guesses.append((p.id, text, correct))
        if correct:
            r.winner_id = p.id
            r.points = rules.points_for(rules.dots_shown(now, r.t0))
            p.score += r.points
            self._end_round(now, "answered")
        return correct

    def track(self, now: int, token: object, round_id: str, n: int) -> list[int]:
        """Marker n's track (reveal order), only once that dot is revealed."""
        p = self.player(token)
        p.last_seen = now
        r = self.round
        if r is None or round_id != r.id or self.status not in ("reveal", "answer"):
            raise GameError(404, "no_such_round")
        if not 0 <= n < rules.TOTAL_DOTS:
            raise GameError(404, "no_such_marker")
        revealed = rules.TOTAL_DOTS if self.status == "answer" else rules.dots_shown(now, r.t0)
        if n >= revealed:
            raise GameError(403, "not_revealed_yet")
        return list(r.view.tracks[n])

    # --- what a phone sees

    def state(self, now: int, token: object = None) -> dict:
        me = self.by_token.get(token) if isinstance(token, str) else None
        if me is not None:
            me.last_seen = now
        leader = self.leader(now)
        r = self.round
        show_answer = self.status in ("answer", "final")
        out = {
            "status": self.status,
            "serverNow": now,
            "totalRounds": self.total_rounds,
            "minPlayers": MIN_PLAYERS,
            "maxPlayers": MAX_PLAYERS,
            "players": [{
                "id": p.id,
                "name": p.name,
                "score": p.score,
                "leader": p is leader,
                "away": p.away(now),
                "waiting": p.waiting,
                "out": p.guess is not None and not p.guess_correct,
            } for p in self.players],
            "you": None if me is None else {
                "id": me.id,
                "guessed": me.guess is not None,
                "waiting": me.waiting,
                "leader": me is leader,
            },
        }
        if r is not None and self.status != "lobby":
            out["round"] = {
                "number": r.number,
                "id": r.id,
                "t0": r.t0,
                "dotsShown": rules.TOTAL_DOTS if show_answer else rules.dots_shown(now, r.t0),
                "dotIntervalMs": rules.DOT_INTERVAL_MS,
                "startDots": rules.START_DOTS,
                "totalDots": rules.TOTAL_DOTS,
                "fps": r.view.fps,
                "frameCount": r.view.frame_count,
                "bounds": {"minX": r.view.min_x, "maxX": r.view.max_x, "maxY": r.view.max_y},
                "deadline": rules.round_deadline(r.t0),
            }
            if show_answer:
                names = {**self.left_names, **{p.id: p.name for p in self.players}}
                out["answer"] = {
                    "category": r.clip.category,
                    "endReason": r.end_reason,
                    "winner": names.get(r.winner_id),
                    "points": r.points,
                    "guesses": [{"name": names.get(pid), "guess": text, "correct": ok}
                                for pid, text, ok in r.guesses],
                    "clipId": r.clip.id,
                    "description": r.clip.description,
                    "nextAt": (r.ended_at + ANSWER_MS) if self.status == "answer" else None,
                }
        return out
