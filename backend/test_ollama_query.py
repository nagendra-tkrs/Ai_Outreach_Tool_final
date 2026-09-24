import httpx, json

prompt = 'Who are the key decision makers, executives, CEO, Managing Director, and leadership of Garware Technical Fibres Ltd? Return a JSON array of up to 6 executives with keys "name" and "role". Return JSON format: {"executives": [{"name": "...", "role": "..."}]}'
res = httpx.post('http://127.0.0.1:11434/api/chat', json={
    'model': 'qwen2.5:1.5b',
    'messages': [{'role': 'user', 'content': prompt}],
    'stream': False,
    'format': 'json'
}, timeout=30)
print('Status:', res.status_code)
print('Response:', res.json().get('message', {}).get('content'))
