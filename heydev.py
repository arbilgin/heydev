import argparse
import asyncio
import base64
import getpass
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import websockets

from auth import load_or_create_key, sign_challenge, verify_signature

NTFY_HOST = "ntfy.sh"
TOPIC_PREFIX = "heydev_inbox_"
PRESENCE_TOPIC = "heydev_presence"


def parse_args():
    parser = argparse.ArgumentParser(description="heydev: CLI messaging for developers")

    # -u is mainly for testing different users on the same machine
    parser.add_argument("-u", "--user", help="Your username")
    parser.add_argument(
        "-c",
        "--contacts",
        action="store_true",
        help="List people you previously messaged",
    )
    parser.add_argument("recipient", nargs="?", help="Username to send a message to")
    parser.add_argument("message", nargs="*", help="Message to send")

    return parser.parse_args()


def load_contacts(username):
    contacts_file = Path.home() / ".heydev" / f"contacts_{username}.json"
    if contacts_file.exists():
        return set(json.loads(contacts_file.read_text()))
    return set()


def add_contact(username, other):
    if not other or other == username:
        return
    contacts = load_contacts(username)
    if other not in contacts:
        contacts.add(other)
        contacts_file = Path.home() / ".heydev" / f"contacts_{username}.json"
        contacts_file.parent.mkdir(parents=True, exist_ok=True)
        contacts_file.write_text(json.dumps(sorted(contacts), indent=2))


def send_once(username, recipient, text):
    private_key, pubkey = load_or_create_key(username)
    timestamp = datetime.now().strftime("%H:%M")

    # sign sender + time + text together so nothing can be tampered with
    payload_to_sign = f"{username}:{timestamp}:{text}"
    signature = sign_challenge(private_key, payload_to_sign)

    packet = json.dumps(
        {
            "from": username,
            "text": text,
            "time": timestamp,
            "pubkey": pubkey,
            "signature": signature,
        }
    ).encode()

    # base64 encode so ntfy.sh always treats the payload as raw text
    encoded_packet = base64.b64encode(packet)

    url = f"https://{NTFY_HOST}/{TOPIC_PREFIX}{recipient}"
    req = urllib.request.Request(url, data=encoded_packet, method="POST")
    with urllib.request.urlopen(req) as resp:
        if resp.status == 200:
            add_contact(username, recipient)
            print(f"✓ Message sent to @{recipient}")


def verify_incoming(data):
    sender = data["from"]
    payload = f"{sender}:{data['time']}:{data['text']}"

    if not verify_signature(data["pubkey"], payload, data["signature"]):
        print(f"[!] Dropped message with invalid SSH signature from @{sender}")
        return False

    # works like ~/.ssh/known_hosts: save the user's key on first message,
    # and reject if someone else tries to use the same username with another key
    known_file = Path.home() / ".heydev" / "known_keys.json"
    known_file.parent.mkdir(parents=True, exist_ok=True)
    known_keys = json.loads(known_file.read_text()) if known_file.exists() else {}

    if sender in known_keys and known_keys[sender] != data["pubkey"]:
        print(f"[!] WARNING: SSH key mismatch for @{sender}! Impostor blocked.")
        return False

    known_keys[sender] = data["pubkey"]
    known_file.write_text(json.dumps(known_keys, indent=2))
    return True


# keep track of message IDs we already printed so ?since=all doesn't repeat old messages
def load_seen_ids(username):
    seen_file = Path.home() / ".heydev" / f"seen_{username}.json"
    if seen_file.exists():
        return set(json.loads(seen_file.read_text()))
    return set()


def save_seen_ids(username, seen_ids):
    seen_file = Path.home() / ".heydev" / f"seen_{username}.json"
    seen_file.parent.mkdir(parents=True, exist_ok=True)
    seen_file.write_text(json.dumps(list(seen_ids)))


def send_presence(username, status):
    packet = json.dumps({"user": username, "status": status}).encode()
    url = f"https://{NTFY_HOST}/{PRESENCE_TOPIC}"
    req = urllib.request.Request(url, data=packet, method="POST")
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def handle_stdin_line(username, online_users):
    line = sys.stdin.readline().strip()
    if not line:
        return
    if line == "/online":
        users_str = ", ".join(f"@{u}" for u in sorted(online_users))
        print(f"Online users: {users_str}")
    elif line == "/contacts":
        contacts = load_contacts(username)
        if contacts:
            print("Contacts: " + ", ".join(f"@{u}" for u in sorted(contacts)))
        else:
            print("No saved contacts yet.")
    elif line.startswith("@") and " " in line:
        recipient, text = line[1:].split(" ", 1)
        send_once(username, recipient, text)
    else:
        print("Usage: @<username> <message>  (or /online, /contacts)")


