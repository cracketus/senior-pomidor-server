"""Internal-only bounded lost-ACK/outage proxy. Never accepts an upstream URL."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LOCK = threading.Lock()
STATE: dict[str, Any] = {"mode": "pass", "lost": 0, "accepted": 0, "duplicate": 0, "attempts": 0}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        with LOCK:
            self.respond(200, dict(STATE))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 65536:
            return self.respond(413, {})
        data = self.rfile.read(length)
        if self.path == "/control":
            try:
                mode = json.loads(data)["mode"]
                if mode not in {"pass", "outage", "lost-ack"}:
                    raise ValueError("mode")
                with LOCK:
                    STATE["mode"] = mode
                return self.respond(200, {"mode": mode})
            except (ValueError, KeyError):
                return self.respond(400, {})
        if self.path != "/telemetry":
            return self.respond(404, {})
        with LOCK:
            STATE["attempts"] += 1
            mode = STATE["mode"]
        if mode == "outage":
            return self.respond(503, {})
        conn = http.client.HTTPConnection("api", 8000, timeout=5)
        try:
            conn.request("POST", "/api/v1/edge/telemetry", data, {"Content-Type": "application/json"})
            response = conn.getresponse()
            body = json.loads(response.read(65536))
            with LOCK:
                status = body.get("status")
                if status in {"accepted", "duplicate"}:
                    STATE[status] += 1
                    if STATE["mode"] == "lost-ack":
                        STATE["lost"] += 1
                        # Keep dropping until the controller has proved persistence + pending.
                        self.close_connection = True
                        return None
            self.respond(response.status, body)
        except (OSError, ValueError, http.client.HTTPException):
            self.respond(503, {})
        finally:
            conn.close()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
