# heydev
#### A Serverless SSH-Authenticated CLI Messaging Tool for Developers
#### Video Demo:  
#### Description:

**heydev** is a serverless, command-line messaging tool built for software developers who live in the terminal. Modern engineering teams constantly need to share quick status updates, error tracebacks, test results, or configuration snippets with teammates. However, doing so usually requires context-switching out of the terminal into heavy web or desktop chat applications, creating user accounts, managing passwords, or spinning up and maintaining dedicated chat servers.

`heydev` solves this by bringing authenticated, real-time and asynchronous messaging directly into the command line with **zero server setup**. Instead of usernames backed by a central database and password hashes, `heydev` uses OpenSSH `ed25519` cryptographic keys to sign and verify every message. And instead of requiring developers to host or run a background relay process on their own machines, `heydev` routes signed message packets through `ntfy.sh`'s public HTTPS and WebSocket pub/sub channels (`https://ntfy.sh` and `wss://ntfy.sh`). Because messages are cached automatically in transit, a developer can send a message (or pipe the output of a command) to a teammate on the other side of the world and immediately close their laptop; when the teammate comes online hours later and runs `heydev`, the waiting messages are downloaded, cryptographically verified, and displayed in their terminal.

---

### How It Works Under the Hood

#### 1. Serverless Delivery (Offline & Live)
When you send a message to a username (for example, `@bob`), `heydev` packages your message into a signed JSON payload and sends it via an HTTPS `POST` request to the recipient's inbox channel (`https://ntfy.sh/heydev_inbox_bob`).
* **If `@bob` is currently online** with `heydev` open in his terminal, the message arrives instantaneously over his open WebSocket stream (`wss://ntfy.sh/heydev_inbox_bob/ws`).
* **If `@bob` is offline**, the message waits in the channel cache. The next time `@bob` runs `heydev`, his client fetches all cached messages (`?since=all`), filters out any message IDs he has already read using his local `~/.heydev/seen_bob.json` state file, and prints only the new messages.

#### 2. End-to-End SSH Key Authentication (`Ed25519`)
Because messages travel over a public pub/sub service with no login accounts, `heydev` enforces authenticity using asymmetric cryptography:
* Each user has an OpenSSH `ed25519` private/public keypair stored locally in `~/.heydev/keys/<username>` (with strict `0600` owner-only permissions). If you do not have a key yet, `heydev` generates a standards-compliant OpenSSH keypair automatically on your first run.
* Before any message leaves your computer, `heydev` constructs the canonical payload string `"<sender>:<timestamp>:<message>"` and signs it with your `Ed25519` private key. Your private key never leaves your machine.
* The outgoing JSON packet includes your username, the message text, the timestamp, your OpenSSH public key string (`ssh-ed25519 ...`), and the hexadecimal signature.

#### 3. Impostor Protection via Trust-On-First-Use (TOFU)
When a recipient receives a message, `heydev` performs two security checks before displaying it:
1. **Mathematical Signature Verification:** It verifies the digital signature against the attached OpenSSH public key. If the message text, timestamp, or sender name was tampered with in transit, verification fails and the message is dropped.
2. **Known Keys Verification (`~/.heydev/known_keys.json`):** Inspired by OpenSSH's `~/.ssh/known_hosts`, `heydev` remembers the public key associated with each username you communicate with in `~/.heydev/known_keys.json`. The first time `@arda` messages `@bob`, `@bob`'s CLI records `@arda`'s public key. If an impostor on another machine later tries to send a message claiming to be `@arda` using a different SSH keypair, `@bob`'s CLI detects the key mismatch, blocks the message, and prints a warning (`[!] WARNING: SSH key mismatch for @arda! Impostor blocked.`).

