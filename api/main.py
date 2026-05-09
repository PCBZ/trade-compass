from fastapi import FastAPI

app = FastAPI(title="trade-compass API")


@app.get("/health")
def health():
    return {"status": "ok"}
