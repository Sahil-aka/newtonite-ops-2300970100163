from fastapi import FastAPI

app = FastAPI(
    title="Newtonite Operations Tracker",
    description="A team-based work tracking API for the Newtonite engineering challenge.",
    version="0.1.0",
)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Report that the API process is running."""
    return {"status": "ok"}
