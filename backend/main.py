from fastapi import FastAPI

app = FastAPI(title="SciCopilot Backend")


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "SciCopilot Backend",
        "version": "v0.1"
    }