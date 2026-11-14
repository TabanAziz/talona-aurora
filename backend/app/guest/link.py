"""Create the public guest deep link and a QR code for the presentation."""
import argparse
import os
import re
import sys
from pathlib import Path

import qrcode

from app.core import config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="PNG destination")
    args = parser.parse_args(argv)
    config.load_dotenv()
    username = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().removeprefix("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", username):
        print("Set TELEGRAM_BOT_USERNAME to the bot's public username.", file=sys.stderr)
        return 2
    link = f"https://t.me/{username}?start=guest"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(link).save(args.out, format="PNG")
    print(link)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
