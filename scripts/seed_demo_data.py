"""
Load the dashboard's demo dataset into MongoDB so Power BI (or the API's consumers) have data to read.

    python scripts/seed_demo_data.py            # insert the demo rows
    python scripts/seed_demo_data.py --clear    # remove only the rows this script inserted

Rows are flagged `"demo": true`, so --clear never touches real data. Uses MONGO_URI / MONGO_DB_NAME from `.env`.
The `trays` collection is a dashboard dimension (tray -> seed, media, optimal moisture band), not an API collection.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from scripts.demo_data import build_demo_dataset  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clear", action="store_true", help="delete the rows previously inserted by this script")
    args = parser.parse_args()

    db = MongoClient(settings.mongo_uri)[settings.mongo_db_name]
    data = build_demo_dataset()
    for collection, rows in data.items():
        if args.clear:
            print(f"{collection}: removed {db[collection].delete_many({'demo': True}).deleted_count}")
        else:
            db[collection].insert_many([{**row, "demo": True} for row in rows])
            print(f"{collection}: inserted {len(rows)}")


if __name__ == "__main__":
    main()
