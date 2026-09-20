#!/usr/bin/env python3
"""Create a private Fernet key without printing it or overwriting an old key."""
import argparse
import base64
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser()
parser.add_argument("--path", default="session_encryption_key.txt")
args = parser.parse_args()
path = Path(args.path)
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit("Key file already exists; it was not changed.")
with os.fdopen(descriptor, "wb") as stream:
    stream.write(base64.urlsafe_b64encode(secrets.token_bytes(32)) + b"\n")
    stream.flush()
    os.fsync(stream.fileno())
print(f"Private session key created: {path.resolve()}")
