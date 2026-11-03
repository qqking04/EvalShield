import urllib.request, json
body = json.dumps({'username': 'admin', 'password': 'EvalShield@123'}).encode()
req = urllib.request.Request('http://localhost:8000/api/auth/login', data=body, headers={'Content-Type':'application/json'})
token = json.loads(urllib.request.urlopen(req).read())['data']['access_token']

def t(n, p):
    try:
        req = urllib.request.Request(f'http://localhost:8000{p}')
        req.add_header('Authorization', f'Bearer {token}')
        r = urllib.request.urlopen(req, timeout=5)
        d = json.loads(r.read())
        items = 0
        if isinstance(d.get('data'), dict):
            items = d['data'].get('total', len(d['data'].get('items', [])))
        elif isinstance(d.get('data'), list):
            items = len(d['data'])
        code = d.get('code', r.status)
        print(f'OK  [{n}] code={code} items={items}')
    except urllib.error.HTTPError as e:
        print(f'FAIL [{n}] HTTP {e.code}')
    except Exception as e:
        print(f'FAIL [{n}] {e.__class__.__name__}')

print('=== suites ===')
t('GET /api/suites', '/api/suites')
t('GET /api/projects/1/suites', '/api/projects/1/suites')
t('GET /api/suites/1', '/api/suites/1')

print()
print('=== scenarios (刚恢复) ===')
t('GET /api/scenarios', '/api/scenarios?page_size=10')
t('GET /api/scenarios/1', '/api/scenarios/1')

print()
print('=== dashboard trend ===')
t('GET /api/dashboard/trend', '/api/dashboard/trend')
