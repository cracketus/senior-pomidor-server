from fastapi import FastAPI

from app.api import router

app = FastAPI(title="Senior Pomidor Core Server", version="0.1.0")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
