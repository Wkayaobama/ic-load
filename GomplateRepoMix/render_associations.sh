#!/usr/bin/env bash
# render_associations.sh
# Concrete Gomplate script to render ALL association SQL files from templates.
#
# Usage:
#   bash GomplateRepoMix/render_associations.sh
#
# Prerequisites:
#   - gomplate is installed (https://docs.gomplate.ca/)
#   - schema_context.yaml and run_context.yaml resolve correctly from this script's directory
#
# ── Loop 1: Communication engagement associations (association_bridge.sql.tmpl) ──
# Outputs (written to ../sql/rendered/):
#   association_calls_company.sql  association_calls_contact.sql
#   association_notes_company.sql  association_notes_contact.sql  association_notes_deal.sql
#   association_tasks_company.sql  association_tasks_contact.sql
#
# ── Loop 2: Direct-FK object associations (association_object.sql.tmpl) ─────────
# Outputs (written to ../sql/rendered/):
#   association_ticket_company.sql
#   association_ticket_contact.sql
#   association_ticket_deal.sql
#
# Each file implements the two-pass pattern:
#   Pass A — StackSync UUID join (stacksync_record_id_* column)
#   Pass B — legacy icalps_*_id fallback
# Both passes use NOT EXISTS idempotency guard. UNION (not UNION ALL) between passes.
#
# Idempotency contract: re-running this script produces byte-identical SQL files
# for the same schema_context.yaml + run_context.yaml inputs. Any type ID update
# in schema_context.yaml automatically propagates to all rendered SQL on next run.
#
# See: GomplateRepoMix/templates/association_bridge.sql.tmpl   (communication pattern)
# See: GomplateRepoMix/templates/association_object.sql.tmpl   (direct-FK pattern)
# See: docs/ASSOCIATION_PROBE_TECHNICAL_STATE.md (M6 for history of the hand-written SQL mistake)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SCHEMA_FILE="${SCRIPT_DIR}/schema_context.yaml"
RUN_FILE="${SCRIPT_DIR}/run_context.yaml"
TEMPLATE_COMM="${SCRIPT_DIR}/templates/association_bridge.sql.tmpl"
TEMPLATE_OBJ="${SCRIPT_DIR}/templates/association_object.sql.tmpl"
OUTPUT_DIR="${REPO_ROOT}/sql/rendered"

if [ ! -f "${SCHEMA_FILE}" ]; then
  echo "ERROR: schema_context.yaml not found at ${SCHEMA_FILE}" >&2
  exit 1
fi

if [ ! -f "${RUN_FILE}" ]; then
  echo "ERROR: run_context.yaml not found at ${RUN_FILE}" >&2
  exit 1
fi

if [ ! -f "${TEMPLATE_COMM}" ]; then
  echo "ERROR: association_bridge.sql.tmpl not found at ${TEMPLATE_COMM}" >&2
  exit 1
fi

if [ ! -f "${TEMPLATE_OBJ}" ]; then
  echo "ERROR: association_object.sql.tmpl not found at ${TEMPLATE_OBJ}" >&2
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
echo "IC'ALPS association bridge — Gomplate render (all patterns)"
echo "Template (comm) : ${TEMPLATE_COMM}"
echo "Template (obj)  : ${TEMPLATE_OBJ}"
echo "Schema          : ${SCHEMA_FILE}"
echo "Run ctx         : ${RUN_FILE}"
echo "Output          : ${OUTPUT_DIR}"
echo "════════════════════════════════════════════════"
echo "Loop 1 — Communication engagement associations"
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
        --file "${TEMPLATE_COMM}" \
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

echo ""
echo "Loop 2 — Direct-FK object associations"
echo "────────────────────────────────────────────────"

# Object patterns: object_type x target
# Mirrors association_object_bridge.supported_patterns in schema_context.yaml
declare -A OBJ_PATTERNS
OBJ_PATTERNS["ticket"]="company contact deal"

for OBJ_TYPE in ticket; do
  for TARGET in ${OBJ_PATTERNS[$OBJ_TYPE]}; do
    OUT_FILE="${OUTPUT_DIR}/association_${OBJ_TYPE}_${TARGET}.sql"

    echo -n "  Rendering ${OBJ_TYPE} → ${TARGET} ... "

    export GOMPLATE_OBJECT_TYPE="${OBJ_TYPE}"
    export GOMPLATE_ASSOC_TARGET="${TARGET}"

    if gomplate \
        --datasource "schema=file://${SCHEMA_FILE}" \
        --datasource "run=file://${RUN_FILE}" \
        --file "${TEMPLATE_OBJ}" \
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

echo ""
echo "════════════════════════════════════════════════"
echo "  Rendered : ${RENDERED}"
echo "  Errors   : ${ERRORS}"
echo ""

if [ "${ERRORS}" -gt 0 ]; then
  echo "ERROR: ${ERRORS} render(s) failed. Check gomplate is installed and datasource paths are correct." >&2
  exit 1
fi

echo "All association SQL files rendered successfully."
echo ""
echo "Verify two-pass pattern in each output file:"
echo "── Communication ────────────────────────────────"
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
echo "── Object ───────────────────────────────────────"
for OBJ_TYPE in ticket; do
  for TARGET in ${OBJ_PATTERNS[$OBJ_TYPE]}; do
    OUT_FILE="${OUTPUT_DIR}/association_${OBJ_TYPE}_${TARGET}.sql"
    PASS_A=$(grep -c "Pass A" "${OUT_FILE}" 2>/dev/null || echo 0)
    PASS_B=$(grep -c "Pass B" "${OUT_FILE}" 2>/dev/null || echo 0)
    if [ "${PASS_A}" -ge 1 ] && [ "${PASS_B}" -ge 1 ]; then
      echo "  [OK] ${OBJ_TYPE}_${TARGET}.sql — two-pass confirmed"
    else
      echo "  [WARN] ${OBJ_TYPE}_${TARGET}.sql — two-pass markers missing (Pass A: ${PASS_A}, Pass B: ${PASS_B})"
    fi
  done
done
echo ""
