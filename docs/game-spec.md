# Skugga: game specification

A party guessing game for phones on the same Wi-Fi. Each round, every phone
shows the same motion-capture clip as a point-light display: it starts as a
single moving dot, and more of the figure's joints appear over about 20
seconds. The first player to type the right action scores, and the earlier
they get it, the more points they score.

Status: **draft**. The core rules (sections 2.1–2.4) are decided. Defaults
marked *(default)* are proposals that can still change.

---

## 1. Overview

- **One small server, everyone on their own phone.** One player (the host)
  runs a small server on a computer. Everyone, the host included, opens the
  address it prints on their own phone's browser, on the same Wi-Fi. There's no app to install, no
  account, and no internet connection needed during play.
- **Every phone shows the figure.** There's no shared screen: each phone
  shows the dots, a guess box, and the scores.
- **The server is the referee.** It runs the clock, decides how many dots are
  showing, checks guesses, and decides who was first. Phones only show what
  the server says and send what the player types.

### 1.1 Design goals

- **Least information first.** A round starts with as little as possible: one
  dot. The game rewards reading human motion from very little.
- **No setup friction.** Enter a name and play.
- **Fair.** Timing and scoring are judged by the server. A phone can't see more
  of the figure, or the answer, before the rules allow it (section 5).
- **Small and dependency-free.** The server is standard-library Python; the
  phone page is plain JavaScript modules with no build step.

---

## 2. Rules

### 2.1 A round (decided)

1. Every phone shows the same clip, starting with **5 dots**.
2. A dot is added every **0.7 seconds** until all **31** joints of the CMU
   skeleton show (about 20 seconds). The clip loops the whole time.
3. Players type guesses whenever they like. **The first correct guess wins
   the round.**

### 2.2 Guesses (decided)

- **One guess per clip.** A wrong guess puts that player out until the next
  clip. They keep watching.
- A guess is correct if it names the clip's category: the category's own name
  or any of its synonyms in `data/categories.json` (section 4).

### 2.3 Reveal (decided)

The standard reveal is **dots only**: no distractor dots, upright figure.
Distractor dots ("noise") and an upside-down start are possible later as
optional harder modes (section 9).

### 2.4 Scoring (decided)

The winner of a round scores **32 minus the number of dots showing** when the
server receives their guess: 27 points at the start (5 dots), 16 points at 16
dots, 1 point with the full figure of 31 (and during the grace period after
it). Nobody else
scores in that round, and wrong guesses cost nothing beyond being out.

### 2.5 End of a round *(default)*

A round ends when:

- someone guesses correctly; or
- every player still in the round has guessed wrong; or
- nobody has it **5 seconds** after the full figure appears.

The answer is then shown on every phone for **5 seconds**: the category, who
won and their points, and every guess made in the round. Then the next round
starts.

### 2.6 Seeing other players' guesses *(default)*

During a round, players see **that** someone guessed wrong ("Ben ✗") but not
**what** they guessed, so a wrong guess doesn't help others rule an answer
out. All guesses are shown when the round ends.

### 2.7 A game *(default)*

- **10 rounds**, each with a different category, and a clip from that
  category.
- Categories and clips are dealt like shuffled decks that carry over from
  game to game for as long as the server runs: every category comes up once
  before any comes up again, and within a category every clip plays before
  any plays again. With 25 categories, three games in a row show all of them.
- After the last round, a final scoreboard and a **Play again** button. Play
  again keeps the same players and resets scores.
- **2 to 8 players.**

### 2.8 Lobby *(default)*

1. Each player enters a name (1–16 characters).
2. The **first player to join is the game leader** and sees a **Start**
   button. The leader can start once at least 2 players have joined.
3. Players can join until the game starts. Someone who opens the page during
   a game sees "Game in progress" and joins the lobby for the next game.

### 2.9 Reconnecting *(default)*

If a phone reloads the page or drops off Wi-Fi briefly, it gets its place and
score back (section 6.2). A player whose phone hasn't checked in for
**30 seconds** is shown as away and doesn't count toward "every player has
guessed wrong". If the leader is away, the next player to have joined
becomes the leader. An away player keeps their place until the game is
full and someone new joins: the newcomer then takes the place of the
player who has been away longest. That player's name stays in the current
round's answer, and their phone, if it comes back, shows the join screen.

---

## 3. Reveal timing

All timing is in server milliseconds.

