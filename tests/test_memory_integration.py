import os
import time
import uuid
from typing import Any, Dict

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
def mem0_context() -> Dict[str, Any]:
    base_url = os.getenv("MEM0_BASE_URL", "http://127.0.0.1:4040").rstrip("/")
    _skip_if_service_unavailable(base_url)

    patcher = pytest.MonkeyPatch()
    raw_user = f"integration-user-{uuid.uuid4().hex[:8]}"
    patcher.setenv("MEMORY_USER_ID", raw_user)

    client = MemoryClient()
    sanitized_user = client.user_id

    context: Dict[str, Any] = {
        "client": client,
        "sanitized_user": sanitized_user,
    }

    try:
        yield context
    finally:
        # Clean up user data
        try:
            client.wipe_user(sanitized_user)
        except Exception:
            pass
        patcher.undo()


@pytest.mark.integration
def test_memory_write_and_search(mem0_context: Dict[str, Any]) -> None:
    ctx = mem0_context
    client = ctx["client"]

    label = "facts"
    unique_value = f"enjoys integration testing {uuid.uuid4()}"

    # Write to memory
    client.write(label, unique_value)

    # Wait for persistence
    time.sleep(1)

    # Search should find the item
    results = client.search(unique_value)

    assert any(unique_value in item.get("value", "") for item in results)


@pytest.mark.integration
def test_memory_search_returns_inserted_item(mem0_context: Dict[str, Any]) -> None:
    ctx = mem0_context
    client = ctx["client"]

    label = "profile"
    unique_value = f"bio data for integration test {uuid.uuid4()}"

    client.write(label, unique_value)

    time.sleep(1)
    results = client.search(unique_value)

    assert any(unique_value in item.get("value", "") for item in results)
    assert any(item.get("label") == label for item in results)
