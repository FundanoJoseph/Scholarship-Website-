from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from backend.config import required_env

PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "scholarship-portal"
JWT_LIFETIME = timedelta(hours=8)


def hash_password(password):
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash, password):
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def password_needs_rehash(password_hash):
    try:
        return PASSWORD_HASHER.check_needs_rehash(password_hash)
    except (InvalidHashError, VerificationError):
        return True


def create_access_token(user):
    secret = required_env("JWT_SECRET")
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 bytes.")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["id"]),
        "sv": int(user.get("session_version", 0)),
        "iat": now,
        "exp": now + JWT_LIFETIME,
        "iss": JWT_ISSUER,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token):
    secret = required_env("JWT_SECRET")
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 bytes.")
    return jwt.decode(
        token,
        secret,
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        options={"require": ["sub", "iat", "exp", "iss"]},
        leeway=timedelta(seconds=30),
    )


def token_max_age():
    return int(JWT_LIFETIME.total_seconds())
