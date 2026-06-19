import requests, json

api = "https://api.puter.com"

# Try drivers/call without auth
payload = {
    "interface": "puter-chat-completion",
    "driver": "ai-chat",
    "method": "complete",
    "args": {
        "messages": [{"role": "user", "content": "Say hello in one word"}],
        "model": "gpt-4o-mini"
    },
    "test_mode": False
}

headers = {"Content-Type": "application/json"}
r = requests.post(f"{api}/drivers/call", json=payload, headers=headers)
print(f"Status: {r.status_code}")
print(f"Response: {r.text[:500]}")

# Also try models listing without auth
payload2 = {
    "interface": "puter-chat-completion",
    "driver": "ai-chat",
    "method": "models",
    "args": {}
}
r2 = requests.post(f"{api}/drivers/call", json=payload2, headers=headers)
print(f"\nModels status: {r2.status_code}")
print(f"Models response: {r2.text[:500]}")
