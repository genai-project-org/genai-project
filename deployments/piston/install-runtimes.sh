#!/usr/bin/env bash
# Install the runtimes the contest needs into the running piston container. Idempotent.
# Run on the server from deployments/ (deploy.sh does this for you).
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f docker-compose.yml --env-file .env.production exec -T api python - <<'PY'
import requests, sys, time
base = "http://piston:2000/api/v2"
# (piston package, version) -- must match LANGUAGES in apps/api/services/practice_service.py
want = [("python", "3.10.0"), ("node", "20.11.1"), ("gcc", "10.2.0"), ("java", "15.0.2")]
for _ in range(40):
    try:
        requests.get(base + "/runtimes", timeout=3); break
    except Exception:
        time.sleep(3)
rts = requests.get(base + "/runtimes", timeout=10).json()
for lang, ver in want:
    if any(r["version"] == ver and (r["language"] == lang or lang in r.get("aliases", [])) for r in rts):
        print("ok     ", lang, ver); continue
    print("install", lang, ver, flush=True)
    r = requests.post(base + "/packages", json={"language": lang, "version": ver}, timeout=900)
    print("  ->", r.status_code, r.text[:200])
    if r.status_code >= 400:
        sys.exit(1)
PY
