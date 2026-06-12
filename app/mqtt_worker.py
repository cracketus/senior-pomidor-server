from __future__ import annotations

import json
import logging
import signal
import sys
from threading import Event

import paho.mqtt.client as mqtt

from app.config import settings
from app.db import SessionLocal
from app.services import persist_telemetry
from app.validation import ValidationError, validate_telemetry_payload, validate_topic_device

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
stop_event = Event()


def on_connect(
    client: mqtt.Client,
    _userdata: object,
    _flags: object,
    reason_code: int,
    _properties: object = None,
) -> None:
    if reason_code != 0:
        logger.error("MQTT connect failed: %s", reason_code)
        return
    topic = f"{settings.mqtt_topic_prefix}/+/telemetry"
    client.subscribe(topic, qos=1)
    logger.info("Subscribed to %s", topic)


def on_message(_client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        device_id, _timestamp = validate_telemetry_payload(payload)
        validate_topic_device(message.topic, settings.mqtt_topic_prefix, device_id)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        logger.warning("Rejected MQTT telemetry on %s: %s", message.topic, exc)
        return

    with SessionLocal() as db:
        try:
            event = persist_telemetry(db, payload, source="mqtt")
        except Exception:
            logger.exception("Failed to persist MQTT telemetry on %s", message.topic)
            return
    logger.info("Accepted MQTT telemetry event_id=%s topic=%s", event.id, message.topic)


def main() -> int:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()
        client.disconnect()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
    client.loop_start()
    stop_event.wait()
    client.loop_stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
