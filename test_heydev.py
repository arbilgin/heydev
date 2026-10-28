# CS50x Final Project - heydev
# Used Gemini for help writing pytest fixtures.

from pathlib import Path

from auth import load_or_create_key, sign_challenge, verify_signature
from heydev import add_contact, load_contacts, parse_args, verify_incoming


def test_load_or_create_key(tmp_path, monkeypatch):
    # use a temp folder so tests don't overwrite real keys in ~/.heydev
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    priv1, pub1 = load_or_create_key("alice")
    priv2, pub2 = load_or_create_key("alice")

    assert pub1.startswith("ssh-ed25519 ")
    assert pub1 == pub2


def test_sign_and_verify_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    private_key, pubkey = load_or_create_key("alice")
    challenge = "random_challenge_nonce_123"

    signature = sign_challenge(private_key, challenge)
    assert verify_signature(pubkey, challenge, signature) is True


def test_verify_invalid_signature(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    alice_priv, alice_pub = load_or_create_key("alice")
    bob_priv, bob_pub = load_or_create_key("bob")

    challenge = "random_challenge_nonce_123"
    alice_sig = sign_challenge(alice_priv, challenge)

    assert verify_signature(alice_pub, "wrong_challenge", alice_sig) is False
    assert verify_signature(bob_pub, challenge, alice_sig) is False
    assert verify_signature(alice_pub, challenge, "not_valid_hex") is False


def test_verify_incoming_tofu_and_impostor(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    alice_priv, alice_pub = load_or_create_key("alice")
    impostor_priv, impostor_pub = load_or_create_key("impostor")

    payload = "alice:14:30:hello bob"
    valid_packet = {
        "from": "alice",
        "text": "hello bob",
        "time": "14:30",
        "pubkey": alice_pub,
        "signature": sign_challenge(alice_priv, payload),
    }
    assert verify_incoming(valid_packet) is True

    # someone else trying to send a message as alice with a different ssh key
    impostor_packet = {
        "from": "alice",
        "text": "hello bob",
        "time": "14:30",
        "pubkey": impostor_pub,
        "signature": sign_challenge(impostor_priv, payload),
    }
    assert verify_incoming(impostor_packet) is False


def test_parse_args_send(monkeypatch):
    monkeypatch.setattr("sys.argv", ["heydev.py", "-u", "arda", "bob", "hello", "world"])
    args = parse_args()
    assert args.user == "arda"
    assert args.recipient == "bob"
    assert " ".join(args.message) == "hello world"


def test_parse_args_inbox(monkeypatch):
    monkeypatch.setattr("sys.argv", ["heydev.py"])
    args = parse_args()
    assert args.user is None
    assert args.recipient is None
    assert args.message == []


def test_contacts(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    add_contact("arda", "bob")
    add_contact("arda", "alice")
    add_contact("arda", "arda")  # shouldn't add self

    assert load_contacts("arda") == {"alice", "bob"}
