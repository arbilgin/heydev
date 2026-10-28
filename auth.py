from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def load_or_create_key(username):
    keys_dir = Path.home() / ".heydev" / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    priv_path = keys_dir / username

    # load existing key if the user already has one, otherwise generate a new ed25519 key
    if priv_path.exists():
        private_key = serialization.load_ssh_private_key(
            priv_path.read_bytes(), password=None
        )
    else:
        private_key = ed25519.Ed25519PrivateKey.generate()
        priv_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
        priv_path.write_bytes(priv_bytes)
        priv_path.chmod(0o600)

    pub_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    return private_key, pub_bytes.decode()


def sign_challenge(private_key, challenge):
    signature = private_key.sign(challenge.encode())
    return signature.hex()


def verify_signature(public_key_str, challenge, signature_hex):
    try:
        public_key = serialization.load_ssh_public_key(public_key_str.encode())
        public_key.verify(bytes.fromhex(signature_hex), challenge.encode())
        return True
    except (InvalidSignature, ValueError):
        return False
