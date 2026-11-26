# Skugga

*Skugga* (Swedish, "shadow") is a browser-based social guessing game built on
**biological motion perception**: the human ability to recognize an action from
just a handful of moving dots placed on the joints (Johansson, 1973).

![A single moving dot on black, joined by one more joint at a time until a full point-light walker appears and the answer "walk" is shown](docs/demo.webp)

> [!NOTE]
> **Made with AI.** This project is being built with
> [Claude Code](https://claude.com/claude-code), Anthropic's AI coding
> assistant (Claude), working under my direction: the data pipeline, game code,
> tests and documentation. I set the direction, make the design calls and
> judge what's fun and what reads as human motion. Commits Claude wrote or
> co-wrote name it in a `Co-Authored-By` trailer.

## Concept

Each round plays a motion-capture clip as a point-light display. It starts with
as little information as possible, a single moving dot, and more of the
figure's joints appear over about 20 seconds. The first player to name the
action scores, and the earlier they get it, the more points they score.

Everyone plays on their own phone: one player runs a small server on a computer,
and the others join from their phones' browsers on the same Wi-Fi. Guesses are
free text, and synonyms count ("jog" for *run*, "tiptoe" for *sneak*). Each
player gets one guess per clip. The actions are broad categories: walk, run,
jump, dance, boxing, kick, climb, sit, throw, basketball, jumping jacks,
cartwheel, march, sneak, sweep, wave, golf, limp and drink.

The rules and design are in [docs/game-spec.md](docs/game-spec.md). To play,
start the game server (below) and open the address it prints on each phone.

## Repository layout

| Path | What it is |
|------|------------|
| `data/clips/` | Built point-light clips (JSON), one per file, plus `index.json` |
| `data/categories.json` | Action categories and the synonyms accepted as correct guesses |
| `pipeline/clips.toml` | Which CMU trials become clips, and their categories |
| `pipeline/cmu_index.json` | Index of all 2,379 CMU trials with descriptions, for choosing clips |
| `pipeline/*.py` | The data pipeline (Python 3.11+, standard library only) |
| `server/` | The game server: `rules.py` (guessing, timing, scoring), `game.py` (players and rounds), `skugga_server.py` (HTTP) |
| `web/` | Clip viewer (static site; `web/js/display.js` is the reusable display model) |
| `tests/` | Unit tests for the rules, game and server, and a headless-browser smoke test for the viewer |
| `tools/` | Local static server, the README demo renderer, and the actionlint installer |
| `docs/` | The game specification, and README media |

## Game server

```sh
npm run game         # or: python3 server/skugga_server.py [port]   (default 8765)
```

It prints an address to open on each phone (same Wi-Fi); everyone enters a
name, and the first player to join starts the game. The server assumes a
trusted home network: no HTTPS, no password. It gives each player a token so
no phone can act as another, accepts only small JSON requests, and refuses
requests addressed to other host names. See
[docs/game-spec.md](docs/game-spec.md), section 6.

## Viewer

`web/` is a clip viewer for trying out reveal settings: how many dots,
scrambled-dot noise, upside down, camera angle, speed, and an auto-reveal
that adds dots and removes noise over time. It's plain JavaScript modules
with no build step. To run it:

```sh
npm run serve        # then open http://127.0.0.1:8000/web/
```

Starting settings can go in the URL, e.g.
`/web/?dots=5&noise=30&inv=1&hide=1#13_17` (see `applyQuery` in
`web/js/viewer.js`).

Tests (Node 22.13+, Chromium, pyflakes (`apt install python3-pyflakes`) and
actionlint (`bash tools/install-actionlint.sh`)):

```sh
npm install          # dev dependency: puppeteer-core (uses your system Chromium)
npm run check        # syntax-check the JS
npm run lint         # ESLint, pyflakes and actionlint
npm test             # unit tests: game rules, game, and the server's HTTP API (Python)
npm run smoke        # drive the viewer in headless Chromium; add a folder to save screenshots
npm run smoke:game   # three phones play a short game against the real server (~15 s)
npm run demo         # re-render docs/demo.webp (needs img2webp: apt install webp)
```

## Data pipeline

The built clips are committed, so playing the game doesn't require running the
pipeline. To rebuild them, or to add clips:

```sh
python3 pipeline/cmu_index.py      # (re)build the trial index; only needed once
python3 pipeline/build.py          # download, convert and validate every clip in clips.toml
python3 pipeline/build.py 02_01    # or just some clips
python3 pipeline/preview.py sheet.png 02_01 09_01   # contact sheet for eyeballing clips
```

`build.py` downloads the original ASF/AMC files from the CMU site into
`data/raw/` (gitignored, cached, one request per second), runs forward
kinematics, and writes 15 markers per frame: head, neck, shoulders, elbows,
wrists, pelvis, hips, knees and ankles. Clips are resampled to 30 fps,
capped at 10 seconds and stored in millimetres. Each clip is normalized so the
figure starts at the origin facing +x (x forward, y up, z to the figure's
left), with the floor at y = 0. The build fails a clip if any bone changes
length by more than 1%.

## Data credit and terms

Motion data comes from the
[CMU Graphics Lab Motion Capture Database](http://mocap.cs.cmu.edu/). The data
used in this project was obtained from mocap.cs.cmu.edu. The database was
created with funding from NSF EIA-0196217.

The clips in `data/clips/`, the trial descriptions in
`pipeline/cmu_index.json` and the demo animation in `docs/demo.webp` are derived
from that database and remain subject to CMU's terms: free to use, including in
commercial products, but not to be resold directly, even in altered form. The
MIT license below covers this project's own code and documentation, not the CMU
data.

## Contributing

Clip feedback, bug reports and ideas are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md)
and the [code of conduct](CODE_OF_CONDUCT.md).

## Security

Please report vulnerabilities privately; see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
