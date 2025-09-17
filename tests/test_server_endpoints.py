import importlib
import sys

import pytest


class StubSession:
    def __init__(self):
        self.chats = []

    def chat(self, text):
        self.chats.append(text)
        return {'reply': f'echo:{text}'}


@pytest.fixture
def server_client(monkeypatch):
    monkeypatch.setenv('CLERK_PUBLISHABLE_KEY', 'pk_test_stub')
    monkeypatch.setenv('CLERK_ISSUER', 'https://issuer.test')
    monkeypatch.setenv('CLERK_JWKS_URL', 'https://issuer.test/jwks.json')

    # Ensure fresh import so env vars take effect
    sys.modules.pop('web.server', None)
    server = importlib.import_module('web.server')

    stub = StubSession()
    monkeypatch.setattr(server, '_session_for_user', lambda _uid: stub)
    monkeypatch.setattr(server.CLERK, 'verify', lambda token: {'sub': 'user-token'})

    server.GUEST_USAGE.clear()

    client = server.app.test_client()
    return client, server, stub


def test_api_auth_config_returns_key(server_client):
    client, server, _ = server_client

    resp = client.get('/api/auth/config')
    assert resp.status_code == 200
    assert resp.get_json()['publishableKey'] == 'pk_test_stub'


def test_api_chat_allows_guest_without_token(server_client):
    client, server, stub = server_client
    server.GUEST_USAGE.clear()

    resp = client.post('/api/chat', json={'message': 'hello'}, headers={'X-Guest-Id': 'guest-1'})

    assert resp.status_code == 200
    assert stub.chats == ['hello']
    remaining = int(resp.headers['X-Guest-Remaining'])
    assert remaining == server.GUEST_MESSAGE_LIMIT - 1


def test_api_chat_without_credentials_is_unauthorized(server_client):
    client, server, _ = server_client
    server.GUEST_USAGE.clear()

    resp = client.post('/api/chat', json={'message': 'hello'})

    assert resp.status_code == 401
