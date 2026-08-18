# Unit tests for FraudModelService.
# Verifies model loading, feature engineering, and prediction output shape.

import pytest
from app.model import FraudModelService


@pytest.fixture(scope="module")
def svc() -> FraudModelService:
    service = FraudModelService()
    service.load()
    return service


def test_model_loads(svc):
    assert svc.is_loaded


def test_model_version(svc):
    assert svc.model_version != "unknown"
    assert "xgb" in svc.model_version


def test_predict_returns_probability(svc):
    prob = svc.predict(
        amount=1500.0,
        category="shopping_net",
        state="CA",
        transaction_hour=3,
        distance_from_last_transaction=900.0,
        device_type="mobile",
    )
    assert isinstance(prob, float)
    assert 0.0 <= prob <= 1.0


def test_predict_legit_transaction_low_prob(svc):
    # Daytime, low amount, short distance → model should give low fraud prob
    prob = svc.predict(
        amount=25.0,
        category="grocery_pos",
        state="TX",
        transaction_hour=14,
        distance_from_last_transaction=2.0,
        device_type="desktop",
    )
    assert prob < 0.8, f"Expected low fraud prob for legit transaction, got {prob}"


def test_predict_suspicious_transaction_high_prob(svc):
    # High amount, 3am, large distance, mobile, online → should trigger high fraud
    prob = svc.predict(
        amount=8000.0,
        category="misc_net",
        state="NY",
        transaction_hour=3,
        distance_from_last_transaction=5000.0,
        device_type="mobile",
    )
    assert prob > 0.5, f"Expected high fraud prob for suspicious transaction, got {prob}"


@pytest.mark.parametrize("device", ["mobile", "desktop", "tablet"])
def test_predict_all_device_types(svc, device):
    prob = svc.predict(
        amount=100.0, category="food_dining", state="CA",
        transaction_hour=12, distance_from_last_transaction=5.0, device_type=device,
    )
    assert 0.0 <= prob <= 1.0


def test_predict_unknown_category_handled(svc):
    # Unknown category should fall back to index 0, not crash
    prob = svc.predict(
        amount=200.0, category="unknown_category_xyz", state="CA",
        transaction_hour=10, distance_from_last_transaction=10.0, device_type="mobile",
    )
    assert 0.0 <= prob <= 1.0
