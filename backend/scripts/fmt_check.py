import sys, json, urllib.request, urllib.error, os
os.environ.setdefault("DB_HOST", "host.docker.internal")

def req(method, path, body=None):
    h = {"Content-Type": "application/json"}
    if body is not None: h.update({"Authorization": f"Bearer __PLACE__"})
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request("http://127.0.0.1:8000/api"+path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp: return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()

_, data = req("POST", "/auth/login", {"username": "admin", "password": "EvalShield@123"})
token = json.loads(data)["data"]["access_token"]

for ep in ["/cases?page=1&page_size=2", "/scenarios", "/datasets?page=1&page_size=2"]:
    r = urllib.request.Request(f"http://127.0.0.1:8000/api{ep}", headers={"Authorization":f"Bearer {token}"})
    with urllib.request.urlopen(r, timeout=10) as resp:
        body = resp.read().decode()
        parsed = json.loads(body)
        print(f"GET {ep} -> type(data)={type(parsed.get('data')).__name__}")
        print(f"  first key: {list(parsed.keys())}")
        if isinstance(parsed.get("data"), dict):
            print(f"  data keys: {list(parsed['data'].keys())}")
        elif isinstance(parsed.get("data"), list):
            print(f"  data list len: {len(parsed['data'])}")
        print()
