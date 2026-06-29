from __future__ import annotations

import json
import logging
import signal
import sys
from threading import Event

import paho.mqtt.client as mqtt

from app.config import settings
from app.db import SessionLocal
from app.logging_config import configure_logging
from app.services import persist_telemetry
from app.validation import ValidationError, validate_telemetry_payload, validate_topic_device
from app.worker_health import write_worker_health

configure_logging()
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
        write_worker_health("connect_failed", reason_code=str(reason_code))
        return
    topic = f"{settings.mqtt_topic_prefix}/+/telemetry"
    result, message_id = client.subscribe(topic, qos=1)
    if result != mqtt.MQTT_ERR_SUCCESS:
        logger.error("MQTT subscribe failed topic=%s result=%s", topic, result)
        write_worker_health("subscribe_failed", topic=topic, result=result)
        return
    write_worker_health("healthy", topic=topic, subscribe_mid=message_id)
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
    write_worker_health("healthy", last_message_topic=message.topic)
    logger.info("Accepted MQTT telemetry event_id=%s topic=%s", event.id, message.topic)


def main() -> int:
    stop_event.clear()
    write_worker_health("starting")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if settings.mqtt_username:
        client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    client.on_connect = on_connect
    client.on_message = on_message

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()
        client.disconnect()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    if not connect_with_retry(client, stop_event):
        write_worker_health("stopped")
        return 0
    client.loop_start()
    while not stop_event.wait(30):
        write_worker_health("healthy")
    client.loop_stop()
    write_worker_health("stopped")
    return 0


def connect_with_retry(
    client: mqtt.Client,
    stop: Event,
    *,
    initial_delay_seconds: float = 1.0,
    max_delay_seconds: float = 30.0,
) -> bool:
    delay = initial_delay_seconds
    while not stop.is_set():
        try:
            client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
            return True
        except OSError:
            write_worker_health("connect_failed", host=settings.mqtt_host, port=settings.mqtt_port)
            logger.exception(
                "MQTT broker connection failed host=%s port=%s; retrying in %.1fs",
                settings.mqtt_host,
                settings.mqtt_port,
                delay,
            )
            stop.wait(delay)
            delay = min(delay * 2, max_delay_seconds)
        except Exception:
            write_worker_health("connect_failed", host=settings.mqtt_host, port=settings.mqtt_port)
            logger.exception("Unexpected MQTT startup failure; retrying in %.1fs", delay)
            stop.wait(delay)
            delay = min(delay * 2, max_delay_seconds)
    return False


if __name__ == "__main__":
    sys.exit(main())
