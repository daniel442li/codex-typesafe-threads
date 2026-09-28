from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .feed import append_jsonl, evaluate_threads_parallel, noul_from_record, prepare_request
from .questions import FEATURE_NOUL_ID
from .threads import default_codex_home, load_threads


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def checkpoint_path(out_dir: Path) -> Path:
    return out_dir / "fed-thread-ids.json"


def load_checkpoint(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return set()
    if isinstance(data, list):
        return {str(item) for item in data}
    return set()


def save_checkpoint(path: Path, ids: set[str]) -> None:
    path.write_text(json.dumps(sorted(ids), indent=2) + "\n")


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Feed Codex threads into TypeSafe System One")
    parser.add_argument("--limit", type=int, default=20, help="Newest threads to consider")
    parser.add_argument("--thread-id", help="Feed a single Codex thread id")
    parser.add_argument("--cwd-contains", help="Only threads whose cwd contains this string")
    parser.add_argument("--codex-home", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("out/results.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Re-feed threads already in the checkpoint")
    parser.add_argument(
        "--feature",
        required=True,
        help="USER INPUT: the feature to look for in each thread",
    )
    args = parser.parse_args()

    load_dotenv(project_root() / ".env")
    if not args.dry_run and not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("TYPESAFE_API_KEY is not set. Put it in .env or the environment.")

    threads = load_threads(
        codex_home=args.codex_home or default_codex_home(),
        limit=None if args.thread_id else args.limit,
        thread_id=args.thread_id,
        cwd_contains=args.cwd_contains,
    )
    if not threads:
        raise SystemExit("No Codex threads found.")

    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpoint_path(out_path.parent)
    already = set() if args.force else load_checkpoint(checkpoint)
    feature_key = args.feature.strip()

    pending = [
        thread
        for thread in threads
        if f"{thread.thread_id}::{feature_key}" not in already
    ]
    if not pending:
        print("All selected threads were already fed for this feature.")
        return

    if args.dry_run:
        for thread in pending:
            raw, questions = prepare_request(thread, feature_key)
            print(
                json.dumps(
                    {
                        "thread_id": thread.thread_id,
                        "cwd": thread.cwd,
                        "raw_chars": len(raw),
                        "questions": questions,
                    }
                )
            )
        return

    records = evaluate_threads_parallel(pending, feature_key)
    fed = set(already)
    for record in records:
        append_jsonl(out_path, record)
        fed.add(f"{record['thread_id']}::{feature_key}")
        print(f"{record['thread_id']} {FEATURE_NOUL_ID}={noul_from_record(record)}")
    save_checkpoint(checkpoint, fed)
    print(f"Wrote {len(pending)} results to {out_path}")


if __name__ == "__main__":
    main()
