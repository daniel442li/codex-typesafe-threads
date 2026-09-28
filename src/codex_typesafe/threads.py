from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class CodexThread:
    thread_id: str
    path: Path
    cwd: str | None = None
    name: str | None = None
    created: str | None = None
    source: str | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)

    def to_state(self, max_chars: int = 24000) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        budget = max_chars
        for turn in self.turns:
            for role, key in (("user", "user"), ("assistant", "assistant")):
                text = (turn.get(key) or "").strip()
                if not text:
                    continue
                if len(text) > 4000:
                    text = text[:4000] + "…"
                entry = {"role": role, "text": text, "turn_id": str(turn.get("turn_id") or "")}
                encoded = json.dumps(entry)
                if len(encoded) > budget:
                    break
                messages.append(entry)
                budget -= len(encoded)
            else:
                continue
            break
        return {
            "thread_id": self.thread_id,
            "name": self.name,
            "cwd": self.cwd,
            "created": self.created,
            "source": self.source,
            "messages": messages,
        }

    def raw_text(self, max_chars: int = 24000) -> str:
        chunks: list[str] = []
        for turn in self.turns:
            turn_id = turn.get("turn_id") or ""
            user = (turn.get("user") or "").strip()
            assistant = (turn.get("assistant") or "").strip()
            if user:
                chunks.append(f"user ({turn_id}):\n{user}")
            if assistant:
                chunks.append(f"assistant ({turn_id}):\n{assistant}")
        text = "\n\n".join(chunks)
        if len(text) > max_chars:
            return text[: max_chars - 1] + "…"
        return text


def default_codex_home() -> Path:
    return Path.home() / ".codex"


def iter_rollout_files(codex_home: Path) -> Iterable[Path]:
    sessions = codex_home / "sessions"
    if not sessions.is_dir():
        return
    yield from sorted(sessions.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("input_text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def load_thread(path: Path) -> CodexThread | None:
    thread_id = ""
    cwd = None
    name = None
    created = None
    source = None
    by_turn: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    try:
        with path.open() as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                kind = obj.get("type")

                if kind == "session_meta":
                    thread_id = str(payload.get("id") or payload.get("session_id") or "")
                    cwd = payload.get("cwd")
                    name = payload.get("name")
                    created = obj.get("timestamp") or payload.get("timestamp")
                    source = payload.get("source") or payload.get("originator")
                    continue

                if kind != "event_msg":
                    continue
                if payload.get("type") != "item_completed":
                    continue
                turn_id = str(payload.get("turn_id") or "")
                item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
                item_type = item.get("type")
                if not turn_id:
                    continue
                if turn_id not in by_turn:
                    by_turn[turn_id] = {"turn_id": turn_id}
                    order.append(turn_id)
                if item_type == "UserMessage":
                    by_turn[turn_id]["user"] = _text_from_content(item.get("content"))
                elif item_type == "AgentMessage":
                    text = _text_from_content(item.get("content"))
                    if item.get("phase") == "final_answer" or not by_turn[turn_id].get("assistant"):
                        by_turn[turn_id]["assistant"] = text
    except OSError:
        return None

    if not thread_id:
        stem = path.stem
        thread_id = stem.rsplit("-", 5)[-1] if "-" in stem else stem
    turns = [by_turn[tid] for tid in order if by_turn[tid].get("user") or by_turn[tid].get("assistant")]
    if not turns:
        return None
    return CodexThread(
        thread_id=thread_id,
        path=path,
        cwd=cwd,
        name=name,
        created=str(created) if created else None,
        source=str(source) if source else None,
        turns=turns,
    )


def load_threads(
    *,
    codex_home: Path | None = None,
    limit: int | None = None,
    thread_id: str | None = None,
    cwd_contains: str | None = None,
) -> list[CodexThread]:
    home = codex_home or default_codex_home()
    found: list[CodexThread] = []
    seen: set[str] = set()
    for path in iter_rollout_files(home):
        thread = load_thread(path)
        if thread is None:
            continue
        if thread.thread_id in seen:
            continue
        if thread_id and thread.thread_id != thread_id:
            continue
        if cwd_contains and cwd_contains not in (thread.cwd or ""):
            continue
        seen.add(thread.thread_id)
        found.append(thread)
        if limit is not None and len(found) >= limit:
            break
    return found
