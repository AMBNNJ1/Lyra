import time

import pytest

from neuro_mvp.clerk_auth import ClerkVerifier, ClerkAuthError


def test_from_env_requires_configuration(monkeypatch):
    monkeypatch.delenv('CLERK_ISSUER', raising=False)
    monkeypatch.delenv('CLERK_JWKS_URL', raising=False)
    monkeypatch.delenv('CLERK_JWT_AUDIENCE', raising=False)

    with pytest.raises(RuntimeError):
        ClerkVerifier.from_env()


def test_from_env_builds_default_jwks(monkeypatch):
    monkeypatch.setenv('CLERK_ISSUER', 'https://example.com/')
    monkeypatch.delenv('CLERK_JWKS_URL', raising=False)
    monkeypatch.delenv('CLERK_JWT_AUDIENCE', raising=False)

    verifier = ClerkVerifier.from_env()

    assert verifier.issuer == 'https://example.com'
    assert verifier.jwks_url == 'https://example.com/.well-known/jwks.json'
    assert verifier.audience is None


def test_load_jwks_is_cached(monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append((url, timeout))

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {'keys': [{'kid': 'kid1'}]}

        return _Resp()

    verifier = ClerkVerifier(issuer='https://issuer', audience=None, jwks_url='https://issuer/jwks')
    monkeypatch.setattr('neuro_mvp.clerk_auth.requests.get', fake_get)

    first = verifier._load_jwks()
    second = verifier._load_jwks()

    assert first == {'keys': [{'kid': 'kid1'}]}
    assert second == first
    assert calls == [('https://issuer/jwks', 5)]


def test_get_key_refreshes_when_missing(monkeypatch):
    verifier = ClerkVerifier(issuer='https://issuer', audience=None, jwks_url='https://issuer/jwks')
    calls = []

    def fake_load():
        calls.append('load')
        if len(calls) == 1:
            return {'keys': [{'kid': 'old'}]}
        return {'keys': [{'kid': 'target'}]}

    monkeypatch.setattr(verifier, '_load_jwks', fake_load)

    key = verifier._get_key('target')

    assert key == {'kid': 'target'}
    assert calls == ['load', 'load']


def test_verify_decodes_token(monkeypatch):
    verifier = ClerkVerifier(issuer='https://issuer', audience='aud', jwks_url='https://issuer/jwks')
    verifier.cache_ttl = 3600

    monkeypatch.setattr(verifier, '_load_jwks', lambda: {'keys': [{'kid': 'kid123'}]})

    def fake_header(token):
        assert token == 'token123'
        return {'kid': 'kid123', 'alg': 'RS256'}

    decode_calls = {}

    def fake_decode(token, key, **kwargs):
        decode_calls['token'] = token
        decode_calls['key'] = key
        decode_calls['kwargs'] = kwargs
        return {'sub': 'user123'}

    monkeypatch.setattr('neuro_mvp.clerk_auth.jwt.get_unverified_header', fake_header)
    monkeypatch.setattr('neuro_mvp.clerk_auth.jwt.decode', fake_decode)

    claims = verifier.verify('token123')

    assert claims == {'sub': 'user123'}
    assert decode_calls['token'] == 'token123'
    assert decode_calls['key'] == {'kid': 'kid123'}
    assert decode_calls['kwargs']['algorithms'] == ['RS256']
    assert decode_calls['kwargs']['audience'] == 'aud'
    assert decode_calls['kwargs']['issuer'] == 'https://issuer'


def test_verify_missing_token_raises():
    verifier = ClerkVerifier(issuer=None, audience=None, jwks_url='https://issuer/jwks')

    with pytest.raises(ClerkAuthError):
        verifier.verify('')
