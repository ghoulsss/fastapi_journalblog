from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from config import settings


def validate_jwt_keys() -> None:
    try:
        private = serialization.load_pem_private_key(
            settings.auth_jwt.private_key_path.read_bytes(), password=None
        )
        public = serialization.load_pem_public_key(
            settings.auth_jwt.public_key_path.read_bytes()
        )
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(
            "JWT keys are missing or unreadable. Run python scripts/generate_jwt_keys.py "
            "or configure AUTH_JWT__PRIVATE_KEY_PATH and AUTH_JWT__PUBLIC_KEY_PATH."
        ) from exc
    if (
        not isinstance(private, rsa.RSAPrivateKey)
        or not isinstance(public, rsa.RSAPublicKey)
        or private.key_size < 2048
        or private.public_key().public_numbers() != public.public_numbers()
    ):
        raise RuntimeError("JWT keys must be a matching RSA pair of at least 2048 bits")


def encode_jwt(
    payload: dict,
    key: str | None = None,
    algorithm: str | None = None,
    expired_minutes: int | None = None,
    expired_timedelta: timedelta | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    lifetime = (
        expired_timedelta
        if expired_timedelta is not None
        else timedelta(
            minutes=expired_minutes
            if expired_minutes is not None
            else settings.auth_jwt.access_token_expired_minutes
        )
    )
    return jwt.encode(
        {**payload, "exp": now + lifetime, "iat": now},
        key if key is not None else settings.auth_jwt.private_key_path.read_text(),
        algorithm=algorithm or settings.auth_jwt.algorithm,
    )


def decode_jwt(token: str | bytes, public_key: str | None = None) -> dict:
    return jwt.decode(
        token,
        public_key
        if public_key is not None
        else settings.auth_jwt.public_key_path.read_text(),
        algorithms=[settings.auth_jwt.algorithm],
        options={"require": ["exp", "iat", "sub"]},
    )


def hash_password(password: str) -> bytes:
    raw = password.encode()
    if not 8 <= len(raw) <= 72:
        raise ValueError("Password must contain 8 to 72 UTF-8 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt())


def validate_password(password: str, hashed_password: bytes) -> bool:
    raw = password.encode()
    if len(raw) > 72:
        return False
    try:
        return bcrypt.checkpw(raw, hashed_password)
    except ValueError:
        return False
