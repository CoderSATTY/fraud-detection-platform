# FraudModelService — loads the trained XGBoost model once at startup
# and exposes a predict() method used by the FastAPI /predict endpoint.
# Uses singleton pattern so model.pkl is read from disk exactly once per pod.

from __future__ import annotations
import json
import pickle
from pathlib import Path
from typing import Tuple

import numpy as np

from app.features import FEATURE_NAMES, build_feature_vector

_ML_DIR    = Path(__file__).parent.parent / "ml"
_MODEL_PATH = _ML_DIR / "model.pkl"
_META_PATH  = _ML_DIR / "model_meta.json"


class FraudModelService:
    _instance: "FraudModelService | None" = None

    def __new__(cls) -> "FraudModelService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def load(self) -> None:
        """Load model.pkl from disk. Called once during FastAPI lifespan startup."""
        if self._loaded:
            return
        if not _MODEL_PATH.exists():
            raise FileNotFoundError(
                f"model.pkl not found at {_MODEL_PATH}. Run `python ml/train.py` first."
            )
        with open(_MODEL_PATH, "rb") as f:
            self._model = pickle.load(f)

        self._version = "xgb-v1"
        self._model_type = "XGBoost Classifier"
        if _META_PATH.exists():
            with open(_META_PATH) as f:
                meta = json.load(f)
            self._version   = meta.get("model_version", self._version)
            self._model_type = meta.get("model_type", self._model_type)

        self._loaded = True

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def model_version(self) -> str:
        return self._version if self._loaded else "unknown"

    @property
    def model_type(self) -> str:
        return self._model_type if self._loaded else "unknown"

    def predict(
        self,
        amount: float,
        category: str,
        state: str,
        transaction_hour: int,
        distance_from_last_transaction: float,
        device_type: str,
    ) -> float:
        """
        Run feature engineering then XGBoost inference.
        Returns fraud_probability in [0.0, 1.0].
        """
        if not self._loaded:
            raise RuntimeError("FraudModelService not loaded. Call .load() first.")

        # Build the (1, 8) feature vector
        X = build_feature_vector(
            amount=amount,
            category=category,
            state=state,
            transaction_hour=transaction_hour,
            distance_from_last_transaction=distance_from_last_transaction,
            device_type=device_type,
        )

        # predict_proba returns [[p_legit, p_fraud]]; we want p_fraud
        prob = float(self._model.predict_proba(X)[0, 1])
        return round(prob, 4)

fraud_model = FraudModelService()
