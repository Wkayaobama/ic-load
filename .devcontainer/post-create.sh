#!/usr/bin/env bash
set -euo pipefail

echo "Installing reproducible toolchain..."
pip install --upgrade pip
pip install -r /workspaces/icalps/requirements.txt
pip install dbt-postgres snakemake
npm install -g repomix@latest

echo "Validating required tools..."
for tool in gomplate yq repomix dbt snakemake python; do
  command -v "$tool" >/dev/null
done

echo "Container root: ${ICALPS_PROJECT_ROOT}"
test -f /workspaces/icalps/GomplateRepoMix/schema_context.yaml

cat <<'EOF'
Codespaces note:
- Prefer repository-level Codespaces secrets for ICALPS_DB_*.
- If you use Codespaces secrets, remove the runArgs env-file line from .devcontainer/devcontainer.json.
EOF
