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


def make_memory(user_id: str | None = None, companion_id: str | None = None) -> MemoryClient:
    """Create a MemoryClient with optional user and companion isolation.

    When companion_id is provided, builds a composite user_id: {user_id}_{companion_id}
    This matches the web session behavior for user-companion memory isolation.
    """
    # Build composite user_id if companion_id is provided
    effective_user_id = user_id
    if companion_id and user_id:
        effective_user_id = f"{user_id}_{companion_id}"
    elif companion_id:
        # Use companion_id with default user if no user_id specified
        base_user = os.getenv("MEMORY_USER_ID", "default")
        effective_user_id = f"{base_user}_{companion_id}"

    if effective_user_id:
        os.environ["MEMORY_USER_ID"] = effective_user_id

    provider = os.getenv("MEMORY_PROVIDER", "mem0").strip().lower()
    return MemoryClient(provider=provider, user_id=effective_user_id)


def _get_effective_user_display(args) -> str:
    """Get display string for effective user_id (with companion if set)."""
    base = args.user_id or os.getenv("MEMORY_USER_ID", "default")
    if getattr(args, "companion_id", None):
        return f"{base}_{args.companion_id}"
    return base


def cmd_export(args) -> int:
    mem = make_memory(args.user_id, getattr(args, "companion_id", None))
    data = mem.export_json(mem.user_id)
    if args.out:
        Path(args.out).write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"[memory] Exported to {args.out}")
    else:
        print(json.dumps(data, indent=2))
    return 0


def cmd_forget_last_session(args) -> int:
    mem = make_memory(args.user_id, getattr(args, "companion_id", None))
    n = mem.forget_last_session(mem.user_id)
    print(f"[memory] Deleted {n} episodic items from last session for user {_get_effective_user_display(args)}")
    return 0


def cmd_forget_by_label(args) -> int:
    mem = make_memory(args.user_id, getattr(args, "companion_id", None))
    n = mem.forget_by_label(args.label, mem.user_id)
    print(f"[memory] Deleted {n} items with label '{args.label}' for user {_get_effective_user_display(args)}")
    return 0


def cmd_wipe_user(args) -> int:
    mem = make_memory(args.user_id, getattr(args, "companion_id", None))
    mem.wipe_user(mem.user_id)
    print(f"[memory] Wiped user {_get_effective_user_display(args)}")
    return 0


def cmd_index_files(args) -> int:
    mem = make_memory(args.user_id, getattr(args, "companion_id", None))
    paths = args.paths if args.paths else None
    n = mem.index_files(paths)
    print(f"[memory] Indexed {n} chunks from files")
    return 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add common arguments (--user-id, --companion-id) to a subparser."""
    parser.add_argument("--user-id", type=str, default=None, help="User ID")
    parser.add_argument("--companion-id", "-c", type=str, default=None,
                        help="Companion/character ID for memory isolation (e.g., 'nova', 'sage')")


def main():
    ap = argparse.ArgumentParser(description="Memory maintenance CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_exp = sub.add_parser("export", help="Export memory as JSON")
    _add_common_args(p_exp)
    p_exp.add_argument("--out", type=str, default=None)
    p_exp.set_defaults(func=cmd_export)

    p_fls = sub.add_parser("forget-last-session", help="Forget last session for a user")
    _add_common_args(p_fls)
    p_fls.set_defaults(func=cmd_forget_last_session)

    p_fbl = sub.add_parser("forget-by-label", help="Forget by tag/label for a user")
    _add_common_args(p_fbl)
    p_fbl.add_argument("--label", type=str, required=True)
    p_fbl.set_defaults(func=cmd_forget_by_label)

    p_wu = sub.add_parser("wipe-user", help="Wipe all memory for a user")
    _add_common_args(p_wu)
    p_wu.set_defaults(func=cmd_wipe_user)

    p_idx = sub.add_parser("index-files", help="Index local project files into general memory")
    p_idx.add_argument("paths", nargs="*", help="Files or directories to index (default: agent.md, config.yaml, src, tools)")
    _add_common_args(p_idx)
    p_idx.set_defaults(func=cmd_index_files)

    # Set persona (global)
    def cmd_set_persona(args) -> int:
        mem = make_memory(args.user_id, getattr(args, "companion_id", None))
        mem.ensure_persona(args.text)
        print("[memory] Persona updated.")
        return 0

    p_sp = sub.add_parser("set-persona", help="Set or replace the global persona text")
    p_sp.add_argument("--text", type=str, required=True)
    _add_common_args(p_sp)
    p_sp.set_defaults(func=cmd_set_persona)

    # Set user label -> selects/creates the user
    def cmd_set_user_label(args) -> int:
        mem = make_memory(args.user_id, getattr(args, "companion_id", None))
        uid = mem.ensure_user(args.text)
        print(f"[memory] User label set. Active user: {uid}")
        return 0

    p_sul = sub.add_parser("set-user-label", help="Set user label (e.g., 'User is Noah.') and select user")
    p_sul.add_argument("--text", type=str, required=True)
    _add_common_args(p_sul)
    p_sul.set_defaults(func=cmd_set_user_label)

    # Add memory item for current user (semantic by default)
    def cmd_add(args) -> int:
        mem = make_memory(args.user_id, getattr(args, "companion_id", None))
        if args.user_label:
            mem.ensure_user(args.user_label)
        iid = mem.add_label_value(args.label, args.value, replace=bool(args.replace))
        print(f"[memory] Added item {iid} label={args.label}")
        return 0

    p_add = sub.add_parser("add", help="Add a memory item for the current user")
    p_add.add_argument("--label", type=str, required=True, help="persona|user|profile|preferences|facts|goals|general")
    p_add.add_argument("--value", type=str, required=True)
    p_add.add_argument("--replace", action="store_true")
    _add_common_args(p_add)
    p_add.add_argument("--user-label", type=str, default=None, help="Optionally set/select user (e.g., 'User is Noah.')")
    p_add.set_defaults(func=cmd_add)

    # Consolidate/decay
    def cmd_consolidate(args) -> int:
        mem = make_memory(args.user_id, getattr(args, "companion_id", None))
        res = mem.consolidate()
        print(f"[memory] Consolidation: merged={res.get('merged',0)} decayed={res.get('decayed',0)}")
        return 0

    p_con = sub.add_parser("consolidate", help="Merge duplicates and decay old facts")
    _add_common_args(p_con)
    p_con.set_defaults(func=cmd_consolidate)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
