#!/usr/bin/env bash
# render_associations.sh
# Concrete Gomplate script to render all supported association bridge SQL files.
#
# Usage:
#   bash GomplateRepoMix/render_associations.sh
#
# Prerequisites:
#   - gomplate is installed (https://docs.gomplate.ca/)
#   - GOMPLATE_DATASOURCE_SCHEMA and GOMPLATE_DATASOURCE_RUN are set, or
#     the defaults below resolve correctly from this script's directory
#
# Outputs (written to ../sql/rendered/):
#   association_calls_company.sql
#   association_calls_contact.sql
#   association_notes_company.sql
#   association_notes_contact.sql
#   association_notes_deal.sql
#   association_tasks_company.sql
#   association_tasks_contact.sql
#
# Each file implements the two-pass pattern:
#   Pass A — StackSync UUID join (stacksync_record_id_* → associated_*_id)
#   Pass B — legacy ID fallback  (icalps_*_id → legacy_*_id)
# Both passes use NOT EXISTS idempotency guard. UNION between passes.
#
# See: GomplateRepoMix/templates/association_bridge.sql.tmpl
# See: docs/ASSOCIATION_PROBE_TECHNICAL_STATE.md

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SCHEMA_FILE="${SCRIPT_DIR}/schema_context.yaml"
RUN_FILE="${SCRIPT_DIR}/run_context.yaml"
TEMPLATE="${SCRIPT_DIR}/templates/association_bridge.sql.tmpl"
OUTPUT_DIR="${REPO_ROOT}/sql/rendered"

if [ ! -f "${SCHEMA_FILE}" ]; then
  echo "ERROR: schema_context.yaml not found at ${SCHEMA_FILE}" >&2
  exit 1
fi

if [ ! -f "${RUN_FILE}" ]; then
  echo "ERROR: run_context.yaml not found at ${RUN_FILE}" >&2
  exit 1
fi

if [ ! -f "${TEMPLATE}" ]; then
  echo "ERROR: association_bridge.sql.tmpl not found at ${TEMPLATE}" >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

# Supported patterns: comm_type x target
# Mirrors association_bridge.supported_patterns in schema_context.yaml
# Meetings are explicitly excluded (see schema_context.yaml for deferral rationale)
declare -A PATTERNS
PATTERNS["Calls"]="company contact"
PATTERNS["Notes"]="company contact deal"
PATTERNS["Tasks"]="company contact"

RENDERED=0
ERRORS=0

echo ""
echo "IC'ALPS association bridge — Gomplate render"
echo "Template : ${TEMPLATE}"
echo "Schema   : ${SCHEMA_FILE}"
echo "Run ctx  : ${RUN_FILE}"
echo "Output   : ${OUTPUT_DIR}"
echo "────────────────────────────────────────────────"

for COMM_TYPE in Calls Notes Tasks; do
  for TARGET in ${PATTERNS[$COMM_TYPE]}; do
    OUT_FILE="${OUTPUT_DIR}/association_${COMM_TYPE,,}_${TARGET}.sql"

    echo -n "  Rendering ${COMM_TYPE} → ${TARGET} ... "

    export GOMPLATE_COMM_TYPE="${COMM_TYPE}"
    export GOMPLATE_ASSOC_TARGET="${TARGET}"

    if gomplate \
        --datasource "schema=file://${SCHEMA_FILE}" \
        --datasource "run=file://${RUN_FILE}" \
        --file "${TEMPLATE}" \
        --out "${OUT_FILE}" 2>/dev/null; then
      LINE_COUNT=$(wc -l < "${OUT_FILE}")
      echo "OK  (${LINE_COUNT} lines → $(basename "${OUT_FILE}"))"
      RENDERED=$((RENDERED + 1))
    else
      echo "FAILED"
      ERRORS=$((ERRORS + 1))
    fi
  done
done

echo "────────────────────────────────────────────────"
echo "  Rendered : ${RENDERED}"
echo "  Errors   : ${ERRORS}"
echo ""

if [ "${ERRORS}" -gt 0 ]; then
  echo "ERROR: ${ERRORS} render(s) failed. Check gomplate is installed and datasource paths are correct." >&2
  exit 1
fi

echo "All association bridge SQL files rendered successfully."
echo ""
echo "Verify two-pass pattern is present in each output file:"
for COMM_TYPE in Calls Notes Tasks; do
  for TARGET in ${PATTERNS[$COMM_TYPE]}; do
    OUT_FILE="${OUTPUT_DIR}/association_${COMM_TYPE,,}_${TARGET}.sql"
    PASS_A=$(grep -c "Pass A" "${OUT_FILE}" 2>/dev/null || echo 0)
    PASS_B=$(grep -c "Pass B" "${OUT_FILE}" 2>/dev/null || echo 0)
    if [ "${PASS_A}" -ge 1 ] && [ "${PASS_B}" -ge 1 ]; then
      echo "  [OK] ${COMM_TYPE,,}_${TARGET}.sql — two-pass confirmed"
    else
      echo "  [WARN] ${COMM_TYPE,,}_${TARGET}.sql — two-pass markers missing (Pass A: ${PASS_A}, Pass B: ${PASS_B})"
    fi
  done
done
echo ""
