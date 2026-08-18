# Feature engineering pipeline.
# Converts raw transaction fields into the numeric feature vector the XGBoost model expects.
# Both ml/train.py and app/model.py import from here so training and inference
# always use identical feature logic.

from __future__ import annotations
import numpy as np

# All allowed categorical values — order defines the label encoding.
# Unknown values at inference time fall back to index 0.
CATEGORIES = [
    "shopping_net", "grocery_pos", "gas_transport", "entertainment",
    "food_dining", "personal_care", "health_fitness", "travel",
    "kids_pets", "misc_net", "home", "shopping_pos", "misc_pos",
]
STATES = [
    "CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI",
    "NJ", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI", "CO",
]
DEVICES = ["mobile", "desktop", "tablet"]

# Names must match the column order built in build_feature_vector()
FEATURE_NAMES = [
    "log_amount",
    "category_enc",
    "state_enc",
    "transaction_hour",
    "log_distance",
    "device_enc",
    "is_night",
    "is_high_amount",
]


def _encode(value: str, options: list[str]) -> int:
    """Label-encode a string; return 0 for unseen categories."""
    try:
        return options.index(value)
    except ValueError:
        return 0


def build_feature_vector(
    amount: float,
    category: str,
    state: str,
    transaction_hour: int,
    distance_from_last_transaction: float,
    device_type: str,
) -> np.ndarray:
    """
    Produce a (1, 8) float32 array for a single transaction.
    Called at inference time — must be fast and stateless.
    """
    return np.array([[
        np.log1p(amount),                                               # log_amount
        _encode(category, CATEGORIES),                                  # category_enc
        _encode(state, STATES),                                         # state_enc
        transaction_hour,                                               # transaction_hour
        np.log1p(distance_from_last_transaction),                       # log_distance
        _encode(device_type, DEVICES),                                  # device_enc
        int(transaction_hour < 6 or transaction_hour > 22),             # is_night
        int(amount > 500),                                              # is_high_amount
    ]], dtype=np.float32)


def build_feature_matrix(df) -> np.ndarray:
    """
    Vectorised version of build_feature_vector used during model training.
    Takes a pandas DataFrame with all transaction columns.
    """
    import pandas as pd

    X = pd.DataFrame({
        "log_amount":       np.log1p(df["amount"]),
        "category_enc":     df["category"].map(lambda x: _encode(x, CATEGORIES)),
        "state_enc":        df["state"].map(lambda x: _encode(x, STATES)),
        "transaction_hour": df["transaction_hour"],
        "log_distance":     np.log1p(df["distance_from_last_transaction"]),
        "device_enc":       df["device_type"].map(lambda x: _encode(x, DEVICES)),
        "is_night":         ((df["transaction_hour"] < 6) | (df["transaction_hour"] > 22)).astype(int),
        "is_high_amount":   (df["amount"] > 500).astype(int),
    })
    return X[FEATURE_NAMES].values.astype(np.float32)
