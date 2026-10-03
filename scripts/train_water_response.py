"""
Train the Crop-Water Response model (Model 1) from the irrigation history in MongoDB.

    python scripts/train_water_response.py                       # train and save to WATER_RESPONSE_MODEL_PATH
    python scripts/train_water_response.py --dry-run             # train and report metrics, save nothing
    python scripts/train_water_response.py --out my.joblib --test-size 0.25

Training rows are `irrigation_logs` with pre_irrigation_moisture, post_irrigation_moisture and water_volume. Features
are rebuilt "as of" each event's timestamp (no future data). Events linked to a non-normal or injected fault are excluded.
The train/test split is grouped by crop batch (fallback: by date) -- never a random row split.
Moisture is % VWC, volume mL. Refuses to train below WATER_RESPONSE_MIN_TRAINING_ROWS rows. The API picks the artifact
up automatically (it reloads when the file changes).
"""
import argparse
import sys
from bisect import bisect_right
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymongo import MongoClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.ml.water_response.features import build_features  # noqa: E402
from app.ml.water_response.registry import resolve_path  # noqa: E402
from app.ml.water_response.trained import save_artifact, train_model  # noqa: E402
from app.models.common import as_utc  # noqa: E402

EXCLUDED_FAULTS = {"irrigation_id": {"$ne": None}, "$or": [{"fault_hypothesis": {"$ne": "normal"}}, {"injected": True}]}


def _utc_docs(cursor) -> list[dict[str, Any]]:
    docs = list(cursor)
    for doc in docs:
        for key in ("timestamp",):
            if doc.get(key) is not None:
                doc[key] = as_utc(doc[key])
    return docs


def build_training_rows(db) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (rows, groups). Each row = feature dict + `actual_response` + `timestamp`; db is a sync pymongo database."""
    excluded = {f["irrigation_id"] for f in db.fault_events.find(EXCLUDED_FAULTS, {"irrigation_id": 1})}
    logs = sorted(_utc_docs(db.irrigation_logs.find({})), key=lambda d: d["timestamp"])
    sensors_by_tray: dict[str, list[dict[str, Any]]] = {}
    for doc in sorted(_utc_docs(db.sensor_data.find({})), key=lambda d: d["timestamp"]):
        sensors_by_tray.setdefault(doc["tray_id"], []).append(doc)
    sensor_times = {tray: [d["timestamp"] for d in docs] for tray, docs in sensors_by_tray.items()}
    batches = list(db.crop_batches.find({}))
    batch_by_id = {b["batch_id"]: b for b in batches}
    history_by_tray: dict[str, list[dict[str, Any]]] = {}
    for log in logs:
        history_by_tray.setdefault(log["tray_id"], []).append(log)

    rows: list[dict[str, Any]] = []
    groups: list[str] = []
    for log in logs:
        pre, post, volume = (log.get(k) for k in ("pre_irrigation_moisture", "post_irrigation_moisture", "water_volume"))
        if pre is None or post is None or volume is None or log.get("irrigation_id") in excluded:
            continue
        tray, when = log["tray_id"], log["timestamp"]

        batch = batch_by_id.get(log.get("batch_id"))
        if batch is None:  # fall back to the batch active in that tray at the event date
            candidates = [
                b for b in batches if b["tray_id"] == tray and b["planting_date"] <= when.date().isoformat()
                and not b.get("harvest_date")
            ]
            batch = max(candidates, key=lambda b: b["planting_date"], default=None)

        sensor: dict[str, Any] = {}
        times = sensor_times.get(tray, [])
        index = bisect_right(times, when)
        if index:
            sensor = sensors_by_tray[tray][index - 1]

        features = build_features(
            tray_id=tray,
            event_time=when,
            water_volume=volume,
            pre_irrigation_moisture=pre,
            seed_type=(batch or {}).get("seed_type") or sensor.get("seed_type"),
            media_type=(batch or {}).get("media_type") or sensor.get("media_type"),
            growth_stage=log.get("growth_stage"),
            avg_flow_rate=log.get("avg_flow_rate"),
            temperature=sensor.get("temperature"),
            humidity=sensor.get("humidity"),
            light_intensity=sensor.get("light_intensity"),
            planting_date=date.fromisoformat(batch["planting_date"]) if batch else None,
            prior_irrigations=history_by_tray[tray],
        )
        rows.append({**features, "actual_response": post - pre, "timestamp": when})
        groups.append(log.get("batch_id") or when.date().isoformat())
    return rows, groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=settings.water_response_model_path, help="artifact path")
    parser.add_argument("--test-size", type=float, default=0.2, help="share of groups held out for evaluation")
    parser.add_argument("--dry-run", action="store_true", help="report metrics but do not save the artifact")
    args = parser.parse_args()

    db = MongoClient(settings.mongo_uri)[settings.mongo_db_name]
    rows, groups = build_training_rows(db)
    minimum = settings.water_response_min_training_rows
    if len(rows) < minimum:
        print(
            f"Refusing to train: {len(rows)} usable irrigation events, need at least {minimum} "
            "(events need pre/post moisture and water_volume, and must not be linked to a fault).",
            file=sys.stderr,
        )
        return 1
    try:
        artifact, metrics = train_model(rows, groups, test_size=args.test_size)
    except ValueError as exc:
        print(f"Refusing to train: {exc}", file=sys.stderr)
        return 1

    print(f"Trained on {artifact['n_rows']} events ({metrics['n_train']} train / {metrics['n_test']} held-out rows)")
    print(f"  MAE  (median model): {metrics['mae']:.2f} % points")
    print(f"  RMSE (median model): {metrics['rmse']:.2f} % points")
    print(f"  Interval coverage  : {metrics['interval_coverage']:.2f} (target about 0.80)")
    if args.dry_run:
        print("Dry run: artifact not saved.")
        return 0
    out = resolve_path(args.out)
    save_artifact(artifact, out)
    print(f"Saved {artifact['model_version']} to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
