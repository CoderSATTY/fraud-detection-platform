# FastAPI application — Real-Time Credit Card Fraud Detection service.
# Exposes /predict, /health, /ready, /model, /metrics endpoints.
# Stateless by design: each pod loads the model independently,
# making it safe to run behind NGINX Ingress with multiple replicas.
#
# NOTE: This is a learning/demo system. It is NOT suitable for real
# financial decisions without proper validation and compliance controls.

from __future__ import annotations
import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

from app.decision import get_thresholds, make_decision
from app.features import FEATURE_NAMES
from app.kafka_producer import close_producer, publish_fraud_event
from app.model import fraud_model
from app.schemas import (
    FraudResponse,
    HealthResponse,
    ModelInfoResponse,
    ReadyResponse,
    TransactionRequest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Custom Prometheus metrics — these appear on /metrics alongside
# the auto-instrumented HTTP request count and latency from Instrumentator.
FRAUD_DECISIONS_TOTAL = Counter(
    "fraud_decisions_total", "Fraud decisions by outcome", ["decision"]
)
FRAUD_INFERENCE_LATENCY = Histogram(
    "fraud_inference_latency_seconds",
    "XGBoost inference latency",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25],
)
KAFKA_EVENTS_TOTAL = Counter(
    "kafka_fraud_events_produced_total", "Kafka events published to fraud-transactions"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: load model once per pod. Pod is not ready until this completes.
    logger.info("Loading XGBoost fraud model ...")
    try:
        fraud_model.load()
        logger.info("Model loaded — version=%s", fraud_model.model_version)
    except FileNotFoundError as exc:
        logger.error("FATAL: %s", exc)
    yield
    # Shutdown: gracefully close Kafka producer connection
    await close_producer()


app = FastAPI(
    title="Credit Card Fraud Detection API",
    description=(
        "Real-time fraud scoring using XGBoost. "
        "DEMO SYSTEM — not for production financial use."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow all origins in dev; restrict via NGINX Ingress in production
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Auto-instrument HTTP request count, latency, and error rate for Prometheus
Instrumentator().instrument(app).expose(app)


@app.get("/", tags=["Operations"])
async def root():
    return {"service": "Fraud Detection API", "version": fraud_model.model_version, "docs": "/docs"}


@app.get("/health", response_model=HealthResponse, tags=["Operations"])
async def health() -> HealthResponse:
    """Kubernetes liveness probe — confirms the pod process is alive."""
    loaded = fraud_model.is_loaded
    resp = HealthResponse(status="ok" if loaded else "degraded", model_loaded=loaded, model_version=fraud_model.model_version)
    if not loaded:
        raise HTTPException(status_code=503, detail=resp.model_dump())
    return resp


@app.get("/ready", response_model=ReadyResponse, tags=["Operations"])
async def ready() -> ReadyResponse:
    """Kubernetes readiness probe — pod only receives traffic once model is loaded."""
    ready = fraud_model.is_loaded
    if not ready:
        raise HTTPException(status_code=503, detail={"ready": False})
    return ReadyResponse(ready=True)


@app.get("/model", response_model=ModelInfoResponse, tags=["ML"])
async def model_info() -> ModelInfoResponse:
    """Returns metadata about the currently loaded model and active thresholds."""
    return ModelInfoResponse(
        model_version=fraud_model.model_version,
        model_type=fraud_model.model_type,
        features=FEATURE_NAMES,
        thresholds=get_thresholds(),
    )


@app.post("/predict", response_model=FraudResponse, tags=["ML"])
async def predict(body: TransactionRequest) -> FraudResponse:
    """
    Fraud detection pipeline:
      1. Pydantic validates the raw transaction.
      2. Feature engineering converts it to an 8-dim numeric vector.
      3. XGBoost returns fraud_probability.
      4. Decision engine applies thresholds → APPROVE / REVIEW / BLOCK.
      5. HTTP response is returned immediately (synchronous).
      6. Kafka event is published asynchronously (non-blocking).
    """
    if not fraud_model.is_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded.")

    # Time only the ML inference step for the Prometheus histogram
    start = time.perf_counter()
    fraud_prob = fraud_model.predict(
        amount=body.amount,
        category=body.category,
        state=body.state,
        transaction_hour=body.transaction_hour,
        distance_from_last_transaction=body.distance_from_last_transaction,
        device_type=body.device_type,
    )
    FRAUD_INFERENCE_LATENCY.observe(time.perf_counter() - start)

    decision = make_decision(fraud_prob)
    FRAUD_DECISIONS_TOTAL.labels(decision=decision).inc()

    logger.info(
        "predict | id=%s decision=%s prob=%.4f",
        body.transaction_id, decision, fraud_prob,
    )

    # Fire-and-forget Kafka publish — does NOT delay the HTTP response
    asyncio.create_task(_kafka_task(body.transaction_id, fraud_prob, decision))

    return FraudResponse(
        transaction_id=body.transaction_id,
        fraud_probability=fraud_prob,
        decision=decision,
        model_version=fraud_model.model_version,
    )


async def _kafka_task(transaction_id: str, fraud_prob: float, decision: str) -> None:
    """Background task: publish fraud event to Kafka without blocking HTTP."""
    try:
        published = await publish_fraud_event(
            transaction_id=transaction_id,
            fraud_probability=fraud_prob,
            decision=decision,
            model_version=fraud_model.model_version,
        )
        if published:
            KAFKA_EVENTS_TOTAL.inc()
    except Exception as exc:
        logger.error("Kafka task error: %s", exc)
