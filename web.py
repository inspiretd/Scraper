import asyncio
import sys
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok", "bot": "co_worker"}

@app.get("/health")
async def health():
    return {"status": "alive"}

async def start_bot():
    sys.argv = ["co_worker.py"]
    import co_worker
    await co_worker.main()

@app.on_event("startup")
async def startup():
    asyncio.create_task(start_bot())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
