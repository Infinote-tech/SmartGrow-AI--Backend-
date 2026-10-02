"""
Insert five dummy tray entries into MongoDB so the Power BI dashboard has data,
and optionally export all entries to CSV for Power BI's Text/CSV connector.

Entries are attached to an existing user (register one first via the API):

    python scripts/seed_tray_entries.py                      # first user in the DB
    python scripts/seed_tray_entries.py --email me@x.com     # a specific user
    python scripts/seed_tray_entries.py --export-csv tray_entries.csv
    python scripts/seed_tray_entries.py --clear-dummy        # remove seeded rows

Seeded rows carry `"dummy": true` so they can be removed later without touching real entries.
"""
import argparse
import csv
import sys
from datetime import UTC, datetime

from pymongo import MongoClient

sys.path.insert(0, ".")
from app.core.config import settings  # noqa: E402

DUMMY_ENTRIES = [
    # (seed_type, substrate_type, tray_number, date, time)
    ("radish", "cocopeat", 1, "2026-09-21", "07:30:00"),
    ("mustard", "cocopeat", 2, "2026-09-23", "09:15:00"),
    ("coriander", "compost", 3, "2026-09-25", "14:45:00"),
    ("sunflower", "tissue paper", 4, "2026-09-26", "18:10:00"),
    ("pea", "compost", 5, "2026-09-28", "11:00:00"),
]


def seed(db, email: str | None = None) -> int:
    user = db.users.find_one({"email": email} if email else {})
    if not user:
        raise SystemExit("No user found. Register one first: POST /api/v1/auth/register")
    now = datetime.now(UTC).isoformat()
    docs = [
        {
            "user_id": str(user["_id"]),
            "seed_type": seed_type,
            "substrate_type": substrate,
            "tray_number": tray,
            "date": date,
            "time": time,
            "created_at": now,
            "dummy": True,
        }
        for seed_type, substrate, tray, date, time in DUMMY_ENTRIES
    ]
    db.tray_entries.insert_many(docs)
    return len(docs)


def export_csv(db, path: str) -> int:
    fields = ["id", "user_id", "seed_type", "substrate_type", "tray_number", "date", "time"]
    rows = list(db.tray_entries.find())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({"id": str(row["_id"]), **{f: row.get(f) for f in fields[1:]}})
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", help="owner of the dummy entries (default: first user)")
    parser.add_argument("--export-csv", metavar="PATH", help="write all tray entries to a CSV and exit")
    parser.add_argument("--clear-dummy", action="store_true", help="delete rows seeded by this script and exit")
    args = parser.parse_args()

    db = MongoClient(settings.mongo_uri)[settings.mongo_db_name]
    if args.clear_dummy:
        print(f"Removed {db.tray_entries.delete_many({'dummy': True}).deleted_count} dummy entries")
    elif args.export_csv:
        print(f"Exported {export_csv(db, args.export_csv)} entries to {args.export_csv}")
    else:
        print(f"Inserted {seed(db, args.email)} dummy entries")


if __name__ == "__main__":
    main()
