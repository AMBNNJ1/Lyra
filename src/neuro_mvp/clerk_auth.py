from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from jose import jwt


class ClerkAuthError(Exception):
    """Raised when Clerk authentication fails."""


@dataclass
class ClerkVerifier:
    issuer: Optional[str]
    audience: Optional[str]
    jwks_url: str
    cache_ttl: int = 3600

    _jwks: Optional[Dict[str, Any]] = None
    _jwks_fetched_at: float = 0.0

    @classmethod
    def from_env(cls) -> "ClerkVerifier":
        issuer = os.getenv("CLERK_ISSUER")
        jwks_url = os.getenv("CLERK_JWKS_URL")
        audience = os.getenv("CLERK_JWT_AUDIENCE")
        if not issuer and not jwks_url:
            raise RuntimeError("CLERK_ISSUER or CLERK_JWKS_URL must be set for Clerk auth")
        if issuer:
            issuer = issuer.rstrip("/")
        if not jwks_url:
            jwks_url = f"{issuer}/.well-known/jwks.json"
        return cls(issuer=issuer, audience=audience, jwks_url=jwks_url)

    def _load_jwks(self) -> Dict[str, Any]:
        now = time.time()
        if not self._jwks or (now - self._jwks_fetched_at) > self.cache_ttl:
            resp = requests.get(self.jwks_url, timeout=5)
            resp.raise_for_status()
            self._jwks = resp.json()
            self._jwks_fetched_at = now
        return self._jwks or {}

    def _get_key(self, kid: str) -> Dict[str, Any]:
        jwks = self._load_jwks().get("keys", [])
        for key in jwks:
            if key.get("kid") == kid:
                return key
        # Refresh once and retry
        self._jwks = None
        jwks = self._load_jwks().get("keys", [])
        for key in jwks:
            if key.get("kid") == kid:
                return key
        raise ClerkAuthError("jwks_key_not_found")

    def verify(self, token: str) -> Dict[str, Any]:
        if not token:
            raise ClerkAuthError("missing_token")
        try:
            headers = jwt.get_unverified_header(token)
        except Exception as exc:  # noqa: BLE001
            raise ClerkAuthError("invalid_token_header") from exc
        kid = headers.get("kid")
        if not kid:
            raise ClerkAuthError("token_missing_kid")
        key = self._get_key(kid)
        algorithms = [headers.get("alg", "RS256")]
        decode_kwargs: Dict[str, Any] = {"algorithms": algorithms}
        if self.audience:
            decode_kwargs["audience"] = self.audience
        if self.issuer:
            decode_kwargs["issuer"] = self.issuer
        try:
            claims = jwt.decode(token, key, **decode_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise ClerkAuthError(f"token_invalid: {exc}") from exc
        return claims
