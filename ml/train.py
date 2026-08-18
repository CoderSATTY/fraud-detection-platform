# XGBoost fraud detection model training script.
# Uses synthetic transaction data that mimics real credit-card fraud patterns:
#   - Fraud transactions: high amounts, late night, large geo-distance, mobile device
#   - Legitimate transactions: low amounts, daytime, short distance
#
# Imports feature engineering from app/features.py so training and inference
# use IDENTICAL feature logic — the most common source of training-serving skew.
#
# Run: python ml/train.py
# Output: ml/model.pkl + ml/model_meta.json

from __future__ import annotations
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

# Add project root to path so we can import app.features
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.features import CATEGORIES, DEVICES, STATES, build_feature_matrix

MODEL_VERSION = "xgb-v1"
MODEL_DIR  = Path(__file__).parent
MODEL_PATH = MODEL_DIR / "model.pkl"
META_PATH  = MODEL_DIR / "model_meta.json"


def _generate_transactions(n: int = 60_000, fraud_rate: float = 0.02, seed: int = 42) -> pd.DataFrame:
    """
    Build a synthetic fraud dataset with realistic class imbalance (~2% fraud).
    Fraud patterns baked in:
      - Much higher amounts
      - Late-night hours (0-5 or 22-23)
      - Large distances from last transaction
      - Online categories (shopping_net, misc_net)
      - Predominantly mobile device
    """
    rng = np.random.RandomState(seed)
    n_fraud = int(n * fraud_rate)
    n_legit = n - n_fraud

    legit = pd.DataFrame({
        "amount":                         rng.exponential(75, n_legit).clip(1, 400),
        "category":                       rng.choice(CATEGORIES, n_legit),
        "state":                          rng.choice(STATES, n_legit),
        "transaction_hour":               rng.randint(7, 22, n_legit),     # business hours
        "distance_from_last_transaction": rng.exponential(25, n_legit).clip(0, 150),
        "device_type":                    rng.choice(DEVICES, n_legit, p=[0.35, 0.55, 0.10]),
        "label":                          0,
    })

    fraud = pd.DataFrame({
        "amount":                         rng.exponential(1400, n_fraud).clip(200, 12_000),
        "category":                       rng.choice(["shopping_net", "misc_net", "entertainment", "travel"], n_fraud),
        "state":                          rng.choice(STATES, n_fraud),
        "transaction_hour":               rng.choice(list(range(0, 6)) + list(range(22, 24)), n_fraud),
        "distance_from_last_transaction": rng.exponential(600, n_fraud).clip(100, 8_000),
        "device_type":                    rng.choice(DEVICES, n_fraud, p=[0.72, 0.20, 0.08]),
        "label":                          1,
    })

    df = pd.concat([legit, fraud], ignore_index=True)
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


def train() -> None:
    print("Generating synthetic fraud dataset ...")
    df = _generate_transactions()

    n_fraud = df["label"].sum()
    print(f"Dataset: {len(df):,} transactions | {n_fraud:,} fraud ({n_fraud/len(df)*100:.1f}%)")

    # Build feature matrix using the same logic as inference (no skew)
    X = build_feature_matrix(df)
    y = df["label"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    # scale_pos_weight handles class imbalance — tells XGBoost to weight
    # fraud samples more heavily (ratio of negatives to positives)
    pos_weight = (y_train == 0).sum() / (y_train == 1).sum()

    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=pos_weight,  # compensate for class imbalance
        random_state=42,
        eval_metric="logloss",
        early_stopping_rounds=20,
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    print("\nClassification Report (test set):")
    print(classification_report(y_test, y_pred, target_names=["Legit", "Fraud"]))
    print(f"ROC-AUC: {roc_auc_score(y_test, y_prob):.4f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)

    from app.features import FEATURE_NAMES
    meta = {
        "model_version":   MODEL_VERSION,
        "model_type":      "XGBoost Classifier (Gradient Boosted Decision Trees)",
        "dataset":         "Synthetic credit-card fraud (60k samples, 2% fraud rate)",
        "features":        FEATURE_NAMES,
        "n_estimators":    model.n_estimators,
        "n_train":         int(len(X_train)),
        "n_test":          int(len(X_test)),
        "roc_auc":         round(float(roc_auc_score(y_test, y_prob)), 4),
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nModel saved  → {MODEL_PATH}")
    print(f"Metadata     → {META_PATH}")
    print(f"Version      : {MODEL_VERSION}")


if __name__ == "__main__":
    train()