| Constant | Value | Meaning |
|---|---|---|
| `COUNTDOWN_MS` | 3000 | "Get ready" countdown before each round |
| `START_DOTS` | 5 | Dots showing when the reveal starts |
| `TOTAL_DOTS` | 31 | Dots in the full figure |
| `DOT_INTERVAL_MS` | 700 | Time between dots |
| `GRACE_MS` | 5000 | Time after the full figure before the round ends unanswered |
| `ANSWER_MS` | 5000 | How long the answer is shown between rounds |

With the round's reveal starting at server time `t0`, the dots showing at
server time `t` are:

```
dots(t) = min(31, 5 + floor((t - t0) / DOT_INTERVAL_MS))
```

The 31st dot appears at `t0 + 26 × 700 = t0 + 18.2 s`, and an unanswered
round ends at `t0 + 23.2 s`.

Dots are added in the viewer's `REVEAL_ORDER`, least telling first. The
first five (left ankle, right wrist, head, right knee, left elbow) show
from the start; then come the rest of the main joints with the spine and
neck points mixed in; the feet and hands, which give away the most for
actions like kicking, drinking and waving, come last.

Phones animate the dots smoothly by combining the server's time from their
last check-in with how long ago that was. The **server's**
dot count is what scores.

---

## 4. Checking guesses

The server checks guesses; phones never know the answer before the round ends.

1. **Normalize:** lowercase; turn anything that isn't a letter, digit or space
   into a space; collapse spaces; trim.
2. **Read each word:** the filler words "a", "an" and "the" are dropped,
   here and in the names and synonyms, so "bouncing ball" is the same as
   "bouncing a ball". Every other word is read as its base form: the
   shortest of the word and the word with an ending taken off ("-ing",
   "-ed", "-er", "-es", "-s", then perhaps adding an "e" or undoubling the
   last letter) that is a word in some name or synonym. So "walks",
   "walked", "walker" and "walking" all read as "walk", "runner" as "run"
   and "punches" as "punch". Words under 4 letters keep their form ("his"
   is never "hi"). Irregular forms ("ran", "sat", "threw") are synonyms.
3. **Forgive typos, but exact wins:** a guess word with no base form may
   instead be a word of 5 letters or more from a name or synonym that is
   one edit away (one letter added, removed or changed), so "runnig" reads
   as "running" (*run*) and "jumpin jacks" as *jumping jacks*. A word that
   has a base form is never typo-matched: "mopping" is *sweep*, even though
   it is one letter from "hopping" (*jump*). Words under 5 letters must be
   exact or a form of a known word.
4. **Match phrases:** a category matches if its name or one of its synonyms,
   read the same way, appears in the guess as whole words (so "a person
   walking" matches *walk*, and "climbs a ladder" matches *climb* through
   "climbing a ladder").
5. **Prefer longer phrases:** when one match is part of a longer one ("jump"
   inside "star jump", "bounce" inside "bounce ball"), only the longer one
   counts, so "star jump" is *jumping jacks*, not *jump*, and "walking with
   a limp" is *limp*, not *walk*.
6. **Decide:** the guess is correct if it matches exactly one category and
   that is the clip's category. A guess that matches **two or more**
   categories ("walk or run") is wrong, so listing several answers in one
   guess doesn't work.

Data rules, checked by unit tests whenever `data/categories.json` changes:

- no name or synonym, read as in step 2, belongs to two categories;
- every name and synonym, typed on its own as a guess, matches its own
  category and no other under steps 1–6 (this catches near-misses like
  "hopping"/"mopping" and phrases hidden inside other phrases).

---

## 5. Keeping the answer secret

The clip files in `data/clips/` are public and include each clip's category.
Two things would let a phone (or a player with developer tools open) cheat,
and the server prevents both:

- **The clip and its category.** The server never sends a clip's CMU id,
  description or category during a round. A round's clip is known to phones
  only by a random round id. The answer is sent when the round ends.
- **Seeing dots early.** If a phone received the whole clip at the start, it
  could draw all 31 dots straight away. Instead, the server sends each dot's
  motion only when that dot is revealed: when `dots(t)` goes up, phones fetch
  that one marker's track for the round.

**Limit:** someone determined could still compare the motion they receive with
the public clip files to find the clip. To make that harder, the server applies
a random viewing angle (within ±30° of the side view), a random start frame and
a random left-right mirror to each round's clip, and sends positions relative
to the pelvis. Skugga is a party game among friends, not a tournament, so this
is the intended level of protection.

---

## 6. Architecture

### 6.1 Parts

| Part | Where | What |
|---|---|---|
| Server | `server/skugga_server.py` | Standard-library Python (`http.server.ThreadingHTTPServer`). Holds the game in memory behind one lock: one game at a time. Serves the phone page and the JSON API. |
| Game rules | `server/rules.py` | Guess checking, scoring and round timing as pure functions, so they're unit-tested without a server. |
| Phone page | `web/play/` | Plain JavaScript with no build step. Draws the 2D dot tracks the server sends. |
| Data | `data/clips/`, `data/categories.json` | Read by the server at startup. Phones never fetch these directly during a game. |

