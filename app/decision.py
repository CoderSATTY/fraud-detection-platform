# Decision engine — maps XGBoost fraud probability to a business decision.
# Thresholds are read from environment variables so they can be tuned
# via Kubernetes ConfigMap without rebuilding the image.

import os

# Load thresholds from env (set in K8s ConfigMap or docker-compose)
REVIEW_THRESHOLD = float(os.getenv("REVIEW_THRESHOLD", "0.60"))
BLOCK_THRESHOLD  = float(os.getenv("BLOCK_THRESHOLD", "0.90"))


def make_decision(fraud_probability: float) -> str:
    """
    Apply business thresholds:
      ≥ BLOCK_THRESHOLD  → BLOCK
      ≥ REVIEW_THRESHOLD → REVIEW
      otherwise          → APPROVE
    """
    if fraud_probability >= BLOCK_THRESHOLD:
        return "BLOCK"
    if fraud_probability >= REVIEW_THRESHOLD:
        return "REVIEW"
    return "APPROVE"


def get_thresholds() -> dict[str, float]:
    return {"review": REVIEW_THRESHOLD, "block": BLOCK_THRESHOLD}
