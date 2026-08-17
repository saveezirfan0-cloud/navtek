"""Command-line wrapper around lib/bootstrap.py.

The browser setup console at /setup does all of this with buttons and is the
supported path. This exists for anyone who prefers a terminal, and so the same
logic has a second caller keeping it honest.

    python scripts/bootstrap_board.py --dry-run
    python scripts/bootstrap_board.py
    python scripts/bootstrap_board.py --webhook https://your-service.vercel.app/eorder
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from _lib import bootstrap, config  # noqa: E402
from _lib.monday import Monday  # noqa: E402
from _lib.store import Store  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--webhook")
    parser.add_argument("--sync", action="store_true",
                        help="copy Installer Accounts from monday into Supabase")
    args = parser.parse_args()

    if not config.MONDAY_TOKEN:
        sys.exit("MONDAY_TOKEN is not set")

    monday = Monday()

    if args.sync:
        print(json.dumps(bootstrap.sync_installers(monday, Store()), indent=2))
        return

    if args.dry_run:
        for entry in bootstrap.plan_columns(monday):
            mark = "=" if entry["action"] == "exists" else "+"
            print(f"  {mark} {entry['title']:<26} {entry['column_id'] or entry['type']}")
        return

    result = bootstrap.create_columns(monday)
    print("\n".join("  " + line for line in result["log"]))

    board = bootstrap.create_installer_board(monday)
    print("\n".join("  " + line for line in board["log"]))
    link = bootstrap.create_installer_link(monday, board["board_id"])
    result["column_ids"]["installer"] = link["column_id"]

    print("\nPaste into Vercel:\n")
    print("COLUMN_IDS=" + json.dumps(result["column_ids"], separators=(",", ":")))
    print(f"INSTALLERS_BOARD_ID={board['board_id']}")

    if args.webhook:
        hook = bootstrap.register_webhook(
            monday, args.webhook, file_column_id=result["column_ids"].get("eorder_file")
        )
        print(f"\nWebhook {hook['webhook_id']} → {hook['url']}")


if __name__ == "__main__":
    main()
