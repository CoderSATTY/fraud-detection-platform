# Integration tests for FastAPI fraud detection endpoints.
# Uses httpx AsyncClient against the ASGI app — no network required.

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.model import fraud_model

LEGIT_TXN = {
    "transaction_id": "txn_legit_001",
    "amount": 22.50,
    "category": "grocery_pos",
    "state": "TX",
    "transaction_hour": 14,
    "distance_from_last_transaction": 1.5,
    "device_type": "desktop",
}

SUSPICIOUS_TXN = {
    "transaction_id": "txn_fraud_001",
    "amount": 9500.00,
    "category": "shopping_net",
    "state": "CA",
    "transaction_hour": 3,
    "distance_from_last_transaction": 4500.0,
    "device_type": "mobile",
}


@pytest.fixture(scope="module", autouse=True)
def load_model():
    if not fraud_model.is_loaded:
        fraud_model.load()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["model_loaded"] is True


@pytest.mark.asyncio
async def test_ready_ok(client):
    r = await client.get("/ready")
    assert r.status_code == 200
    assert r.json()["ready"] is True


@pytest.mark.asyncio
async def test_model_info(client):
    r = await client.get("/model")
    assert r.status_code == 200
    data = r.json()
    assert "model_version" in data
    assert "features" in data
    assert "thresholds" in data
    assert "review" in data["thresholds"]
    assert "block" in data["thresholds"]


@pytest.mark.asyncio
async def test_predict_response_shape(client):
    r = await client.post("/predict", json=LEGIT_TXN)
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {"transaction_id", "fraud_probability", "decision", "model_version"}
    assert data["decision"] in {"APPROVE", "REVIEW", "BLOCK"}
    assert 0.0 <= data["fraud_probability"] <= 1.0


@pytest.mark.asyncio
async def test_predict_transaction_id_passthrough(client):
    r = await client.post("/predict", json=LEGIT_TXN)
    assert r.json()["transaction_id"] == LEGIT_TXN["transaction_id"]


@pytest.mark.asyncio
async def test_predict_legit_likely_approved(client):
    r = await client.post("/predict", json=LEGIT_TXN)
    # Low-risk transaction should not be blocked
    assert r.json()["decision"] != "BLOCK"


@pytest.mark.asyncio
async def test_predict_suspicious_high_probability(client):
    r = await client.post("/predict", json=SUSPICIOUS_TXN)
    assert r.json()["fraud_probability"] > 0.5


@pytest.mark.asyncio
async def test_predict_missing_field_422(client):
    r = await client.post("/predict", json={"transaction_id": "txn_001", "amount": 100.0})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_predict_negative_amount_422(client):
    bad = {**LEGIT_TXN, "amount": -10.0}
    r = await client.post("/predict", json=bad)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_predict_invalid_hour_422(client):
    bad = {**LEGIT_TXN, "transaction_hour": 25}
    r = await client.post("/predict", json=bad)
    assert r.status_code == 422
