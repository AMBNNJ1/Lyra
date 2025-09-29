from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.neuro_mvp.memory import MemoryClient


def make_memory(user_id: str | None = None) -> MemoryClient:
    # MEMORY_USER_ID controls default user; provider set via MEMORY_PROVIDER
    if user_id:
        os.environ["MEMORY_USER_ID"] = user_id
    provider = os.getenv("MEMORY_PROVIDER", "qdrant").strip().lower()
    return MemoryClient(provider=provider)


def cmd_export(args) -> int:
    mem = make_memory(args.user_id)
    data = mem.export_json(args.user_id)
    if args.out:
        Path(args.out).write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"[memory] Exported to {args.out}")
    else:
        print(json.dumps(data, indent=2))
    return 0


def cmd_forget_last_session(args) -> int:
    mem = make_memory(args.user_id)
    n = mem.forget_last_session(args.user_id)
    print(f"[memory] Deleted {n} episodic items from last session for user {args.user_id or os.getenv('MEMORY_USER_ID','default')}")
    return 0


def cmd_forget_by_label(args) -> int:
    mem = make_memory(args.user_id)
    n = mem.forget_by_label(args.label, args.user_id)
    print(f"[memory] Deleted {n} items with label '{args.label}' for user {args.user_id or os.getenv('MEMORY_USER_ID','default')}")
    return 0


def cmd_wipe_user(args) -> int:
    mem = make_memory(args.user_id)
    mem.wipe_user(args.user_id)
    print(f"[memory] Wiped user {args.user_id or os.getenv('MEMORY_USER_ID','default')}")
    return 0


def cmd_index_files(args) -> int:
    mem = make_memory(args.user_id)
    paths = args.paths if args.paths else None
    n = mem.index_files(paths)
    print(f"[memory] Indexed {n} chunks from files")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Memory maintenance CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_exp = sub.add_parser("export", help="Export memory as JSON")
    p_exp.add_argument("--user-id", type=str, default=None)
    p_exp.add_argument("--out", type=str, default=None)
    p_exp.set_defaults(func=cmd_export)

    p_fls = sub.add_parser("forget-last-session", help="Forget last session for a user")
    p_fls.add_argument("--user-id", type=str, default=None)
    p_fls.set_defaults(func=cmd_forget_last_session)

    p_fbl = sub.add_parser("forget-by-label", help="Forget by tag/label for a user")
    p_fbl.add_argument("--user-id", type=str, default=None)
    p_fbl.add_argument("--label", type=str, required=True)
    p_fbl.set_defaults(func=cmd_forget_by_label)

    p_wu = sub.add_parser("wipe-user", help="Wipe all memory for a user")
    p_wu.add_argument("--user-id", type=str, default=None)
    p_wu.set_defaults(func=cmd_wipe_user)

    p_idx = sub.add_parser("index-files", help="Index local project files into general memory")
    p_idx.add_argument("paths", nargs="*", help="Files or directories to index (default: agent.md, config.yaml, src, tools)")
    p_idx.add_argument("--user-id", type=str, default=None)
    p_idx.set_defaults(func=cmd_index_files)

    # Set persona (global)
    def cmd_set_persona(args) -> int:
        mem = make_memory(args.user_id)
        mem.ensure_persona(args.text)
        print("[memory] Persona updated.")
        return 0

    p_sp = sub.add_parser("set-persona", help="Set or replace the global persona text")
    p_sp.add_argument("--text", type=str, required=True)
    p_sp.add_argument("--user-id", type=str, default=None)
    p_sp.set_defaults(func=cmd_set_persona)

    # Set user label -> selects/creates the user
    def cmd_set_user_label(args) -> int:
        mem = make_memory(args.user_id)
        uid = mem.ensure_user(args.text)
        print(f"[memory] User label set. Active user: {uid}")
        return 0

    p_sul = sub.add_parser("set-user-label", help="Set user label (e.g., 'User is Noah.') and select user")
    p_sul.add_argument("--text", type=str, required=True)
    p_sul.add_argument("--user-id", type=str, default=None)
    p_sul.set_defaults(func=cmd_set_user_label)

    # Add memory item for current user (semantic by default)
    def cmd_add(args) -> int:
        mem = make_memory(args.user_id)
        if args.user_label:
            mem.ensure_user(args.user_label)
        iid = mem.add_label_value(args.label, args.value, replace=bool(args.replace))
        print(f"[memory] Added item {iid} label={args.label}")
        return 0

    p_add = sub.add_parser("add", help="Add a memory item for the current user")
    p_add.add_argument("--label", type=str, required=True, help="persona|user|profile|preferences|facts|goals|general")
    p_add.add_argument("--value", type=str, required=True)
    p_add.add_argument("--replace", action="store_true")
    p_add.add_argument("--user-id", type=str, default=None)
    p_add.add_argument("--user-label", type=str, default=None, help="Optionally set/select user (e.g., 'User is Noah.')")
    p_add.set_defaults(func=cmd_add)

    # Consolidate/decay
    def cmd_consolidate(args) -> int:
        mem = make_memory(args.user_id)
        res = mem.consolidate()
        print(f"[memory] Consolidation: merged={res.get('merged',0)} decayed={res.get('decayed',0)}")
        return 0

    p_con = sub.add_parser("consolidate", help="Merge duplicates and decay old facts")
    p_con.add_argument("--user-id", type=str, default=None)
    p_con.set_defaults(func=cmd_consolidate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
