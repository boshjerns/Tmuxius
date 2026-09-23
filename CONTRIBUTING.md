# Contributing

Keep the terminal workflow small: readable context, predictable controls, and
as much room for the conversations as possible. Preserve the distinction
between panel identity and keyboard focus. Changes should work with keyboard
navigation, a narrow terminal, and `--no-color`.

Use Python 3.10+ and tmux. Runtime dependencies are all in the standard library.
Run the checks from the repository root:

```sh
./tmuxius --self-test
python3 -m unittest discover -s tests -v
python3 scripts/check-publication.py
```

The interactive test launches only disposable tmux servers with fictional
content. It never attaches to an existing user's server. To render fictional
demo images for local UI checks, install the optional development dependencies
in a venv:

```sh
python3 -m venv .venv
.venv/bin/pip install -r scripts/screenshots-requirements.txt
.venv/bin/python scripts/screenshots.py
```

The renderer uses Liberation Mono; install `fonts-liberation` on Debian/Ubuntu.
It writes to the ignored `local/demo-screenshots/` directory and does not replace
the real README screenshot. Review generated images as well as the source
fixture. Real screenshots require the owner's explicit direction, visual review,
opaque privacy redactions, and metadata removal; never commit the original.

Install [Gitleaks](https://github.com/gitleaks/gitleaks) and enable the local
publication guard before pushing:

```sh
git config core.hooksPath .githooks
gitleaks dir --redact --no-banner .
gitleaks git --redact --no-banner .
```

New files need an explicit entry in `public-files.txt`. This is a review aid,
not a substitute for reading the diff. Keep fixtures fictional, preserve
copyright notices, use a public/noreply commit email, and follow
[SECURITY.md](SECURITY.md). Changes to sending need regression cases for pending
drafts, busy agents, multiline paste, slash commands, and ambiguous results.

Open a pull request describing what happens before and after your change,
which checks passed, and the terminal/agent versions used. No personal host
details or live terminal captures are needed.
