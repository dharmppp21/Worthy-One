#!/usr/bin/env bash
set -euo pipefail

# Terraform validation script for SignalForge
# Usage: ./terraform/validate.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAIL_COUNT=0

for dir in "${SCRIPT_DIR}/examples/eks-complete" "${SCRIPT_DIR}/examples/ecs-simple"; do
  echo "=== Validating: ${dir} ==="
  cd "${dir}"

  if ! terraform init -backend=false > /dev/null 2>&1; then
    echo "ERROR: terraform init failed in ${dir}"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    continue
  fi

  if ! terraform validate; then
    echo "ERROR: terraform validate failed in ${dir}"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  else
    echo "OK: ${dir} is valid"
  fi
  echo ""
done

if [ ${FAIL_COUNT} -gt 0 ]; then
  echo "Validation failed in ${FAIL_COUNT} directory(s)."
  exit 1
fi

echo "All Terraform validations passed!"
