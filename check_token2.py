import requests

r = requests.get('https://js.puter.com/v2/')
text = r.text

# Search for localStorage getItem calls
idx = 0
count = 0
while count < 20:
    idx = text.find('localStorage', idx)
    if idx < 0:
        break
    start = max(0, idx - 30)
    end = min(len(text), idx + 200)
    print(f'--- at {idx} ---')
    print(text[start:end])
    print()
    idx += 1
    count += 1
