import requests

r = requests.get('https://js.puter.com/v2/')
text = r.text

# Find declarations of bs and fs (the token key variables)
for var in ['bs=', 'fs=', 'bs =', 'fs =', 'const bs', 'const fs', 'let bs', 'let fs']:
    idx = text.find(var)
    if idx >= 0:
        start = max(0, idx - 20)
        end = min(len(text), idx + 100)
        print(f'--- "{var}" at {idx} ---')
        print(text[start:end])
        print()
