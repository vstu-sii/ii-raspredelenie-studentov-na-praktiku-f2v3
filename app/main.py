from fastapi import FastAPI

app = FastAPI(title="ВКР-трекер", version="0.1.0")


@app.get("/")
def root() -> dict:
    return {
        "status": "ok",
        "service": "vkr-tracker",
        "message": "Hello world: прод жив с недели 1",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
