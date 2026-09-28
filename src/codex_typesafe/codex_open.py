from __future__ import annotations

import os
import subprocess
from urllib.parse import quote


def open_codex_prompt(query: str) -> None:
    prompt = query.strip()
    if not prompt:
        return
    url = f"codex://threads/new?prompt={quote(prompt)}"
    subprocess.run(["open", url], check=False)
    if os.environ.get("CODEX_TYPESAFE_ALSO_CLI") == "1":
        subprocess.Popen(["codex", prompt], start_new_session=True)