### 6.2 Players and tokens

- Joining returns a random **player token** (`secrets.token_urlsafe(16)`),
  which the phone keeps in `localStorage` and sends with every request.
- A guess is accepted only with a valid token, and only for that token's
  player. One phone can't guess as another.
- Reloading the page sends the stored token, so the player gets their place
  and score back.

### 6.3 Polling

Phones call `GET /state` every **250 ms**. That's simpler than
WebSockets, needs no dependencies, and is quick enough for a game on home
Wi-Fi. Every response includes the server's current time (`serverNow`).

### 6.4 HTTP API

All POST bodies are JSON (`Content-Type: application/json` is required) and
at most 1 KB.

| Method and path | Body | Does |
|---|---|---|
| `GET /` | | The phone page |
| `GET /state?token=…` | | The game as this player should see it (section 6.5) |
| `POST /join` | `{name, token?}` | Joins the lobby, or rejoins with a stored token; returns `{token, playerId}` |
| `POST /start` | `{token}` | Leader only: starts the game |
| `POST /guess` | `{token, roundId, guess}` | One guess for the current round (at most 40 characters); returns `{correct}` |
| `POST /again` | `{token}` | Leader only: Play again after the final scoreboard |
| `GET /round/<roundId>/marker/<n>?token=…` | | Track of revealed dot `n` (0–14) for this round. Refused if that dot isn't revealed yet. |

### 6.5 State sent to phones

The game state, with nothing a phone shouldn't know yet:

- `status`: `lobby`, `countdown`, `reveal`, `answer` or `final`
- `serverNow`, the round's `t0`, `roundId`, round number and `dotsShown`
- players: name, score, in or out this round, away or not, leader or not.
  Other players' tokens are never included.
- during `reveal`: which players have guessed wrong, but not what they guessed
- during `answer` and `final`: the category, the winner and their points,
  every guess of the round, and the clip's CMU id and description (for credit)

### 6.6 Network and security

The server has to be reachable from phones on the home network, so it binds to
the computer's network interfaces. It assumes a trusted home network, and
protects against the realistic risks there: one player's phone acting as
another (which matters with one guess per clip), and other websites reaching
the server through a player's browser. It:

- requires a player token for guesses and leader actions (section 6.2);
- accepts only JSON POST bodies of at most 1 KB, and guesses and names of
  limited length;
- answers only requests whose `Host` header is an IP address, `localhost` or
  the computer's own name, which stops other websites from reaching it
  through the player's browser (DNS rebinding);
- shows names and guesses with `textContent`, never as HTML;
- serves only the phone page, its scripts, and the API, not the rest of the
  repository.

It is still meant for a trusted home network: there's no HTTPS and no
password. The README will say so.

---

## 7. Phone screens

1. **Join:** name box and Join button.
2. **Lobby:** the players so far; the leader sees Start.
3. **Countdown:** "Round 3 of 10", counting down 3, 2, 1.
4. **Reveal:** the dots on black; "9 / 31 dots" and the points a correct guess
   would score now; the guess box (disabled once you've guessed); the
   scoreboard with ✗ next to players who are out.
5. **Answer:** the category, who won and how many points, everyone's guesses,
   and the clip's credit line.
6. **Final:** the scoreboard, and Play again for the leader.

The phone page works in portrait at phone width, with no horizontal scrolling,
and keeps the screen awake during a game where the browser allows it.

---

## 8. Testing

- **Rules unit tests** (`python3 -m unittest`, standard library):
  - every category name and synonym matches its own category;
  - typo tolerance, phrase matching and the "longer phrase wins" rule;
  - a guess naming two categories is wrong;
  - no synonym belongs to two categories (data check);
  - dot timing and scoring at the boundaries;
  - round end conditions.
- **Server tests:** the API with several simulated players, including one
  guess per clip, wrong tokens, the leader's actions, reconnecting, and that
  marker tracks aren't served early.
- **Smoke test:** a headless browser plays a whole game with several phone
  pages at once.

All of these run in CI on every pull request.

---

## 9. Later

- Harder modes: distractor dots, upside-down start, faster reveal.
- A shared-screen mode (TV shows the dots; phones only for guessing).
- A QR code for joining.
- Curating clips: dropping or trimming ambiguous ones before relying on early
  guesses (section 2.4 makes a bad clip feel unfair).
