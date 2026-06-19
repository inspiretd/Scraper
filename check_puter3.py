import requests, re

r = requests.get('https://js.puter.com/v2/')
text = r.text

# Search for the chat/send message endpoint
patterns = ['ai-chat', 'chat-completion', 'puterai/chat/send', 'puterai/chat/complet', 'driver', 'drivers.call']
for p in patterns:
    idx = text.find(p)
    count = 0
    while idx >= 0 and count < 5:
        start = max(0, idx - 100)
        end = min(len(text), idx + 300)
        snippet = text[start:end]
        print(f'--- "{p}" at {idx} ---')
        print(snippet)
        print()
        idx = text.find(p, idx + 1)
        count += 1
