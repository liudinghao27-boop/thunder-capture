"""End-to-end API test — requires server running on localhost:8000"""
import urllib.request
import json

BASE = "http://localhost:8000"

def get(path):
    req = urllib.request.Request(f"{BASE}{path}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())

def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())

print("=== Thunder API Test ===")
print()

# 1. Root (returns HTML page, not JSON)
import urllib.request as ur
with ur.urlopen(f"{BASE}/", timeout=10) as r:
    html = r.read()
    print(f"  GET  /              → {r.status} ({len(html):,} bytes HTML)")

# 2. Health
try:
    status, data = get("/api/system/health")
    print(f"  GET  /api/system/health → {status}")
    for k, v in data.items():
        print(f"       {k}: {v}")
except Exception as e:
    print(f"  GET  /api/system/health → ERROR: {e}")

# 3. Register (if no users)
try:
    status, data = post("/api/auth/register", {
        "username": "admin",
        "password": "admin123"
    })
    print(f"  POST /api/auth/register → {status}: {data.get('message', data)}")
except Exception as e:
    err = str(e)
    if "409" in err or "exists" in err.lower():
        print(f"  POST /api/auth/register → 409 (already exists, OK)")
    else:
        print(f"  POST /api/auth/register → ERROR: {err[:100]}")

# 4. Login
try:
    status, data = post("/api/auth/login", {
        "username": "admin",
        "password": "admin123"
    })
    token = data.get("access_token", "")
    print(f"  POST /api/auth/login    → {status}: token={'OK' if token else 'MISSING'}")
except Exception as e:
    print(f"  POST /api/auth/login    → ERROR: {str(e)[:100]}")
    token = ""

# 5. Industries
try:
    status, data = get("/api/industries")
    print(f"  GET  /api/industries    → {status}: {len(data) if isinstance(data, list) else '?'} industries")
except Exception as e:
    print(f"  GET  /api/industries    → ERROR: {str(e)[:100]}")

# 6. Dashboard
if token:
    try:
        req = urllib.request.Request(f"{BASE}/api/dashboard/state")
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=10) as r:
            ds = json.loads(r.read())
        print(f"  GET  /api/dashboard/state → {r.status}")
        print(f"       industries: {ds.get('project', {}).get('industry_count', '?')}")
        print(f"       devices:    {ds.get('device_matrix', {}).get('total', '?')}")
        print(f"       leads:      pending={ds.get('lead_inventory', {}).get('pending', '?')}")
    except Exception as e:
        print(f"  GET  /api/dashboard/state → ERROR: {str(e)[:100]}")

print()
print("=== API TEST COMPLETE ===")
