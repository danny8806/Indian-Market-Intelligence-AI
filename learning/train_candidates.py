"""Isolated, non-deployed challenger trained on *all frozen news candidates*.

Output predicts historical probability of positive open-to-close move, not
trading profitability. Model is never sent to the live desk or broker.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MIN_DAYS = 40
MIN_OBSERVATIONS = 250


def train(csv_path: Path, out: Path) -> dict:
    if not csv_path.exists():
        return {"status": "INSUFFICIENT_DATA", "reason": "No frozen candidate outcomes available"}
    import pandas as pd
    df = pd.read_csv(csv_path, dtype={"symbol": str, "date": str})
    needed = ["date", "symbol", "up", "review_priority", "articles",
              "official_filing_count", "material_event_count", "positive_yoy_metrics",
              "negative_yoy_metrics", "conflicting_metrics", "news_age_hours",
              "categories_json", "headlines_json", "snapshot_sha256"]
    if df.empty or any(n not in df.columns for n in needed):
        return {"status": "INSUFFICIENT_DATA", "reason": "Empty or incomplete labeled dataset"}
    if df.duplicated(["date", "symbol"]).any():
        raise ValueError("Duplicate candidate/date rows")
    if df[needed].isna().any().any():
        raise ValueError("Missing model features or outcome labels")
    dates = sorted(df.date.unique())
    if len(dates) < MIN_DAYS or len(df) < MIN_OBSERVATIONS or df.up.nunique() != 2:
        return {"status": "INSUFFICIENT_DATA", "sessions": len(dates),
                "observations": len(df), "min_sessions": MIN_DAYS,
                "min_observations": MIN_OBSERVATIONS}
    import numpy as np
    from joblib import dump
    from sklearn.compose import ColumnTransformer
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    cut = max(1, min(len(dates)-1, int(len(dates) * 0.75)))
    train_part = df[df.date.isin(dates[:cut])].copy()
    holdout = df[df.date.isin(dates[cut:])].copy()
    if train_part.up.nunique() != 2 or holdout.up.nunique() != 2:
        return {"status": "INSUFFICIENT_CLASS_VARIETY", "reason": "Holdout needs both directions"}
    numeric = ["review_priority", "articles", "official_filing_count",
               "material_event_count", "positive_yoy_metrics", "negative_yoy_metrics",
               "conflicting_metrics", "news_age_hours"]
    for frame in (train_part, holdout):
        frame["text"] = (frame["categories_json"].astype(str) + " " +
                         frame["headlines_json"].astype(str))
        for col in numeric:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    if train_part[numeric].isna().all(axis=0).any():
        return {"status": "INVALID_NUMERIC_FEATURES"}
    features = ColumnTransformer([
        ("text", TfidfVectorizer(max_features=1500, min_df=2,
                                 ngram_range=(1, 2)), "text"),
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median")),
                              ("scale", StandardScaler())]), numeric),
    ])
    learner = Pipeline([
        ("features", features),
        ("classification", LogisticRegression(C=0.1, max_iter=1500, class_weight=None)),
    ])
    columns = ["text"] + numeric
    learner.fit(train_part[columns], train_part.up.astype(int))
    predicted = learner.predict_proba(holdout[columns])[:, 1]
    baseline = float(train_part.up.mean())
    baseline_prob = np.full(len(holdout), baseline)
    metrics = {
        "status": "CHALLENGER_ONLY_NOT_DEPLOYED",
        "train_days": int(len(dates[:cut])),
        "holdout_days": int(len(dates[cut:])),
        "train_rows": len(train_part), "holdout_rows": len(holdout),
        "train_last_session": dates[cut-1], "holdout_first_session": dates[cut],
        "holdout_brier": round(float(brier_score_loss(holdout.up, predicted)), 6),
        "baseline_brier": round(float(brier_score_loss(holdout.up, baseline_prob)), 6),
        "holdout_logloss": round(float(log_loss(holdout.up, predicted)), 6),
        "baseline_logloss": round(float(log_loss(holdout.up, baseline_prob)), 6),
        "holdout_auc": round(float(roc_auc_score(holdout.up, predicted)), 6),
        "beat_baseline_brier": bool(
            brier_score_loss(holdout.up, predicted) < brier_score_loss(holdout.up, baseline_prob)),
        "trained_at_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
        "promotion_allowed": False,
        "note": ("Outcome labels are theoretical open-to-close moves, not executable profit. "
                 "Yahoo data or supplied CSV may not be NSE-verified. "
                 "Contiguous session holdout is a preliminary test, not proof of forward profitability."),
    }
    out.mkdir(parents=True, exist_ok=True)
    dump(learner, out / "candidate_challenger.joblib")
    (out / "candidate_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, default=ROOT / "learning/data/candidate_outcomes.csv")
    p.add_argument("--out", type=Path, default=ROOT / "learning/out_candidates")
    args = p.parse_args()
    print(json.dumps(train(args.csv, args.out), indent=2))


if __name__ == "__main__":
    main()
