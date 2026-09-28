# Codex Threads

Codex Threads is a macOS menu-bar app that searches your recent Codex threads with TypeSafe and opens the closest match in Codex.

## Setup

You need macOS, Python 3.10 or newer, Codex with local threads in `~/.codex/sessions`, and a TypeSafe API key.

1. Clone the repository and install its Python dependencies:

   ```sh
   git clone https://github.com/daniel442li/codex-typesafe-threads.git
   cd codex-typesafe-threads
   python3 -m venv .venv
   .venv/bin/python -m pip install -e .
   ```

2. Create your local configuration:

   ```sh
   cp .env.example .env
   ```

   Set `TYPESAFE_API_KEY` in `.env`. The file is ignored by Git. The app reads Codex threads from `~/.codex/sessions`.

3. Launch the app:

   ```sh
   open "app/Codex Threads.app"
   ```

The search window opens at launch. Later, use the **Codex** menu-bar item, press **Fn**, or press **Control-Shift-Space**. Type a feature or topic and press **Return** to scan the 20 most recent threads and open the closest match. If macOS prompts for keyboard monitoring permission, grant it to use the global shortcuts; the menu-bar item remains available.

## Start at login (optional)

The included LaunchAgent has paths from the original development machine. Generate a copy with paths for your checkout and home directory:

```sh
python3 - <<'PY'
import plistlib
from pathlib import Path

repo = Path.cwd().resolve()
source = repo / "app/com.daniel-li.codex-typesafe-threads.plist"
agent = Path.home() / "Library/LaunchAgents" / source.name
logs = Path.home() / "Library/Logs"
agent.parent.mkdir(parents=True, exist_ok=True)
logs.mkdir(parents=True, exist_ok=True)
config = plistlib.loads(source.read_bytes())
config["ProgramArguments"] = [str(repo / "app/Codex Threads.app/Contents/MacOS/Codex Threads")]
config["WorkingDirectory"] = str(repo)
config["StandardOutPath"] = str(logs / "CodexThreads.log")
config["StandardErrorPath"] = str(logs / "CodexThreads.error.log")
agent.write_bytes(plistlib.dumps(config))
print(agent)
PY
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.daniel-li.codex-typesafe-threads.plist"
```

The agent starts the app at login and restarts it if it exits. Logs go to `~/Library/Logs/CodexThreads.log` and `~/Library/Logs/CodexThreads.error.log`. To stop and disable it, run:

```sh
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.daniel-li.codex-typesafe-threads.plist"
rm "$HOME/Library/LaunchAgents/com.daniel-li.codex-typesafe-threads.plist"
```

## Command-line use

Run a scan without the menu-bar app:

```sh
.venv/bin/codex-typesafe --feature "your search topic" --dry-run
.venv/bin/codex-typesafe --feature "your search topic"
```

The second command sends requests to TypeSafe and writes results to `out/results.jsonl`. Use `--codex-home PATH` if your Codex data is somewhere other than `~/.codex`.

## How searches work

Searches consider the 20 most recent threads. Each request sends the thread text once, as the API state, and trims long text to a 3,000-token estimated input budget. The budget includes the query instructions and reserves 500 tokens for request overhead. TypeSafe's `jev-latest` tokenizer is not published, so the local count uses `cl100k_base` as an estimate; the API's reported `usage.input_tokens` is the authoritative count.

Verified 2026-09-27 for this Codex task: `python -m unittest discover -s tests -v` passed, and all 20 recent prepared requests were within the local budget. Source: `src/codex_typesafe/feed.py` and `src/codex_typesafe/questions.py`.
