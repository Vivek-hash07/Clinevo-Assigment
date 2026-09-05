"""Send synthetic mailbox fixtures. Usage: python -m app.scripts.seed_mailbox you@gmail.com"""

from __future__ import annotations

import argparse
import sys

from app.services.synthetic import send_synthetic_mailbox, synthetic_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Send synthetic Clinevo test emails via SMTP.")
    parser.add_argument("to_email", help="Destination mailbox (the connected Gmail address)")
    parser.add_argument(
        "--only",
        nargs="*",
        choices=[item.key for item in synthetic_catalog()],
        help="Optional template keys. Default: send all.",
    )
    args = parser.parse_args()
    result = send_synthetic_mailbox(args.to_email, args.only)
    print(f"Sent {result['count']} messages to {result['to']}: {', '.join(result['sent'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
