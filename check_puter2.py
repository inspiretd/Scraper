import requests, re

r = requests.get('https://js.puter.com/v2/')
text = r.text

# Search for chat endpoint patterns
patterns = ['puterai/chat', '/v2/puterai', 'ai/chat', 'chat/complet']
for p in patterns:
    idx = text.find(p)
    count = 0
    while idx >= 0 and count < 5:
        start = max(0, idx - 80)
        end = min(len(text), idx + 200)
        snippet = text[start:end]
        print(f'--- "{p}" at {idx} ---')
        print(snippet)
        print()
        idx = text.find(p, idx + 1)
        count += 1

# Also look for "chat" function definition
idx = text.find('puterai/chat')
if idx >= 0:
    start = max(0, idx - 200)
    end = min(len(text), idx + 500)
    print('=== FULL CONTEXT around puterai/chat ===')
    print(text[start:end])
