"""Send synthetic mailbox fixtures. Usage: python -m app.scripts.seed_mailbox you@gmail.com"""

from __future__ import annotations

import argparse
import sys

from app.services.synthetic import batch_keys, send_synthetic_mailbox, synthetic_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Send synthetic Clinevo test emails via SMTP.")
    parser.add_argument("to_email", help="Destination mailbox (the connected Gmail address)")
    parser.add_argument(
        "--only",
        nargs="*",
        choices=[item.key for item in synthetic_catalog()],
        help="Optional template keys. Default: Day 6 batch of 15.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Send the full catalog instead of the 15-document batch.",
    )
    args = parser.parse_args()
    keys = None if args.all else (args.only or batch_keys())
    result = send_synthetic_mailbox(args.to_email, keys)
    print(f"Sent {result['count']} messages to {result['to']}: {', '.join(result['sent'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
