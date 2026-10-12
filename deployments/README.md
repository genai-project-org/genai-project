# Deploying IEMA.ai (single EC2 + Docker Compose)

Stack on one Ubuntu 24.04 EC2 (t3.large): `caddy` (auto-HTTPS, serves the built SPA, proxies `/api/*`),
`api` (FastAPI/uvicorn), `piston` (privileged code runner), `mongo` (bundled; use Atlas by setting `MONGO_URL`).
The SPA is built with `VITE_BACKEND_URL=https://$DOMAIN`, so API calls are same-origin `/api`.

## First-time setup

1. **AWS**: `aws sts get-caller-identity` must work (region ap-south-1 by default). `./deployments/provision.sh`
   creates key pair `iema-prod` (saved to `~/.ssh/iema-prod.pem`), security group `iema-prod-sg`
   (22 from your IP only, 80, 443 tcp/udp), one t3.large + 40GB gp3, one Elastic IP. It writes `deployments/.deploy-state`.
   Override SSH source with `SSH_CIDR=1.2.3.4/32`; to add another IP later:
   `aws ec2 authorize-security-group-ingress --group-id <sg> --protocol tcp --port 22 --cidr <ip>/32`.
2. **Env**: `./deployments/env.production` creates the gitignored `deployments/.env.production` from the template, copying
   matching keys from `apps/api/.env` (never prints values; re-run keeps your edits). Review it, especially:
   `JWT_SECRET`, `ADMIN_*`, `RAZORPAY_*`, `RESEND_API_KEY`/`SENDER_EMAIL`, OAuth client ids/secrets, `MCP_DEMO_MODE`.
   `APP_URL`, `CORS_ORIGINS`, `PISTON_URL`, `MONGO_URL` are derived by compose (leave blank).
3. **DNS** (at your registrar): `A  iema.ai -> <Elastic IP>` and `A  www.iema.ai -> <Elastic IP>`. Caddy gets the
   certificates automatically once DNS resolves (ports 80/443 must be open). Then set `DOMAIN=iema.ai`
   and blank `SITE_ADDRESS` in `.env.production` and redeploy (the web bundle is rebuilt for the new domain).
   Before DNS, you can use `DOMAIN=<ip-with-dashes>.sslip.io` (and `SITE_ADDRESS` the same) for a real-HTTPS test URL.
4. **OAuth providers**: redirect URIs `https://iema.ai/auth/callback` (login) and
   `https://iema.ai/connectors/oauth-callback` (connectors).

## Redeploy (one command)

```
./deployments/deploy.sh
```
Syncs code (rsync), builds images on the server, `docker compose up -d`, installs Piston runtimes (idempotent),
runs `scripts/seed_contest.py` (idempotent; packs/plans/templates seed on API startup), health-checks the API.
Deploy another checkout: `APPS_SRC=/path/to/repo ./deployments/deploy.sh`.

## Logs / ops / rollback

```
./deployments/deploy.sh logs            # all services; or: logs api | caddy | piston | mongo
ssh -i ~/.ssh/iema-prod.pem ubuntu@<ip>  # then: cd /opt/iema/deployments && sudo docker compose --env-file .env.production ps
./deployments/deploy.sh rollback        # retags the previous api/web images (:prev) and restarts
```
Rollback only covers the last deploy's images; DB changes are not reverted. Mongo data lives in the `mongo_data`
volume (back it up with `docker exec iema-mongo-1 mongodump --archive > dump.archive`).

## Smoke checklist

- [ ] `curl https://iema.ai/api/health` -> `{"status":"healthy"}`; `https://www.iema.ai` redirects to apex
- [ ] Sign up (email), log in, log out, log in again
- [ ] Social login (Google/GitHub) returns via `/auth/callback`
- [ ] Contest page loads, problem list shows, run a Python snippet (exercises Piston); also JS/C++/Java
- [ ] Connectors page lists providers; connect one (redirect to `/connectors/oauth-callback`) or demo mode works
- [ ] Pricing page shows packs; create a Razorpay payment link/order
- [ ] Welcome/verification email arrives (Resend)

## Notes

- Piston runs `privileged` (needed for its isolate sandbox) and is only reachable on the internal compose network.
  If a runtime install fails, `docker compose ... logs piston`, then re-run `deploy.sh`
  (runtimes: python 3.10.0, node 20.11.1, gcc 10.2.0, java 15.0.2, matching `services/practice_service.py`).
- `apps/api/requirements.txt` pins `fastapi==0.110.1`/`starlette==0.37.2`, which conflict with `mcp==1.30.0`;
  `Dockerfile.api` relaxes those two pins at build time (no app files changed).
- The web image uses `npm install` (the lockfile is out of sync with package.json).
- The first API start downloads the Whisper model (cached in the `hf_cache` volume); the speaker-verification model
  is missing and degrades gracefully.
