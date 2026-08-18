import os
import json
import asyncio
import logging
from aiokafka import AIOKafkaConsumer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "fraud-transactions")

async def consume():
    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="fraud-consumer-group",
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )
    await consumer.start()
    logging.info(f"Consumer started. Listening on {KAFKA_BOOTSTRAP} for topic '{KAFKA_TOPIC}'...")
    try:
        async for msg in consumer:
            decision = msg.value.get('decision')
            tx_id = msg.value.get('transaction_id')
            prob = msg.value.get('fraud_probability')
            
            if decision == 'BLOCK':
                logging.error(f"[ALERT] BLOCKED TRANSACTION: {tx_id} | Probability: {prob:.4f} | Triggering account lockout...")
            elif decision == 'REVIEW':
                logging.warning(f"[REVIEW] Suspicious transaction: {tx_id} | Routing to human review queue...")
            else:
                logging.info(f"[APPROVE] Clear transaction: {tx_id}")
    finally:
        await consumer.stop()

if __name__ == "__main__":
    asyncio.run(consume())
