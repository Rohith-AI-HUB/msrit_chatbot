import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import fetch_portal_data
from shared.logging import setup_logger

logger = setup_logger("parents-service")

app = FastAPI(title="MSRIT Parents Portal Service", version="1.0.0")


class FetchRequest(BaseModel):
    usn: str
    dob: str   # DD/MM/YYYY


@app.get("/health")
def health():
    return {"status": "healthy", "service": "parents-service"}


@app.post("/fetch")
async def fetch(request: FetchRequest):
    logger.info(f"Fetch request: USN={request.usn}")
    result = await fetch_portal_data(usn=request.usn.strip().upper(), dob=request.dob.strip())
    return result
