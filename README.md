# Codex Threads

`app/Codex Threads.app` launches the native Codex thread finder as a menu-bar app.

The installed LaunchAgent, `com.daniel-li.codex-typesafe-threads`, starts it at login and restarts it if it exits. Its logs are written to `~/Library/Logs/CodexThreads.log` and `~/Library/Logs/CodexThreads.error.log`.

Searches consider the 20 most recent threads. Each request sends the thread text once, as the API state, and trims long text to a 3,000-token estimated input budget. The budget includes the query instructions and reserves 500 tokens for request overhead. TypeSafe's `jev-latest` tokenizer is not published, so the local count uses `cl100k_base` as an estimate; the API's reported `usage.input_tokens` is the authoritative count.

Verified 2026-09-27 for this Codex task: `python -m unittest discover -s tests -v` passed, and all 20 recent prepared requests were within the local budget. Source: `src/codex_typesafe/feed.py` and `src/codex_typesafe/questions.py`.
