import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette import status

from app.api import router
from app.config import settings
from app.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

docs_url = "/docs" if settings.api_docs_enabled else None
redoc_url = "/redoc" if settings.api_docs_enabled else None
openapi_url = "/openapi.json" if settings.api_docs_enabled else None

app = FastAPI(
    title="Senior Pomidor Core Server",
    version="0.1.0",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)
app.include_router(router)


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.error("Unhandled database error", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "internal server error"},
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled application error", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "internal server error"},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Senior Pomidor Dashboard</title>
  <style>
    :root { color-scheme: light; font-family: Arial, sans-serif; background: #f4f6f5; color: #17201a; }
    body { margin: 0; }
    header { background: #18392b; color: #fff; padding: 16px 24px; display: flex; justify-content: space-between; gap: 16px; align-items: center; }
    h1 { font-size: 20px; margin: 0; font-weight: 700; }
    main { padding: 20px 24px; display: grid; gap: 20px; }
    section { background: #fff; border: 1px solid #dbe3dd; border-radius: 6px; padding: 16px; }
    h2 { font-size: 16px; margin: 0 0 12px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { border-bottom: 1px solid #e7ece8; padding: 8px; text-align: left; vertical-align: top; }
    th { color: #526157; font-weight: 600; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
    .photo { border: 1px solid #dbe3dd; border-radius: 6px; overflow: hidden; background: #fafcfb; }
    .photo img { display: block; width: 100%; aspect-ratio: 4 / 3; object-fit: cover; background: #e7ece8; }
    .photo div { padding: 8px; font-size: 12px; color: #526157; overflow-wrap: anywhere; }
    .muted { color: #526157; font-size: 13px; }
    .error { color: #8a1f11; }
    button { border: 1px solid #9eb0a5; background: #fff; border-radius: 6px; padding: 8px 12px; cursor: pointer; }
  </style>
</head>
<body>
  <header>
    <h1>Senior Pomidor Dashboard</h1>
    <button type="button" onclick="loadDashboard()">Refresh</button>
  </header>
  <main>
    <section>
      <h2>Devices</h2>
      <div id="devices" class="muted">Loading...</div>
    </section>
    <section>
      <h2>Latest Telemetry</h2>
      <div id="telemetry" class="muted">Loading...</div>
    </section>
    <section>
      <h2>Recent Photos</h2>
      <div id="photos" class="muted">Loading...</div>
    </section>
  </main>
  <script>
    async function getJson(path) {
      const response = await fetch(path);
      if (!response.ok) throw new Error(path + " returned " + response.status);
      return response.json();
    }
    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }
    function table(headers, rows) {
      if (!rows.length) return "<p class='muted'>No data yet.</p>";
      return "<table><thead><tr>" + headers.map(h => `<th>${esc(h)}</th>`).join("") + "</tr></thead><tbody>" +
        rows.map(row => "<tr>" + row.map(cell => `<td>${cell}</td>`).join("") + "</tr>").join("") +
        "</tbody></table>";
    }
    function metricSummary(readings) {
      return readings.map(reading => {
        const metrics = Object.entries(reading.metrics || {}).slice(0, 4).map(([key, value]) => `${esc(key)}: ${esc(value)}`).join("<br>");
        return `<strong>${esc(reading.pod_key)}</strong> (${reading.enabled ? "enabled" : "disabled"})<br>${metrics || "<span class='muted'>no metrics</span>"}`;
      }).join("<hr>");
    }
    function healthSummary(event) {
      const health = event.system_health || {};
      const core = health.rpi_core || {};
      const hardware = health.pod_1_hardware || {};
      const climate = hardware.box_climate || {};
      const metrics = [
        ["cpu_temp_c", core.cpu_temp_c],
        ["wifi_rssi_dbm", core.wifi_rssi_dbm],
        ["disk_usage_percent", core.disk_usage_percent],
        ["io_wait_percent", core.io_wait_percent],
        ["bus_voltage_v", hardware.bus_voltage_v],
        ["bus_current_ma", hardware.bus_current_ma],
        ["box_air_temp_c", climate.air_temp_c],
        ["box_air_humidity_percent", climate.air_humidity_percent],
      ].filter(([, value]) => value !== undefined && value !== null);
      const alerts = (event.health_alerts || []).map(alert => `<span class='error'>${esc(alert.message)}</span>`).join("<br>");
      const metricText = metrics.slice(0, 6).map(([key, value]) => `${esc(key)}: ${esc(value)}`).join("<br>");
      return [metricText, alerts].filter(Boolean).join("<hr>") || "<span class='muted'>unknown</span>";
    }
    async function loadDashboard() {
      try {
        const [devices, latest, photos] = await Promise.all([
          getJson("/api/v1/devices"),
          getJson("/api/v1/devices/latest"),
          getJson("/api/v1/photos/recent?limit=12")
        ]);
        document.getElementById("devices").innerHTML = table(
          ["Device", "First seen", "Last seen", "Last payload"],
          devices.map(d => [esc(d.device_id), esc(d.first_seen_at), esc(d.last_seen_at), esc(d.last_payload_at)])
        );
        document.getElementById("telemetry").innerHTML = table(
          ["Device", "Timestamp", "Source", "Plant", "System health"],
          latest.map(e => [esc(e.device_id), esc(e.timestamp_utc), esc(e.source), metricSummary(e.readings || []), healthSummary(e)])
        );
        document.getElementById("photos").innerHTML = photos.length
          ? `<div class="grid">${photos.map(p => `<article class="photo"><img src="/api/v1/photos/${encodeURIComponent(p.photo_id)}" alt=""><div>${esc(p.device_id)}<br>${esc(p.captured_at_utc)}<br>${esc(p.photo_id)}</div></article>`).join("")}</div>`
          : "<p class='muted'>No photos yet.</p>";
      } catch (error) {
        document.querySelector("main").innerHTML = `<section class="error">${esc(error.message)}</section>`;
      }
    }
    loadDashboard();
  </script>
</body>
</html>
"""
