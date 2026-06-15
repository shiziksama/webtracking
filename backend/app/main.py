from fastapi import FastAPI

app = FastAPI(title="Web Tracking API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