#### 4. Live Online Presence & Saved Contacts
Even without a central server maintaining an active user table, `heydev` lets you see both **who is currently online** and **people you have previously communicated with**:
* **Live Presence (`heydev_presence`):** When you launch `heydev` in interactive mode, your CLI broadcasts a `"join"` event. Any other active `heydev` session sees that you came online and automatically responds with a `"here"` announcement so your terminal immediately lists all currently active usernames. When a user exits (`Ctrl+C`), their CLI broadcasts a `"leave"` event before closing.
* **Automatic Contact History (`~/.heydev/contacts_<username>.json`):** Whenever you send a message to someone or receive a verified message from someone, `heydev` automatically saves their username to your local contacts list. That way, even when a teammate is offline and you forget their exact username, you can see your previous contacts immediately upon opening `heydev` (or by running `heydev -c` / typing `/contacts`).

---

### Installation

Clone the repository and install `heydev` globally using `pipx` (recommended so `heydev` works in every terminal without activating a virtual environment):

```bash
git clone https://github.com/arbilgin/heydev.git
cd heydev
pipx install .
```

Alternatively, you can install it with standard `pip`:

```bash
pip install .
```
*(Or on Ubuntu/Debian systems outside a virtual environment without `pipx`: `pip install --user --break-system-packages .`)*

You can also run the script directly with Python without installing the CLI command:

```bash
pip install -r requirements.txt
python3 heydev.py bob "Hello!"
python3 heydev.py
```

---

### How to Use `heydev`

Designed around classic UNIX ergonomics (similar to `ssh` or `mail`), `heydev` uses a **single command** with no subcommands to memorize. It automatically detects what you want to do based on the arguments or pipe you provide:

#### 1. Send a One-Shot Message from the CLI
Pass the recipient's username followed by your message string. Your CLI signs the message, sends it, confirms delivery, and immediately returns you to your shell prompt:

```bash
heydev bob Hey Bob, I just pushed the fix to main!
heydev bob "Hey Bob, I just pushed the fix to main!"
```
Output:
```text
✓ Message sent to @bob
```

#### 2. Pipe Command Output Directly to a Teammate
Because `heydev` detects non-interactive `stdin` streams (`not sys.stdin.isatty()`), you can pipe the output of any terminal command—such as `pytest`, `git diff`, `git log`, or error logs—straight to another developer:

```bash
pytest | heydev bob
git status -s | heydev bob
```

#### 3. Check Your Inbox, See Online Users & Chat Live
Run `heydev` with no recipient argument to open your inbox, see your saved contacts and who is currently online, and enter live chat mode:

```bash
heydev
```
Any unread messages that were sent to you while you were offline will immediately print at the top of your terminal. You will also see live notifications as other users come online or go offline. While in the session, you can reply to anyone using `@<username> <message>`, or type `/online` or `/contacts` at any time:

```text
Connected as @arda. Waiting for messages (Ctrl+C to exit)...
Contacts: @alice, @bob
Online users: @arda
[+] @bob came online (Online: @arda, @bob)
[14:32] [@bob]: Hey Arda, did the tests pass?
@bob Sending you the pytest output right now!
✓ Message sent to @bob
/contacts
Contacts: @alice, @bob
```
Press `Ctrl+C` at any time to disconnect cleanly.

You can also list your saved contacts directly from the terminal without opening a session by passing `-c` / `--contacts`:
```bash
heydev -c
```

#### 4. Testing Multiple Users on One Computer (`-u` / `--user`)
By default, `heydev` uses your operating system login username (`getpass.getuser()`). To simulate and test multiple users side-by-side in two terminal windows on the same laptop, pass the `-u` or `--user` flag:

```bash
# Send a message as alice to bob:
heydev -u alice bob "Hello from Alice!"

# Open bob's inbox to receive Alice's message and reply:
heydev -u bob
```

---

### Running Automated Tests

The project includes an automated `pytest` suite that tests OpenSSH `ed25519` key generation, signature creation and verification, tampered payload rejection, Trust-On-First-Use impostor blocking, and CLI argument parsing:

```bash
pytest
```
