"""Render.com health-check server — keeps the bot alive 24/7"""
import asyncio
import os
from fastapi import FastAPI
import uvicorn

app = FastAPI()

bot_task = None

@app.get("/")
@app.get("/health")
async def health():
    return {"status": "alive", "bot": "co_worker"}

@app.on_event("startup")
async def startup():
    global bot_task
    import co_worker
    bot_task = asyncio.create_task(co_worker.main())
    print("[Web] Bot started in background")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
