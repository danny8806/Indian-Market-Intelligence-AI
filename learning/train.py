"""Train a challenger for direction correctness; NEVER deploy automatically.

Only features known before 09:00 IST are permitted. Selected-signal-only data
cannot teach the model to find missed news, so this is only a conditional
reranker until a complete pre-market candidate pool is collected.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MIN_DAYS = 40
MIN_TRADES = 160


def train(csv_path: Path, output: Path) -> dict:
    if not csv_path.exists():
        return {"status": "INSUFFICIENT_DATA", "reason": "No scored morning trades yet."}
    frame = pd.read_csv(csv_path, dtype={"symbol": str})
    if frame.empty:
        return {"status": "INSUFFICIENT_DATA", "reason": "Empty history."}
    frame = frame.dropna(subset=["date", "side", "reason", "news_summary", "won"])
    frame["won"] = frame["won"].astype(int)
    # No opening gap, prices, returns, or other post-9AM features.
    dates = sorted(frame.date.unique())
    if len(dates) < MIN_DAYS or len(frame) < MIN_TRADES or frame.won.nunique() < 2:
        return {"status": "INSUFFICIENT_DATA", "sessions": len(dates),
                "observations": len(frame), "min_sessions": MIN_DAYS,
                "min_observations": MIN_TRADES}
    cut = max(1, int(len(dates)*0.75))
    train_set = frame[frame.date.isin(dates[:cut])].copy()
    test_set = frame[frame.date.isin(dates[cut:])].copy()
    if train_set.won.nunique() < 2 or test_set.won.nunique() < 2:
        return {"status": "INSUFFICIENT_CLASSES", "reason": "Chronological split lacks both outcomes."}

    from sklearn.compose import ColumnTransformer
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, roc_auc_score, log_loss
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    from joblib import dump

    for d in (train_set, test_set):
        d["news_text"] = d["reason"].fillna("") + " " + d["news_summary"].fillna("")
        d["rank"] = pd.to_numeric(d["rank"], errors="coerce")
        d["source_count"] = pd.to_numeric(d["source_count"], errors="coerce")
        d["news_age_hours"] = pd.to_numeric(d["news_age_hours"], errors="coerce")

    features = ColumnTransformer([
        ("text", TfidfVectorizer(max_features=1000, min_df=2, ngram_range=(1,2)), "news_text"),
        ("side", OneHotEncoder(handle_unknown="ignore"), ["side"]),
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="median")),
                              ("scale", StandardScaler())]),
         ["rank", "source_count", "news_age_hours"]),
    ])
    model = Pipeline([("features", features),
                      ("classifier", LogisticRegression(max_iter=2000, C=0.1))])
    cols = ["news_text", "side", "rank", "source_count", "news_age_hours"]
    model.fit(train_set[cols], train_set.won)
    probs = model.predict_proba(test_set[cols])[:, 1]
    baseline = float(train_set.won.mean())
    baseline_prob = [baseline] * len(test_set)
    metrics = {
        "status": "CHALLENGER_ONLY_NOT_DEPLOYED",
        "trained_at_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
        "train_rows": int(len(train_set)), "test_rows": int(len(test_set)),
        "train_last_date": dates[cut-1], "test_first_date": dates[cut],
        "holdout_brier": float(brier_score_loss(test_set.won, probs)),
        "baseline_brier": float(brier_score_loss(test_set.won, baseline_prob)),
        "holdout_logloss": float(log_loss(test_set.won, probs, labels=[0,1])),
        "baseline_logloss": float(log_loss(test_set.won, baseline_prob, labels=[0,1])),
        "holdout_auc": float(roc_auc_score(test_set.won, probs)),
        "promotion_allowed": False,
        "warning": "Selected-stock sample only; not an unbiased stock-discovery model. No broker connectivity."
    }
    output.mkdir(parents=True, exist_ok=True)
    dump(model, output / "challenger.joblib")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, default=ROOT / "learning/data/trades.csv")
    p.add_argument("--out", type=Path, default=ROOT / "learning/out")
    args = p.parse_args()
    print(json.dumps(train(args.csv, args.out), indent=2))


if __name__ == "__main__":
    main()
