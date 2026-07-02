#!/usr/bin/env python3
"""Pre-authenticate a user MTProto session for tg-if chat export.

Reads the "user" key from config/bots.json, runs an interactive
Pyrofork login via stdin, and saves the .session file for
headless Docker deployment.

Usage:
    python tools/auth_user.py

    python tools/auth_user.py --config /etc/tg-if/bots.json

    python tools/auth_user.py --output sessions/my_user.session

    # Copy the generated session file to your deploy directory:
    cp sessions/user_session.session /path/to/deploy/sessions/
"""

import argparse
import json
import sys
from pathlib import Path

from pyrogram import Client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from infrastructure.config import UserAccountConfig  # noqa: E402
from infrastructure.telegram.handlers import parse_session_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-authenticate a user MTProto session for tg-if chat export.",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config/bots.json",
        help="Path to the bots.json config file (default: config/bots.json)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            "Output path for the session file (e.g. sessions/my_user.session). "
            "Overrides session_file from the config."
        ),
    )
    args = parser.parse_args()

    bots_path = Path(args.config)
    if not bots_path.exists():
        sys.exit(f"Config file not found: {bots_path}")

    raw = json.loads(bots_path.read_text())
    user_data = raw.get("user")
    if not user_data:
        sys.exit(
            f'No "user" key in {bots_path}.\n'
            "Add one with api_id and api_hash:\n"
            '  {"user": {"api_id": ..., "api_hash": "..."}}\n'
            "Optionally include session_file to specify the output path "
            "in the config itself."
        )

    cfg = UserAccountConfig.model_validate(user_data)
    if args.output:
        name, workdir = parse_session_path(args.output)
    else:
        name, workdir = parse_session_path(cfg.session_file)

    print(f"Starting interactive login for user session '{name}'...")
    print(
        "Follow the prompts: phone number → verification code → 2FA password (if enabled)."
    )
    print("")

    client = Client(
        name=name,
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        workdir=workdir,
    )

    try:
        client.start()
    except Exception as e:
        sys.exit(f"Authentication failed: {e}")

    session_path = Path(workdir) / f"{name}.session"
    print(f"\nSession saved to: {session_path}")
    print("Copy this file into your tg-if sessions/ directory before deploying:")
    print(f"  cp {session_path} /path/to/deploy/sessions/")

    client.stop()


if __name__ == "__main__":
    main()
