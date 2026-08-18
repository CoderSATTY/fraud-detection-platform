# Pydantic schemas for the fraud detection API.
# Defines the shape of incoming transactions and outgoing decisions.

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class TransactionRequest(BaseModel):
    # Raw transaction fields sent by the payment client
    transaction_id: str
    amount: float = Field(..., gt=0, description="Transaction amount in USD")
    category: str = Field(..., description="Merchant category (e.g. shopping_net)")
    state: str = Field(..., description="2-letter US state code")
    transaction_hour: int = Field(..., ge=0, le=23, description="Hour of day (0-23)")
    distance_from_last_transaction: float = Field(..., ge=0, description="Distance in km")
    device_type: str = Field(..., description="mobile | desktop | tablet")


class FraudResponse(BaseModel):
    # What gets returned to the client after model inference
    transaction_id: str
    fraud_probability: float = Field(..., ge=0.0, le=1.0)
    decision: Literal["APPROVE", "REVIEW", "BLOCK"]
    model_version: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    model_loaded: bool
    model_version: str


class ReadyResponse(BaseModel):
    ready: bool


class ModelInfoResponse(BaseModel):
    # Exposes metadata about the loaded model (useful for debugging/ops)
    model_version: str
    model_type: str
    features: list[str]
    thresholds: dict[str, float]
