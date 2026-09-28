"""Test-only sensor/time boundary for the real Edge main loop.

Runs inside the pinned Edge image. The application formatter, SQLite spool,
HTTP acknowledgement logic and MQTT publisher are not replaced.
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src import main as edge  # type: ignore[import-not-found]
from src.config import load_config  # type: ignore[import-not-found]

COMMANDS: queue.Queue = queue.Queue(maxsize=64)
CURRENT: dict = {}
FORMAT = edge.format_payload
DB = Path("/data/spool.sqlite3")


def collect(settings):
    global CURRENT
    CURRENT = COMMANDS.get(timeout=600)
    return {
        "pod_1": {"soil": {"soil_moisture_percent": 42.0, "soil_temperature_c": 22.0}},
        "pod_2": None,
        "shared": {
            "air": {
                "air_temperature_c": CURRENT.get("temperature", 25.0),
                "air_humidity_percent": CURRENT.get("humidity", 55.0),
            },
            "light": {"light_lux": 12000.0},
        },
        "system_health": {},
    }


def format_sample(settings, readings):
    return FORMAT(settings, readings, datetime.fromisoformat(CURRENT["timestamp"].replace("Z", "+00:00")))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, code, value):
        body = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if self.path != "/sample" or not 0 < length <= 1024:
            return self.respond(400, {})
        try:
            sample = json.loads(self.rfile.read(length))
            if set(sample) - {"timestamp", "temperature", "humidity"}:
                raise ValueError("unknown field")
            timestamp = datetime.fromisoformat(sample["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("UTC required")
            COMMANDS.put_nowait(sample)
        except (ValueError, KeyError, queue.Full):
            return self.respond(400, {})
        return self.respond(202, {"queued": True})

    def do_GET(self):
        if self.path != "/records":
            return self.respond(404, {})
        if not DB.exists():
            return self.respond(503, {})
        try:
            with sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5) as db:
                db.row_factory = sqlite3.Row
                rows = db.execute(
                    "SELECT record_id,observed_at,state,attempt_count,payload_json FROM records "
                    "ORDER BY sequence LIMIT 256"
                ).fetchall()
                result = [dict(row) for row in rows]
                for row in result:
                    row["payload"] = json.loads(row.pop("payload_json"))
            self.respond(200, result)
        except sqlite3.Error:
            self.respond(503, {})


if __name__ == "__main__":
    settings = load_config()
    if not settings.mock_sensors or settings.camera_enabled or settings.photo_upload_enabled:
        raise SystemExit("fake sensors and disabled camera required")
    edge.collect_readings = collect
    edge.format_payload = format_sample
    server = ThreadingHTTPServer(("0.0.0.0", 8091), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    edge.run(settings)
