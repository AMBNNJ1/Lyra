import json

from neuro_mvp.memory import MemoryClient


def test_sanitize_user_generates_slug():
    client = MemoryClient()
    assert client._sanitize_user('Jane Doe!') == 'jane-doe'
    assert client._sanitize_user('') == 'default'


def test_find_items_filters_labels(monkeypatch):
    client = MemoryClient()
    sample_items = [
        {'label': 'profile', 'value': 'Loves coffee'},
        {'label': 'facts', 'value': 'Lives in Berlin'},
    ]
    monkeypatch.setattr(client, 'search', lambda query: sample_items)

    results = client.find_items('coffee', labels=['facts'])

    assert results == [{'label': 'facts', 'value': 'Lives in Berlin'}]


def test_retrieve_context_includes_persona_and_user(monkeypatch):
    client = MemoryClient()
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


def test_execute_tool_routes_to_write(monkeypatch):
    client = MemoryClient()
    calls = []
    monkeypatch.setattr(client, 'write', lambda label, value: calls.append((label, value)))

    success, msg = client.execute_tool('memory_append', {'label': 'facts', 'value': 'Enjoys chess'})

    assert success is True
    assert msg == 'ok'
    assert calls == [('facts', 'Enjoys chess')]


def test_execute_tool_memory_search_returns_json(monkeypatch):
    client = MemoryClient()
    monkeypatch.setattr(client, 'find_items', lambda query, labels=None, limit=12: [
        {'label': 'facts', 'value': 'Loves pizza'}
    ])

    success, payload = client.execute_tool('memory_search', {'query': 'pizza'})

    assert success is True
    data = json.loads(payload)
    assert data == [{'label': 'facts', 'text': 'Loves pizza'}]


def test_execute_tool_returns_false_for_unknown():
    client = MemoryClient()
    success, message = client.execute_tool('unknown_tool', {})
    assert success is False
    assert message == 'unsupported'
