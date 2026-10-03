"""
Train the optional learned fault classifier (Model 2, Stage B) from deliberately injected faults.

    python scripts/train_fault_classifier.py              # train and save to FAULT_CLASSIFIER_PATH
    python scripts/train_fault_classifier.py --dry-run    # report only

Training examples are `fault_events` with `injected = true`, a `fault_hypothesis` label and an `irrigation_id`
(post those via POST /fault-events during fault-injection experiments). Features come from the linked irrigation log:
flow_class, avg_flow_rate (L/min), flow_cv, actual_response, expected_response, response_deviation (% points) and z.
A DecisionTreeClassifier(max_depth=4) is fitted. Refuses to train with fewer than 10 examples per class (or < 2 classes).
Once the artifact exists, the Response-Deviation model prefers it over the rules (`detected_by = "model"`).
"""
import argparse
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402
import numpy as np  # noqa: E402
from pymongo import MongoClient  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.ml.response_deviation.rules import classifier_features, classify_flow  # noqa: E402
from app.ml.water_response.registry import resolve_path  # noqa: E402
from app.ml.water_response.scoring import half_interval  # noqa: E402

MIN_PER_CLASS = 10


def build_examples(db) -> tuple[list[list[float]], list[str]]:
    """Return (feature vectors, labels) from injected, labelled fault events (db is a sync pymongo database)."""
    X: list[list[float]] = []
    y: list[str] = []
    query = {"injected": True, "fault_hypothesis": {"$ne": None}, "irrigation_id": {"$ne": None}}
    for fault in db.fault_events.find(query):
        log = db.irrigation_logs.find_one({"irrigation_id": fault["irrigation_id"]})
        if not log or log.get("actual_response") is None or log.get("response_deviation") is None:
            continue
        half = half_interval(fault.get("expected_min"), fault.get("expected_max"), settings.deviation_min_tolerance)
        flow_class = fault.get("flow_class") or classify_flow(log.get("avg_flow_rate"), log.get("flow_cv"))[0]
        X.append(
            classifier_features(
                flow_class,
                log.get("avg_flow_rate"),
                log.get("flow_cv"),
                log["actual_response"],
                log.get("expected_response"),
                log["response_deviation"],
                log["response_deviation"] / half,
            )
        )
        y.append(fault["fault_hypothesis"])
    return X, y


def train(X: list[list[float]], y: list[str]) -> dict[str, Any]:
    counts = Counter(y)
    if len(counts) < 2:
        raise ValueError(f"need at least 2 fault classes, found {len(counts)}: {dict(counts)}")
    short = {label: n for label, n in counts.items() if n < MIN_PER_CLASS}
    if short:
        raise ValueError(f"need at least {MIN_PER_CLASS} examples per class, too few for: {short}")
    pipeline = Pipeline([("tree", DecisionTreeClassifier(max_depth=4, random_state=0))]).fit(np.array(X), y)
    return {
        "pipeline": pipeline,
        "model_version": f"fault-clf-{datetime.now(UTC).date().isoformat()}",
        "trained_at": datetime.now(UTC).isoformat(),
        "n_rows": len(y),
        "class_counts": dict(counts),
        "training_accuracy": float(pipeline.score(np.array(X), y)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=settings.fault_classifier_path, help="artifact path")
    parser.add_argument("--dry-run", action="store_true", help="report only, do not save")
    args = parser.parse_args()

    db = MongoClient(settings.mongo_uri)[settings.mongo_db_name]
    X, y = build_examples(db)
    try:
        artifact = train(X, y)
    except ValueError as exc:
        print(f"Refusing to train: {exc}", file=sys.stderr)
        return 1
    print(f"Trained on {artifact['n_rows']} injected faults: {artifact['class_counts']}")
    print(f"  training accuracy: {artifact['training_accuracy']:.2f}")
    if args.dry_run:
        print("Dry run: artifact not saved.")
        return 0
    out = resolve_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, out)
    print(f"Saved {artifact['model_version']} to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
