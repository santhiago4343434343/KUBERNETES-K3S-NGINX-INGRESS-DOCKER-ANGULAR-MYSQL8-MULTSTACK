#!/bin/bash
# Builda e sobe SO o que mudou (economiza metade do tempo).
# Uso:  ./deploy.sh front   |   ./deploy.sh back   |   ./deploy.sh ambos
ALVO="${1:-ambos}"
TAG="deploy-$(date +%H%M%S)"
CLUSTER=painel-obs

subir_back() {
  echo "🐍 Backend ($TAG)..."
  docker build -t catalogo-backend:"$TAG" ./backend \
    && k3d image import catalogo-backend:"$TAG" -c "$CLUSTER" \
    && kubectl set image deployment/backend backend=catalogo-backend:"$TAG"
}
subir_front() {
  echo "🅰️  Frontend ($TAG)..."
  docker build -t catalogo-frontend:"$TAG" ./frontend \
    && k3d image import catalogo-frontend:"$TAG" -c "$CLUSTER" \
    && kubectl set image deployment/frontend frontend=catalogo-frontend:"$TAG"
}

case "$ALVO" in
  back)  subir_back ;;
  front) subir_front ;;
  ambos) subir_back && subir_front ;;
  *) echo "Uso: ./deploy.sh [front|back|ambos]"; exit 1 ;;
esac

echo "⏳ Aguardando o rollout..."
[ "$ALVO" != "front" ] && kubectl rollout status deployment/backend  --timeout=180s
[ "$ALVO" != "back" ]  && kubectl rollout status deployment/frontend --timeout=180s
echo "✅ Feito!  →  http://localhost:8090"

