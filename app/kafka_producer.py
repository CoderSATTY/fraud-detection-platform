# Async Kafka producer for the fraud-transactions topic.
# The prediction HTTP response is returned immediately; Kafka publish runs
# concurrently via asyncio.create_task() and never blocks the client.
# Set KAFKA_ENABLED=true in K8s ConfigMap to activate (Phase 7).

from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

KAFKA_ENABLED   = os.getenv("KAFKA_ENABLED", "false").lower() == "true"
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC     = os.getenv("KAFKA_TOPIC", "fraud-transactions")  # updated topic name

_producer = None


async def _get_producer():
    global _producer
    if _producer is None:
        try:
            from aiokafka import AIOKafkaProducer
            _producer = AIOKafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await _producer.start()
        except Exception as exc:
            logger.warning("Kafka producer init failed: %s", exc)
            _producer = None
    return _producer


async def publish_fraud_event(
    transaction_id: str,
    fraud_probability: float,
    decision: str,
    model_version: str,
) -> bool:
    """Publish one fraud decision event to Kafka. Returns True if sent, False otherwise."""
    if not KAFKA_ENABLED:
        return False
    event = {
        "transaction_id": transaction_id,
        "fraud_probability": fraud_probability,
        "decision": decision,
        "model_version": model_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        producer = await _get_producer()
        if producer is not None:
            await producer.send_and_wait(KAFKA_TOPIC, value=event)
            return True
    except Exception as exc:
        logger.error("Kafka publish error: %s", exc)
    return False


async def close_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
