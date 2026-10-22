#!/bin/bash
# release.sh — loop de release GitOps.
# Builda a imagem, importa no k3d, sobe a tag (vN -> vN+1) no manifest e da push.
# O Argo CD (que observa a pasta k8s/) aplica a mudanca sozinho no cluster.
#
# Uso:  ./release.sh front   |   ./release.sh back   |   ./release.sh ambos
set -euo pipefail

ALVO="${1:-ambos}"
CLUSTER=movies-tmda

# $1=nome-curto  $2=imagem  $3=manifest  $4=diretorio do build
bump() {
  local svc="$1" img="$2" manifest="$3" ctx="$4"
  local atual nova
  atual=$(grep -oE "${img}:v[0-9]+" "$manifest" | head -1 | grep -oE '[0-9]+$' || true)
  if [ -z "$atual" ]; then
    echo "❌ Nao achei a tag ${img}:vN em ${manifest}"; exit 1
  fi
  nova=$((atual + 1))
  echo "📦 ${svc}: v${atual} -> v${nova}"
  docker build -t "${img}:v${nova}" "$ctx"
  k3d image import "${img}:v${nova}" -c "$CLUSTER"
  sed -i "s#${img}:v${atual}#${img}:v${nova}#g" "$manifest"
  git add "$manifest"
}

case "$ALVO" in
  back)  bump backend  catalogo-backend  k8s/backend-deployment.yaml  ./backend ;;
  front) bump frontend catalogo-frontend k8s/frontend-deployment.yaml ./frontend ;;
  ambos) bump backend  catalogo-backend  k8s/backend-deployment.yaml  ./backend
         bump frontend catalogo-frontend k8s/frontend-deployment.yaml ./frontend ;;
  *) echo "Uso: ./release.sh [front|back|ambos]"; exit 1 ;;
esac

git commit -m "deploy: release ${ALVO} ($(date '+%Y-%m-%d %H:%M'))"
git push

echo "✅ Push feito. O Argo CD vai sincronizar o cluster em instantes."
echo "   Acompanhe:  kubectl get applications -n argocd   (ou no painel do Argo)"
