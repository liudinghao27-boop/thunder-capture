"""End-to-end API test — requires server running on localhost:8000"""

import json
import urllib.request
import urllib.request as ur

BASE = "http://localhost:8000"


def _request(path, headers=None):
    req = urllib.request.Request(f"{BASE}{path}")
    headers = headers or {}
    for key, value in headers.items():
        req.add_header(key, value)
    return req


def get(path, headers=None):
    req = _request(path, headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


def post(path, data, headers=None):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=body, headers={"Content-Type": "application/json"}
    )
    headers = headers or {}
    for key, value in headers.items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read())


print("=== Thunder API Test ===")
print()

# 1. Root (returns HTML page, not JSON)
with ur.urlopen(f"{BASE}/", timeout=10) as r:
    html = r.read()
    print(f"  GET  /              → {r.status} ({len(html):,} bytes HTML)")

# 2. Login first so subsequent protected calls are authenticated.
token = ""
try:
    status, data = post(
        "/api/auth/login", {"username": "admin", "password": "admin123"}
    )
    token = data.get("access_token", "")
    print(f"  POST /api/auth/login    → {status}: token={'OK' if token else 'MISSING'}")
except Exception as e:
    print(f"  POST /api/auth/login    → ERROR: {str(e)[:100]}")

# 3. Register (if no users). The backend returns 400 when the username already
# exists, so treat 400 as "already exists" and keep going.
auth_headers = {"Authorization": f"Bearer {token}"} if token else {}
try:
    status, data = post(
        "/api/auth/register", {"username": "admin", "password": "admin123"}
    )
    print(f"  POST /api/auth/register → {status}: {data.get('message', data)}")
except urllib.error.HTTPError as e:
    err_body = e.read().decode(errors="ignore")
    if e.code in (400, 409):
        print(f"  POST /api/auth/register → {e.code} (already exists, OK)")
    else:
        print(f"  POST /api/auth/register → ERROR: {e.code} {err_body[:100]}")
except Exception as e:
    print(f"  POST /api/auth/register → ERROR: {str(e)[:100]}")

# 4. Health (protected endpoint)
try:
    status, data = get("/api/system/health", headers=auth_headers)
    print(f"  GET  /api/system/health → {status}")
    for k, v in data.items():
        print(f"       {k}: {v}")
except Exception as e:
    print(f"  GET  /api/system/health → ERROR: {e}")

# 5. Industries (protected endpoint)
try:
    status, data = get("/api/industries", headers=auth_headers)
    count = len(data) if isinstance(data, list) else data.get("total", "?")
    print(f"  GET  /api/industries    → {status}: {count} industries")
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
        print(
            f"       leads:      pending={ds.get('lead_inventory', {}).get('pending', '?')}"
        )
    except Exception as e:
        print(f"  GET  /api/dashboard/state → ERROR: {str(e)[:100]}")

print()
print("=== API TEST COMPLETE ===")
