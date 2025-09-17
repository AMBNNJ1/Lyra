import os
import sys

def main() -> int:
    try:
        from qdrant_client import QdrantClient  # type: ignore
    except Exception as e:
        print(f"qdrant-client not installed: {e}")
        print("Install with: pip install qdrant-client")
        return 1
    # Try loading .env if present
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass
    url = os.getenv("QDRANT_URL") or (len(sys.argv) > 1 and sys.argv[1]) or "http://localhost:6333"
    api_key = os.getenv("QDRANT_API_KEY") or (len(sys.argv) > 2 and sys.argv[2]) or None
    c = QdrantClient(url=url, api_key=api_key)
    cols = c.get_collections()
    print(cols)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

