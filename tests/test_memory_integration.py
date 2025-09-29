import os
import time
import uuid
from typing import Any, Callable, Dict, List

import pytest
import requests

from neuro_mvp.memory import MemoryClient


def _skip_if_service_unavailable(base_url: str) -> None:
    try:
        resp = requests.get(f"{base_url}/health", timeout=5)
        if resp.status_code != 200:
            pytest.skip(f"mem0-service healthcheck failed: {resp.status_code}")
    except requests.RequestException as exc:
        pytest.skip(f"mem0-service not reachable: {exc}")


@pytest.fixture(scope="module")
def mem0_qdrant_context() -> Dict[str, Any]:
    base_url = os.getenv("MEM0_BASE_URL", "http://127.0.0.1:4040").rstrip("/")
    _skip_if_service_unavailable(base_url)

    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    collection = os.getenv("QDRANT_COLLECTION", "memory_items")

    if not (qdrant_url and qdrant_api_key):
        pytest.skip("Qdrant configuration is missing")

    try:
        resp = requests.get(
            f"{qdrant_url}/collections/{collection}",
            headers={"api-key": qdrant_api_key},
            timeout=10,
        )
        if resp.status_code >= 400:
            pytest.skip(f"Qdrant reachable but returned {resp.status_code}")
    except requests.RequestException as exc:
        pytest.skip(f"Qdrant not reachable: {exc}")

    patcher = pytest.MonkeyPatch()
    raw_user = f"Integration User {uuid.uuid4()}"
    patcher.setenv("MEMORY_USER_ID", raw_user)

    client = MemoryClient()
    sanitized_user = client.user_id

    headers = {
        "api-key": qdrant_api_key,
        "Content-Type": "application/json",
    }

    def fetch_points(limit: int = 200) -> List[Dict[str, Any]]:
        body: Dict[str, Any] = {
            "with_payload": True,
            "with_vector": False,
            "limit": limit,
            "filter": {
                "must": [
                    {"key": "userId", "match": {"value": sanitized_user}}
                ]
            },
        }
        resp = requests.post(
            f"{qdrant_url}/collections/{collection}/points/scroll",
            headers=headers,
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("result", {}).get("points", [])

    def delete_user_points() -> None:
        body = {
            "filter": {
                "must": [
                    {"key": "userId", "match": {"value": sanitized_user}}
                ]
            }
        }
        try:
            requests.post(
                f"{qdrant_url}/collections/{collection}/points/delete",
                headers=headers,
                json=body,
                timeout=60,
            )
        except requests.RequestException:
            pass

    delete_user_points()

    context: Dict[str, Any] = {
        "client": client,
        "sanitized_user": sanitized_user,
        "fetch_points": fetch_points,
        "delete_user_points": delete_user_points,
    }

    try:
        yield context
    finally:
        delete_user_points()
        patcher.undo()


def _write_and_wait(
    client: MemoryClient,
    fetch_points: Callable[[], List[Dict[str, Any]]],
    label: str,
    value: str,
    attempts: int = 10,
    pause: float = 1.0,
) -> Dict[str, Any]:
    client.write(label, value)

    for _ in range(max(1, attempts)):
        time.sleep(pause)
        for point in fetch_points():
            payload = point.get("payload", {})
            if isinstance(payload, dict) and value in str(payload.get("data", "")):
                return point
    raise AssertionError("Memory entry was not persisted to Qdrant within the timeout window")


@pytest.mark.integration
def test_memory_write_persists_to_qdrant_and_applies_user(mem0_qdrant_context: Dict[str, Any]) -> None:
    ctx = mem0_qdrant_context
    ctx["delete_user_points"]()

    label = "facts"
    unique_value = f"enjoys integration testing {uuid.uuid4()}"

    point = _write_and_wait(ctx["client"], ctx["fetch_points"], label, unique_value)

    payload = point.get("payload", {})
    assert unique_value in payload.get("data", "")
    assert payload.get("userId") == ctx["sanitized_user"]


@pytest.mark.integration
def test_memory_search_returns_inserted_item(mem0_qdrant_context: Dict[str, Any]) -> None:
    ctx = mem0_qdrant_context
    ctx["delete_user_points"]()

    label = "profile"
    unique_value = f"bio data for integration test {uuid.uuid4()}"

    _write_and_wait(ctx["client"], ctx["fetch_points"], label, unique_value)

    time.sleep(1)
    results = ctx["client"].search(unique_value)

    assert any(unique_value in item.get("value", "") for item in results)
    assert any(item.get("label") == label for item in results)



