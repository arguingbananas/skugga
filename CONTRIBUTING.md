# Contributing to Skugga

Thanks for your interest! Skugga is early: the game mechanics are still being
designed, so the most useful contributions right now are feedback on clips and
ideas for how a round should play.

By taking part you agree to follow the [code of conduct](CODE_OF_CONDUCT.md).

## Ways to help

- **Clip feedback.** Open the viewer, watch clips, and tell us which ones are
  ambiguous, broken or great. Use the "Clip feedback" issue template.
- **Bug reports.** Use the "Bug report" issue template.
- **Ideas.** Open an issue describing the idea and why it would be fun.
- **Code.** For anything bigger than a small fix, open an issue first so we can
  agree on the approach.

Security problems: please don't open a public issue; see [SECURITY.md](SECURITY.md).

## Development setup

You need Python 3.11+ with pyflakes (`apt install python3-pyflakes`), Node 22.13+
and Chromium (or Chrome).

```sh
npm install          # dev tools only (puppeteer-core)
npm run serve        # viewer at http://127.0.0.1:8000/web/
npm run check        # syntax-check the JavaScript
npm run lint         # ESLint and pyflakes
npm run smoke        # headless browser smoke test
```

The [README](README.md) covers the data pipeline and the demo renderer.

## Pull requests

- `main` only accepts changes through pull requests, and CI (syntax check,
  Python compile check, lint, smoke test) and CodeQL must pass. PRs are merged by
  rebasing, so keep commits tidy and meaningful.
- Keep each PR to one change, and describe what it does and how you tested it.
- The viewer and game are plain JavaScript modules with no build step; please
  keep it that way unless we've agreed otherwise in an issue.
- The pipeline uses only the Python standard library.

## Data

Clips come from the
[CMU Graphics Lab Motion Capture Database](http://mocap.cs.cmu.edu/) and stay
under CMU's terms (see the README). To add or change clips, edit
`pipeline/clips.toml` and rebuild with `python3 pipeline/build.py`; don't
hand-edit files in `data/clips/`. Don't commit raw mocap files.

## Privacy

This is a public repository. Don't commit secrets or anything that identifies
people or machines: real names, emails, usernames, hostnames, local paths or
network addresses. Consider committing with your
[GitHub noreply email](https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-email-preferences/setting-your-commit-email-address).

## AI-assisted contributions

Much of Skugga is written with an AI coding assistant (see the README). AI help
is welcome in contributions too: say so in your PR, and make sure you
understand and have tested what you submit.
