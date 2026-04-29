#!/usr/bin/env python3
"""Pretty-print stored PocoAPoco conversations grouped by user."""
import argparse
import sqlite3
from datetime import datetime, timedelta

from config import DATABASE_PATH


def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return "?"
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


def main() -> None:
    p = argparse.ArgumentParser(description="Show stored PocoAPoco conversations.")
    p.add_argument("--user", help="Filter by username, first name, or telegram_id substring")
    p.add_argument("--days", type=int, help="Only show messages from the last N days")
    p.add_argument("--limit", type=int, help="Show only the most recent N messages per user")
    p.add_argument("--wrap", type=int, default=100, help="Wrap message text at N chars (default: 100)")
    args = p.parse_args()

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        "SELECT telegram_id, username, first_name, last_active "
        "FROM users ORDER BY last_active DESC NULLS LAST"
    )
    users = cur.fetchall()

    cutoff = None
    if args.days is not None:
        cutoff = (datetime.now() - timedelta(days=args.days)).isoformat()

    needle = args.user.lower() if args.user else None

    for u in users:
        haystack = " ".join(
            s for s in (u["username"], u["first_name"], str(u["telegram_id"])) if s
        ).lower()
        if needle and needle not in haystack:
            continue

        sql = "SELECT role, content, created_at FROM conversations WHERE telegram_id = ?"
        params: list = [u["telegram_id"]]
        if cutoff:
            sql += " AND created_at >= ?"
            params.append(cutoff)
        sql += " ORDER BY created_at DESC"
        if args.limit:
            sql += " LIMIT ?"
            params.append(args.limit)
        cur.execute(sql, params)
        rows = list(reversed(cur.fetchall()))
        if not rows:
            continue

        label = u["first_name"] or u["username"] or str(u["telegram_id"])
        header = f"=== {label} (id {u['telegram_id']}, last active {_fmt_ts(u['last_active'])}) ==="
        print()
        print(header)
        print("=" * len(header))
        for r in rows:
            who = "USER" if r["role"] == "user" else "BOT "
            ts = _fmt_ts(r["created_at"])
            text = r["content"] or ""
            if args.wrap and args.wrap > 0:
                lines = []
                for line in text.splitlines() or [""]:
                    while len(line) > args.wrap:
                        lines.append(line[: args.wrap])
                        line = line[args.wrap :]
                    lines.append(line)
                text = ("\n" + " " * 24).join(lines)
            print(f"  [{ts}] {who} | {text}")

    conn.close()


if __name__ == "__main__":
    main()
