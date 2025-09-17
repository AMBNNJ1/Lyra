from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.neuro_mvp.memory import MemoryClient
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None  # type: ignore


def _db_path_for_provider(provider: str) -> str:
    prov = (provider or "qdrant").strip().lower()
    if prov == "qdrant":
        return os.getenv("QDRANT_COLLECTION", "memory_items")
    return os.getenv("QDRANT_COLLECTION", "memory_items")


def main() -> int:
    ap = argparse.ArgumentParser(description="Initialize memory database (provider-aware)")
    ap.add_argument("--user-id", type=str, default=None, help="User id to initialize (default from env)")
    ap.add_argument("--persona", type=str, default=None, help="Persona text to store globally")
    ap.add_argument("--user-label", type=str, default=None, help="User label (e.g. 'User is Alex.')")
    ap.add_argument("--index", action="store_true", help="Index default project files into general memory")
    args = ap.parse_args()

    # Load .env so MEMORY_PROVIDER and related vars are available outside run_agent
    if load_dotenv:
        try:
            load_dotenv(dotenv_path=str(ROOT / ".env"))
        except Exception:
            try:
                load_dotenv()
            except Exception:
                pass

    provider = os.getenv("MEMORY_PROVIDER", "qdrant").strip().lower()
    mem = MemoryClient(provider=provider)
    # Load defaults from config.yaml if present
    try:
        cfg_file = Path("config.yaml")
        cfg_yaml = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    except Exception:
        cfg_yaml = {}
    # Resolve persona/user_label from args, env, or config.yaml (provider section first, then local fallback)
    persona = args.persona or os.getenv("MEMORY_PERSONA")
    if not persona:
        persona = (
            (cfg_yaml.get("memory", {}).get(provider, {}) or {}).get("persona")
            or cfg_yaml.get("memory", {}).get("persona")
        )
    user_label = args.user_label or os.getenv("MEMORY_USER_LABEL")
    if not user_label:
        user_label = (
            (cfg_yaml.get("memory", {}).get(provider, {}) or {}).get("user_label")
            or cfg_yaml.get("memory", {}).get("user_label")
        )
    # Ensure persona + user
    mem.ensure_agent(persona=str(persona or ""), user_label=str(user_label or "User is default."))
    # Optionally index files
    if args.index:
        try:
            n = mem.index_files()
        except Exception:
            n = 0
        print(f"[init] Indexed {n} chunks into general memory")
    db_path = Path(_db_path_for_provider(provider)).resolve()
    print(f"[init] Database ready: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
