"""Generate local RSA keys without overwriting an existing key pair."""

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    directory = Path(__file__).resolve().parents[1] / "certs"
    directory.mkdir(exist_ok=True)
    private_path = directory / "jwt-private.pem"
    public_path = directory / "jwt-public.pem"
    if private_path.exists() or public_path.exists():
        raise SystemExit("Keys already exist; refusing to overwrite them.")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with os.fdopen(
        os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
    ) as stream:
        stream.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    with public_path.open("xb") as stream:
        stream.write(
            key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
    print(f"Created RSA keys in {directory}")


if __name__ == "__main__":
    main()
