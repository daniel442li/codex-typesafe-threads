from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

import tiktoken
from typesafe_sdk import TypeSafeClient

from .questions import FEATURE_NOUL_ID, feature_noul_questions
from .threads import CodexThread


MAX_INPUT_TOKENS = 3000
REQUEST_OVERHEAD_TOKENS = 500


@lru_cache(maxsize=1)
def _encoding():
    # jev-latest does not publish a tokenizer; cl100k_base is a local estimate.
    return tiktoken.get_encoding("cl100k_base")


def prepare_request(thread: CodexThread, feature: str) -> tuple[str, dict]:
    questions = feature_noul_questions(feature)
    encoding = _encoding()
    instructions = questions[FEATURE_NOUL_ID]["instructions"]
    budget = MAX_INPUT_TOKENS - REQUEST_OVERHEAD_TOKENS - len(encoding.encode(instructions))
    if budget < 1:
        raise ValueError("Feature query is too long for the 3,000-token input budget")

    raw = thread.raw_text()
    tokens = encoding.encode(raw)
    if len(tokens) > budget:
        kept = budget - 1
        raw = encoding.decode(tokens[:kept]) + "…"
        while len(encoding.encode(raw)) > budget:
            kept -= 1
            raw = encoding.decode(tokens[:kept]) + "…"
    return raw, questions


def serialize_answers(response) -> dict:
    answers = {}
    raw = getattr(response, "answers", None) or {}
    if hasattr(raw, "items"):
        items = raw.items()
    else:
        items = []
    for key, value in items:
        payload = {"type": getattr(value, "type", None) or type(value).__name__}
        for attr in ("choice", "score", "noul", "confidence", "probabilities", "legend"):
            if hasattr(value, attr):
                field = getattr(value, attr)
                if field is not None:
                    payload[attr] = field
        answers[str(key)] = payload
    usage = getattr(response, "usage", None)
    return {
        "model": getattr(response, "model", None),
        "answers": answers,
        "usage": None
        if usage is None
        else {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
    }


def noul_from_record(record: dict) -> float | None:
    value = ((record.get("typesafe") or {}).get("answers") or {}).get(FEATURE_NOUL_ID) or {}
    noul = value.get("noul")
    try:
        return float(noul)
    except (TypeError, ValueError):
        return None


def evaluate_thread(client: TypeSafeClient, thread: CodexThread, feature: str) -> dict:
    raw, questions = prepare_request(thread, feature)
    response = client.system_one(state=raw, questions=questions, model="jev-latest")
    return {
        "thread_id": thread.thread_id,
        "cwd": thread.cwd,
        "name": thread.name,
        "path": str(thread.path),
        "feature": feature,
        "typesafe": serialize_answers(response),
    }


def _evaluate_with_own_client(thread: CodexThread, feature: str) -> dict:
    with TypeSafeClient() as client:
        return evaluate_thread(client, thread, feature)


def evaluate_threads_parallel(
    threads: list[CodexThread],
    feature: str,
    *,
    max_workers: int = 100,
    on_progress=None,
) -> list[dict]:
    if not threads:
        return []
    workers = max(1, min(max_workers, len(threads)))
    records: list[dict] = []
    done = 0
    total = len(threads)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_evaluate_with_own_client, thread, feature) for thread in threads]
        for future in as_completed(futures):
            done += 1
            if on_progress is not None:
                on_progress(done, total)
            try:
                records.append(future.result())
            except Exception as exc:
                records.append({"thread_id": "error", "error": str(exc), "typesafe": {"answers": {}}})
    return records


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")
