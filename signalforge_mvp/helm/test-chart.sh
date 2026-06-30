#!/usr/bin/env bash
set -euo pipefail

# Chart test script for SignalForge Helm chart
# Usage: ./helm/test-chart.sh

CHART_DIR="helm/signforge"

if ! command -v helm &> /dev/null; then
    echo "ERROR: helm is not installed. Please install Helm: https://helm.sh/docs/intro/install/"
    exit 1
fi

echo "=== Add Helm repositories ==="
helm repo add bitnami https://charts.bitnami.com/bitnami 2>/dev/null || true
helm repo update

echo ""
echo "=== Build chart dependencies ==="
cd "${CHART_DIR}"
helm dependency build
cd - > /dev/null

echo ""
echo "=== Helm Lint ==="
helm lint "${CHART_DIR}"

echo ""
echo "=== Helm Template (default values) ==="
helm template signforge "${CHART_DIR}" > /dev/null
echo "OK: Chart renders with default values"

echo ""
echo "=== Helm Template (with external PostgreSQL) ==="
helm template signforge "${CHART_DIR}" \
    --set postgresql.enabled=false \
    --set env.DATABASE_URL=postgresql://user:pass@host:5432/db \
    > /dev/null
echo "OK: Chart renders with external PostgreSQL"

echo ""
echo "=== Helm Template (single-namespace RBAC) ==="
helm template signforge "${CHART_DIR}" \
    --set discovery.kubernetes.clusterRole=false \
    > /dev/null
echo "OK: Chart renders with single-namespace RBAC"

echo ""
echo "=== Helm Template (with Kafka) ==="
helm template signforge "${CHART_DIR}" \
    --set kafka.enabled=true \
    > /dev/null
echo "OK: Chart renders with Kafka enabled"

echo ""
echo "=== Helm Template (with HPA) ==="
helm template signforge "${CHART_DIR}" \
    --set hpa.enabled=true \
    > /dev/null
echo "OK: Chart renders with HPA enabled"

echo ""
echo "=== Helm Template (with Ingress) ==="
helm template signforge "${CHART_DIR}" \
    --set ingress.enabled=true \
    > /dev/null
echo "OK: Chart renders with Ingress enabled"

echo ""
# Check for helm-unittest plugin
if helm plugin list | grep -q unittest; then
    echo "=== Helm Unit Tests ==="
    helm unittest "${CHART_DIR}"
else
    echo "=== Helm Unit Tests SKIPPED ==="
    echo "Install helm-unittest plugin to run unit tests:"
    echo "  helm plugin install https://github.com/quintush/helm-unittest"
fi

echo ""
echo "All chart tests passed!"
