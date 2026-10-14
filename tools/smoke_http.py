"""Smoke-test an isolated, empty Novel instance without calling an AI model."""

import json
import re
import sys
import time
from urllib.request import Request, urlopen

origin = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8791"
for attempt in range(30):
    try:
        with urlopen(origin + "/health", timeout=2) as response:
            health = json.load(response)
        break
    except OSError:
        time.sleep(1)
else:
    raise RuntimeError("Novel failed to become healthy")
assert health == {"status": "ok", "version": "0.7.0"}, health
with urlopen(origin, timeout=3) as response:
    html = response.read().decode("utf-8")
assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
assert assets, "Missing frontend build"
for asset in assets:
    with urlopen(origin + asset, timeout=3) as response:
        assert response.status == 200 and response.read()
with urlopen(origin + "/api/state", timeout=3) as response:
    state = json.load(response)
assert state["series"] == [], "Run only against an isolated empty library"
request = Request(
    origin + "/api/action",
    data=b'{"action":"demo"}',
    headers={"Content-Type": "application/json", "Origin": origin, "X-Novel-CSRF": state["csrf"]},
)
with urlopen(request, timeout=10) as response:
    assert json.load(response)["series_id"]
with urlopen(origin + "/api/state", timeout=3) as response:
    assert len(json.load(response)["series"]) == 1
print("Docker health, frontend assets and synthetic demo passed; no inference.")
