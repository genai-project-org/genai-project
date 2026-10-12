#!/usr/bin/env bash
# One-command (re)deploy:  ./deployments/deploy.sh          build + ship + up + seed + health check
#                          ./deployments/deploy.sh rollback  retag :prev images and restart
#                          ./deployments/deploy.sh logs [svc]
# Config: deployments/.deploy-state (written by provision.sh) or env HOST, KEY_FILE, SSH_USER.
# APPS_SRC=/path/to/repo  deploy code from another checkout (default: the repo containing this script).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -f "$HERE/.deploy-state" ] && . "$HERE/.deploy-state"
: "${HOST:?HOST not set (run provision.sh or export HOST=<ip>)}"
KEY_FILE=${KEY_FILE:-$HOME/.ssh/iema-prod.pem}
SSH_USER=${SSH_USER:-ubuntu}
SRC=${APPS_SRC:-$(cd "$HERE/.." && pwd)}
REMOTE=/opt/iema
SSH_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30"
ssh_() { ssh $SSH_OPTS "$SSH_USER@$HOST" "$@"; }
DC="cd $REMOTE/deployments && sudo docker compose --env-file .env.production"

case "${1:-deploy}" in
  logs) shift; ssh_ "$DC logs -f --tail=200 $*"; exit;;
  rollback)
    ssh_ "for i in api web; do sudo docker tag iema-\$i:prev iema-\$i:latest; done; $DC up -d --no-build"
    echo "rolled back to previous images"; exit;;
esac

[ -f "$HERE/.env.production" ] || { echo "Missing deployments/.env.production: run deployments/env.production and review it"; exit 1; }

echo "==> waiting for ssh on $HOST"
for i in $(seq 1 40); do ssh_ true 2>/dev/null && break; sleep 5; done

echo "==> bootstrap (docker, swap) if needed"
ssh_ 'set -e
command -v docker >/dev/null || { curl -fsSL https://get.docker.com | sudo sh; sudo usermod -aG docker ubuntu; }
command -v rsync >/dev/null || sudo apt-get install -y rsync >/dev/null
if ! swapon --show | grep -q .; then sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile && echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null; fi
sudo mkdir -p '"$REMOTE"' && sudo chown ubuntu:ubuntu '"$REMOTE"

echo "==> sync code from $SRC"
rsync -az --delete -e "ssh $SSH_OPTS" \
  --exclude .git --exclude .claude --exclude node_modules --exclude .venv --exclude __pycache__ --exclude '.env' --exclude '.env.*' \
  --exclude 'apps/mobile' --exclude 'apps/web/dist' --exclude 'apps/api/uploads' --exclude '.pytest_cache' --exclude '.mongo_data*' --exclude '*.log' \
  "$SRC/apps" "$SRC/README.md" "$SSH_USER@$HOST:$REMOTE/"
rsync -az --delete -e "ssh $SSH_OPTS" --exclude .env.production --exclude .deploy-state --exclude '*.pem' "$HERE/" "$SSH_USER@$HOST:$REMOTE/deployments/"
scp $SSH_OPTS -q "$HERE/.env.production" "$SSH_USER@$HOST:$REMOTE/deployments/.env.production"
ssh_ "chmod 600 $REMOTE/deployments/.env.production"

echo "==> build + up (previous images kept as :prev for rollback)"
ssh_ "for i in api web; do sudo docker image inspect iema-\$i:latest >/dev/null 2>&1 && sudo docker tag iema-\$i:latest iema-\$i:prev || true; done; $DC up -d --build --remove-orphans && sudo docker image prune -f >/dev/null"

echo "==> piston runtimes (idempotent)"
ssh_ "cd $REMOTE/deployments && sudo bash piston/install-runtimes.sh" || echo "WARN: piston runtime install failed; contest code runs will fail (see README)"

echo "==> seeds (idempotent; packs/plans/templates also seed on API startup)"
ssh_ "$DC exec -T api python scripts/seed_contest.py" || echo "WARN: seed_contest failed"

echo "==> health check"
DOMAIN=$(grep -E '^DOMAIN=' "$HERE/.env.production" | cut -d= -f2-); DOMAIN=${DOMAIN:-iema.ai}
for i in $(seq 1 30); do
  if ssh_ "sudo docker exec iema-api-1 curl -fsS http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then echo "api healthy"; ok=1; break; fi; sleep 4
done
[ "${ok:-}" = 1 ] || { echo "API NOT healthy; logs:"; ssh_ "$DC logs --tail=60 api"; exit 1; }
code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 15 "https://$DOMAIN/api/health" || true)
echo "public https://$DOMAIN/api/health -> $code (needs DNS pointing at $HOST; until then test: curl -k --resolve $DOMAIN:443:$HOST https://$DOMAIN/api/health)"
echo "deployed: $(date -u +%FT%TZ)"
