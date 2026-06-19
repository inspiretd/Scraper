import requests, re

r = requests.get('https://js.puter.com/v2/')
text = r.text

# Search for localStorage token key
patterns = ['token', 'authToken', 'localStorage', 'getItem']
for p in patterns:
    idx = text.find(p)
    count = 0
    while idx >= 0 and count < 8:
        start = max(0, idx - 40)
        end = min(len(text), idx + 120)
        snippet = text[start:end]
        if any(kw in snippet for kw in ['token', 'auth', 'storage', 'puter_token']):
            print(f'--- "{p}" at {idx} ---')
            print(snippet)
            print()
        idx = text.find(p, idx + 1)
        count += 1
