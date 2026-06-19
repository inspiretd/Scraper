import requests, json

r = requests.post('https://api.puter.com/drivers/call',
    json={
        'interface': 'puter-chat-completion',
        'driver': 'ai-chat',
        'method': 'complete',
        'args': {
            'messages': [{'role': 'user', 'content': 'Say hello in one word'}],
            'model': 'gpt-4o-mini'
        },
        'test_mode': False
    },
    headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6InYyIn0.eyJ0IjoiZ3VpIiwidiI6IjIiLCJ1IjoiKzRDTmJYSVNSa0dwVU5nbHh4cEJqZz09Iiwic3UiOiIrNENOYlhJU1JrR3BVTmdseHhwQmpnPT0iLCJ1dSI6IldkdWJjMVhQUW1pZExsUytEbGdJU2c9PSIsImFpIjoiV2R1YmMxWFBRbWlkTGxTK0RsZ0lTZz09IiwiaWF0IjoxNzgxODY3MjE1fQ.-GP9fXbXXSlr1krEyv59W8MmInlIhYw60MU5pXqJLjM'
    },
    timeout=60)

print(f'Status: {r.status_code}')
print(f'Response: {r.text[:500]}')
