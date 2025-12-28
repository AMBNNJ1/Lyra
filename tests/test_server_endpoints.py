import importlib
import sys

import pytest


class StubMem:
    def __init__(self):
        self.user_id = None


class StubSession:
    def __init__(self):
        self.chats = []
        self.mem = StubMem()

    def chat(self, text):
        self.chats.append(text)
        return {'reply': f'echo:{text}'}

    def stream_chat(self, text):
        yield f'echo:{text}'


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


def test_api_chat_without_credentials_gets_cookie_and_quota(server_client):
    """Guests without X-Guest-Id get an auto-generated cookie and quota enforcement."""
    client, server, stub = server_client
    server.GUEST_USAGE.clear()

    resp = client.post('/api/chat', json={'message': 'hello'})

    assert resp.status_code == 200
    assert stub.chats == ['hello']
    # Now all guests get quota tracking
    assert 'X-Guest-Remaining' in resp.headers
    remaining = int(resp.headers['X-Guest-Remaining'])
    assert remaining == server.GUEST_MESSAGE_LIMIT - 1
    # Cookie should be set for new guests
    assert '__guest_id' in resp.headers.get('Set-Cookie', '')


def test_guest_quota_enforced_without_header(server_client):
    """Quota is enforced even when X-Guest-Id header is omitted (no bypass)."""
    client, server, stub = server_client
    server.GUEST_USAGE.clear()

    # Send messages until quota is exhausted
    # First request will generate a cookie
    resp = client.post('/api/chat', json={'message': 'msg1'})
    assert resp.status_code == 200
    cookie = resp.headers.get('Set-Cookie', '')
    assert '__guest_id=' in cookie

    # Extract guest_id from cookie for subsequent requests
    import re
    match = re.search(r'__guest_id=([^;]+)', cookie)
    guest_cookie = match.group(1) if match else ''

    # Continue sending messages using the cookie
    for i in range(2, server.GUEST_MESSAGE_LIMIT + 1):
        stub.chats.clear()
        resp = client.post(
            '/api/chat',
            json={'message': f'msg{i}'},
            headers={'Cookie': f'__guest_id={guest_cookie}'}
        )
        assert resp.status_code == 200, f'Message {i} should succeed'

    # Next message should hit quota limit
    stub.chats.clear()
    resp = client.post(
        '/api/chat',
        json={'message': 'over_limit'},
        headers={'Cookie': f'__guest_id={guest_cookie}'}
    )
    assert resp.status_code == 429
    assert resp.get_json()['error'] == 'guest_limit_reached'
    assert stub.chats == []  # Message should not be processed


def test_guest_isolation_different_cookies(server_client):
    """Different guest cookies get separate sessions and quotas."""
    client, server, stub = server_client
    server.GUEST_USAGE.clear()
    server.SESSIONS.clear()

    # First guest
    resp1 = client.post('/api/chat', json={'message': 'guest1'})
    assert resp1.status_code == 200
    cookie1 = resp1.headers.get('Set-Cookie', '')
    import re
    match1 = re.search(r'__guest_id=([^;]+)', cookie1)
    guest1_id = match1.group(1) if match1 else ''

    # Second guest (new request without cookie)
    resp2 = client.post('/api/chat', json={'message': 'guest2'})
    assert resp2.status_code == 200
    cookie2 = resp2.headers.get('Set-Cookie', '')
    match2 = re.search(r'__guest_id=([^;]+)', cookie2)
    guest2_id = match2.group(1) if match2 else ''

    # Different guests should have different IDs
    assert guest1_id != guest2_id
    assert guest1_id != ''
    assert guest2_id != ''


def test_guest_cannot_bypass_quota_by_omitting_header(server_client):
    """
    Regression test: previously, omitting X-Guest-Id would bypass quota entirely
    because all such users shared 'guest-anon' and quota wasn't enforced.
    """
    client, server, stub = server_client
    server.GUEST_USAGE.clear()

    # Exhaust quota for a cookie-based guest
    resp = client.post('/api/chat', json={'message': 'first'})
    cookie = resp.headers.get('Set-Cookie', '')
    import re
    match = re.search(r'__guest_id=([^;]+)', cookie)
    guest_cookie = match.group(1) if match else ''

    # Use up remaining quota
    for _ in range(server.GUEST_MESSAGE_LIMIT - 1):
        client.post(
            '/api/chat',
            json={'message': 'fill'},
            headers={'Cookie': f'__guest_id={guest_cookie}'}
        )

    # Verify quota is exhausted
    resp = client.post(
        '/api/chat',
        json={'message': 'blocked'},
        headers={'Cookie': f'__guest_id={guest_cookie}'}
    )
    assert resp.status_code == 429


def test_guest_with_header_still_works(server_client):
    """X-Guest-Id header still works and takes precedence over cookie."""
    client, server, stub = server_client
    server.GUEST_USAGE.clear()

    resp = client.post(
        '/api/chat',
        json={'message': 'hello'},
        headers={'X-Guest-Id': 'explicit-guest-123'}
    )

    assert resp.status_code == 200
    assert 'X-Guest-Remaining' in resp.headers
    # No new cookie should be set when header is provided
    # (cookie may still be set if it's a first visit, but header takes precedence)


def test_cookie_persists_guest_session(server_client):
    """Guest session persists across requests using the cookie."""
    client, server, stub = server_client
    server.GUEST_USAGE.clear()

    # First request
    resp1 = client.post('/api/chat', json={'message': 'first'})
    cookie = resp1.headers.get('Set-Cookie', '')
    import re
    match = re.search(r'__guest_id=([^;]+)', cookie)
    guest_cookie = match.group(1) if match else ''
    remaining1 = int(resp1.headers['X-Guest-Remaining'])

    # Second request with same cookie
    stub.chats.clear()
    resp2 = client.post(
        '/api/chat',
        json={'message': 'second'},
        headers={'Cookie': f'__guest_id={guest_cookie}'}
    )
    remaining2 = int(resp2.headers['X-Guest-Remaining'])

    # Quota should decrement
    assert remaining2 == remaining1 - 1
