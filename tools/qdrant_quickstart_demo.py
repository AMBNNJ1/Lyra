from __future__ import annotations

import os


def main() -> int:
    try:
        from qdrant_client import QdrantClient  # type: ignore
        from qdrant_client.models import Distance, VectorParams  # type: ignore
    except Exception as e:
        print(f"qdrant-client not installed: {e}")
        print("Install with: pip install qdrant-client")
        return 1

    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    api_key = os.getenv("QDRANT_API_KEY")
    c = QdrantClient(url=url, api_key=api_key)

    # Step 1: create collection
    c.recreate_collection(
        collection_name="star_charts",
        vectors_config=VectorParams(size=4, distance=Distance.DOT),
    )

    # Step 2: load data
    points = [
        {"id": 1, "vector": [0.05, 0.61, 0.76, 0.74], "payload": {"colony": "Mars"}},
        {"id": 2, "vector": [0.19, 0.81, 0.75, 0.11], "payload": {"colony": "Jupiter"}},
        {"id": 3, "vector": [0.36, 0.55, 0.47, 0.94], "payload": {"colony": "Venus"}},
        {"id": 4, "vector": [0.18, 0.01, 0.85, 0.80], "payload": {"colony": "Moon"}},
        {"id": 5, "vector": [0.24, 0.18, 0.22, 0.44], "payload": {"colony": "Pluto"}},
    ]
    c.upsert(collection_name="star_charts", points=points)

    # Step 3: search
    hits = c.search(collection_name="star_charts", query_vector=[0.2, 0.1, 0.9, 0.7], limit=3, with_payload=True)
    print("Top-3 nearest:")
    for h in hits:
        print({"id": h.id, "score": h.score, "payload": h.payload})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

