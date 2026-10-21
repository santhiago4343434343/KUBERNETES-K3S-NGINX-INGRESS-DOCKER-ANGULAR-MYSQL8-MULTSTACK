#!/bin/bash
# Builda e sobe SO o que mudou (economiza metade do tempo).
# Uso:  ./deploy.sh front   |   ./deploy.sh back   |   ./deploy.sh ambos
set -euo pipefail                      # para na PRIMEIRA falha de verdade (build, import, set image)

ALVO="${1:-ambos}"
TAG="deploy-$(date +%H%M%S)"
CLUSTER=movies-tmda

subir_back() {
  echo "🐍 Backend ($TAG)..."
  docker build -t catalogo-backend:"$TAG" ./backend
  k3d image import catalogo-backend:"$TAG" -c "$CLUSTER"
  kubectl set image deployment/backend backend=catalogo-backend:"$TAG"
}

subir_front() {
  echo "🅰️  Frontend ($TAG)..."
  docker build -t catalogo-frontend:"$TAG" ./frontend
  k3d image import catalogo-frontend:"$TAG" -c "$CLUSTER"
  kubectl set image deployment/frontend frontend=catalogo-frontend:"$TAG"
}

case "$ALVO" in
  back)  subir_back ;;
  front) subir_front ;;
  ambos) subir_back; subir_front ;;
  *) echo "Uso: ./deploy.sh [front|back|ambos]"; exit 1 ;;
esac

echo "⏳ Aguardando o rollout..."
if [ "$ALVO" != "front" ]; then kubectl rollout status deployment/backend  --timeout=180s; fi
if [ "$ALVO" != "back"  ]; then kubectl rollout status deployment/frontend --timeout=180s; fi

echo "✅ Feito de verdade!  →  http://localhost:8090"