async def listen_inbox(username):
    # make sure our own key is generated and saved in known_keys right away
    _, pubkey = load_or_create_key(username)
    known_file = Path.home() / ".heydev" / "known_keys.json"
    known_file.parent.mkdir(parents=True, exist_ok=True)
    known_keys = json.loads(known_file.read_text()) if known_file.exists() else {}
    if username not in known_keys:
        known_keys[username] = pubkey
        known_file.write_text(json.dumps(known_keys, indent=2))

    seen_ids = load_seen_ids(username)
    online_users = {username}
    inbox_topic = f"{TOPIC_PREFIX}{username}"
    ws_url = f"wss://{NTFY_HOST}/{inbox_topic},{PRESENCE_TOPIC}/ws?since=all"

    loop = asyncio.get_running_loop()
    loop.add_reader(sys.stdin, handle_stdin_line, username, online_users)

    try:
        async with websockets.connect(ws_url) as ws:
            print(f"Connected as @{username}. Waiting for messages (Ctrl+C to exit)...")
            contacts = load_contacts(username)
            if contacts:
                print("Contacts: " + ", ".join(f"@{u}" for u in sorted(contacts)))
            send_presence(username, "join")
            loop.call_later(
                0.8,
                lambda: print(
                    "Online users: " + ", ".join(f"@{u}" for u in sorted(online_users))
                ),
            )

            async for raw in ws:
                event = json.loads(raw)
                if event.get("event") != "message":
                    continue

                # handle live presence events (ignore cached ones older than 10s)
                if event.get("topic") == PRESENCE_TOPIC:
                    if time.time() - event.get("time", 0) > 10:
                        continue
                    pres = json.loads(event["message"])
                    other = pres.get("user")
                    status = pres.get("status")
                    if not other or other == username:
                        continue

                    if status == "join":
                        online_users.add(other)
                        users_str = ", ".join(f"@{u}" for u in sorted(online_users))
                        print(f"[+] @{other} came online (Online: {users_str})")
                        send_presence(username, "here")
                    elif status == "here":
                        online_users.add(other)
                    elif status == "leave" and other in online_users:
                        online_users.discard(other)
                        users_str = ", ".join(f"@{u}" for u in sorted(online_users))
                        print(f"[-] @{other} went offline (Online: {users_str})")
                    continue

                msg_id = event.get("id")
                if msg_id in seen_ids:
                    continue

                seen_ids.add(msg_id)
                save_seen_ids(username, seen_ids)

                raw_msg = event.get("message", "")
                if "attachment" in event:
                    att_url = event["attachment"]["url"]
                    raw_msg = urllib.request.urlopen(att_url).read().decode()

                try:
                    decoded = base64.b64decode(raw_msg).decode()
                    data = json.loads(decoded)
                except Exception:
                    try:
                        data = json.loads(raw_msg)
                    except Exception:
                        continue

                if verify_incoming(data):
                    add_contact(username, data["from"])
                    print(f"[{data['time']}] [@{data['from']}]: {data['text']}")
    finally:
        loop.remove_reader(sys.stdin)
        send_presence(username, "leave")


def main():
    args = parse_args()
    message = " ".join(args.message).strip() if args.message else None
    username = args.user or getpass.getuser()

    if args.contacts:
        contacts = load_contacts(username)
        if contacts:
            print("Contacts: " + ", ".join(f"@{u}" for u in sorted(contacts)))
        else:
            print("No saved contacts yet.")
        return

    # check if something was piped in (e.g. pytest | heydev bob)
    if message is None and not sys.stdin.isatty():
        message = sys.stdin.read().strip()

    if args.recipient is None:
        try:
            asyncio.run(listen_inbox(username))
        except KeyboardInterrupt:
            print("\nDisconnected.")
    elif message:
        send_once(username, args.recipient, message)
    else:
        print("Error: Please provide a message to send.")
        sys.exit(1)


if __name__ == "__main__":
    main()
