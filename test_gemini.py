import os, json, urllib.request

api_key = ''
with open('.env') as f:
    for line in f:
        if line.startswith('EMBED_API_KEY=') or line.startswith('OPENAI_API_KEY='):
            api_key = line.strip().split('=', 1)[1]
            if api_key and '여기에_발급받은' not in api_key:
                break

url = 'https://generativelanguage.googleapis.com/v1beta/openai/embeddings'
req = urllib.request.Request(url, method='POST')
req.add_header('Content-Type', 'application/json')
req.add_header('Authorization', f'Bearer {api_key}')
data = json.dumps({'model': 'text-embedding-004', 'input': 'hello'}).encode()
try:
    with urllib.request.urlopen(req, data=data) as response:
        print('SUCCESS:', response.status)
except Exception as e:
    print('ERROR:', e)
    if hasattr(e, 'read'):
        print('BODY:', e.read().decode())
