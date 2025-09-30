import json

import pytest

import neuro_mvp.memory as memory_module
from neuro_mvp.memory import MemoryClient


class DummyMem0Client:
    def __init__(self):
        self.api_key = None
        self.add_calls = []
        self.search_requests = []
        self.search_results = []

    def add(self, messages, user_id=None, metadata=None):
        self.add_calls.append({
            "messages": messages,
            "user_id": user_id,
            "metadata": metadata,
        })

    def search(self, query, filters=None, user_id=None, limit=None, version=None):
        self.search_requests.append({
            "query": query,
            "filters": filters,
            "user_id": user_id,
            "limit": limit,
            "version": version,
        })
        return list(self.search_results)


@pytest.fixture
def memory_client(monkeypatch):
    dummy = DummyMem0Client()
    monkeypatch.setenv('MEM0_API_KEY', 'test-key')
    monkeypatch.setattr(memory_module, 'Mem0Client', lambda api_key: dummy)
    client = MemoryClient()
    return client, dummy


def test_sanitize_user_generates_slug(memory_client):
    client, _ = memory_client
    assert client._sanitize_user('Jane Doe!') == 'jane-doe'
    assert client._sanitize_user('') == 'default'


def test_find_items_filters_labels(memory_client, monkeypatch):
    client, _ = memory_client
    sample_items = [
        {'label': 'profile', 'value': 'Loves coffee'},
        {'label': 'facts', 'value': 'Lives in Berlin'},
    ]
    monkeypatch.setattr(client, 'search', lambda query: sample_items)

    results = client.find_items('coffee', labels=['facts'])

    assert results == [{'label': 'facts', 'value': 'Lives in Berlin'}]


def test_retrieve_context_includes_persona_and_user(memory_client, monkeypatch):
    client, _ = memory_client
    client.persona_text = 'Nova is upbeat.'

    monkeypatch.setattr(
        client,
        'search',
        lambda query: [
            {'label': 'persona', 'value': 'Persona detail'},
            {'label': 'profile', 'value': 'User likes hiking'},
            {'label': 'memory', 'value': 'General fact'},
        ],
    )

    context = client.retrieve_context('anything')

    assert any(block['label'] == 'persona' for block in context['persona'])
    assert any(block['label'] in {'user', 'profile', 'preferences'} for block in context['user'])
    assert any(block['label'] == 'memory' for block in context['long_term'])


def test_execute_tool_routes_to_write(memory_client, monkeypatch):
    client, _ = memory_client
    calls = []
    monkeypatch.setattr(client, 'write', lambda label, value: calls.append((label, value)))

    success, msg = client.execute_tool('memory_append', {'label': 'facts', 'value': 'Enjoys chess'})

    assert success is True
    assert msg == 'ok'
    assert calls == [('facts', 'Enjoys chess')]


def test_execute_tool_memory_search_returns_json(memory_client, monkeypatch):
    client, _ = memory_client
    monkeypatch.setattr(client, 'find_items', lambda query, labels=None, limit=12: [
        {'label': 'facts', 'value': 'Loves pizza'}
    ])

    success, payload = client.execute_tool('memory_search', {'query': 'pizza'})

    assert success is True
    data = json.loads(payload)
    assert data == [{'label': 'facts', 'text': 'Loves pizza'}]


def test_execute_tool_returns_false_for_unknown(memory_client):
    client, _ = memory_client
    success, message = client.execute_tool('unknown_tool', {})
    assert success is False
    assert message == 'unsupported'
