"""Run this locally to generate a StringSession for Render deployment.
1. Set API_ID, API_HASH, PHONE as env vars or edit below
2. Run: python generate_session.py
3. Copy the output to STRING_SESSION env var on Render"""
import asyncio, os
from telethon import TelegramClient, sessions

async def main():
    api_id = int(os.environ.get("API_ID") or input("API_ID: "))
    api_hash = os.environ.get("API_HASH") or input("API_HASH: ")
    phone = os.environ.get("PHONE") or input("Phone: ")

    client = TelegramClient(sessions.StringSession(), api_id, api_hash)
    await client.start(phone=phone)
    me = await client.get_me()
    print(f"\nLogged in as: {me.first_name} (@{me.username})")
    print(f"\nYour STRING_SESSION:\n{client.session.save()}")
    print("\nCopy this to Render env vars. Press Ctrl+C to exit.")
    await client.run_until_disconnected()

asyncio.run(main())
