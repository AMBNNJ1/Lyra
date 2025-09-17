from __future__ import annotations

import json
import os
import uuid
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any


def _pbkdf2(password: str, salt: bytes, rounds: int = 200_000) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=32)


@dataclass
class User:
    id: str
    email: str
    name: str
    provider: str  # local | google | facebook
    pass_hash: Optional[str] = None
    pass_salt: Optional[str] = None


class UserStore:
    def __init__(self, path: str = ".data/users.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.users: Dict[str, User] = {}
        self.emails: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._save()
            return
        try:
            data = json.loads(self.path.read_text("utf-8"))
            for uid, u in (data.get("users", {}) or {}).items():
                self.users[uid] = User(**u)
            self.emails = (data.get("emails", {}) or {})
        except Exception:
            self.users = {}
            self.emails = {}

    def _save(self) -> None:
        data = {
            "users": {uid: asdict(u) for uid, u in self.users.items()},
            "emails": self.emails,
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

    def create_local(self, email: str, password: str, name: str) -> User:
        email = (email or "").strip().lower()
        if not email or not password:
            raise ValueError("email and password required")
        if email in self.emails:
            raise ValueError("email_exists")
        uid = "u_" + uuid.uuid4().hex
        salt = os.urandom(16)
        h = _pbkdf2(password, salt)
        user = User(id=uid, email=email, name=name or email.split("@")[0], provider="local",
                    pass_hash=h.hex(), pass_salt=salt.hex())
        self.users[uid] = user
        self.emails[email] = uid
        self._save()
        return user

    def verify_local(self, email: str, password: str) -> Optional[User]:
        email = (email or "").strip().lower()
        uid = self.emails.get(email)
        if not uid:
            return None
        u = self.users.get(uid)
        if not u or not u.pass_hash or not u.pass_salt:
            return None
        h = _pbkdf2(password, bytes.fromhex(u.pass_salt))
        if h.hex() == u.pass_hash:
            return u
        return None

    def get(self, uid: str) -> Optional[User]:
        return self.users.get(uid)

    def get_by_email(self, email: str) -> Optional[User]:
        uid = self.emails.get((email or "").lower())
        return self.users.get(uid) if uid else None

