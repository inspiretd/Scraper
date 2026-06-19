import requests, re, json

r = requests.get('https://js.puter.com/v2/')
text = r.text

# Search for API-related strings
patterns = ['api.puter.com', 'api_url', 'base_url', '/chat', 'endpoint', 'host', 'origin']
for p in patterns:
    idx = text.find(p)
    count = 0
    while idx >= 0 and count < 3:
        start = max(0, idx - 50)
        end = min(len(text), idx + 150)
        snippet = text[start:end]
        print(f'--- "{p}" at {idx} ---')
        print(snippet)
        print()
        idx = text.find(p, idx + 1)
        count += 1
