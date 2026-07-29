#!/usr/bin/env bash
set -euo pipefail

# Reset runtime claim/workflow/document tables while preserving seeded users,
# members, policies, policy versions, and overlays.
#
# Usage:
#   scripts/clean-db.sh           # prompt before cleaning
#   scripts/clean-db.sh --yes     # non-interactive
#
# Optional env overrides:
#   PGHOST=127.0.0.1 PGPORT=55432 PGUSER=claims PGPASSWORD=claims PGDATABASE=claims scripts/clean-db.sh --yes

YES=0
if [[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]]; then
  YES=1
elif [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Reset runtime claim/workflow/document tables while preserving seeded users,
members, policies, policy versions, and overlays.

Usage:
  scripts/clean-db.sh           # prompt before cleaning
  scripts/clean-db.sh --yes     # non-interactive

Optional env overrides:
  PGHOST=127.0.0.1 PGPORT=55432 PGUSER=claims PGPASSWORD=claims PGDATABASE=claims scripts/clean-db.sh --yes
EOF
  exit 0
elif [[ -n "${1:-}" ]]; then
  echo "Unknown argument: $1" >&2
  echo "Usage: scripts/clean-db.sh [--yes]" >&2
  exit 2
fi

export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-55432}"
export PGUSER="${PGUSER:-claims}"
export PGPASSWORD="${PGPASSWORD:-claims}"
export PGDATABASE="${PGDATABASE:-claims}"

if [[ "$YES" -ne 1 ]]; then
  echo "This will TRUNCATE runtime claim data in PostgreSQL:"
  echo "  postgresql://${PGUSER}:***@${PGHOST}:${PGPORT}/${PGDATABASE}"
  echo
  echo "Preserves seeded policy/member/user data; cascades from: idempotency_keys, claims"
  read -r -p "Continue? Type 'clean' to proceed: " confirmation
  if [[ "$confirmation" != "clean" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

psql -v ON_ERROR_STOP=1 <<'SQL'
TRUNCATE TABLE idempotency_keys, claims RESTART IDENTITY CASCADE;
SQL

echo
psql -v ON_ERROR_STOP=1 <<'SQL'
SELECT table_name, row_count
FROM (
  VALUES
    ('claims', (SELECT count(*)::bigint FROM claims)),
    ('claim_versions', (SELECT count(*)::bigint FROM claim_versions)),
    ('claim_work_items', (SELECT count(*)::bigint FROM claim_work_items)),
    ('workflow_runs', (SELECT count(*)::bigint FROM workflow_runs)),
    ('workflow_events', (SELECT count(*)::bigint FROM workflow_events)),
    ('workflow_effects', (SELECT count(*)::bigint FROM workflow_effects)),
    ('documents', (SELECT count(*)::bigint FROM documents)),
    ('document_versions', (SELECT count(*)::bigint FROM document_versions)),
    ('document_page_artifacts', (SELECT count(*)::bigint FROM document_page_artifacts)),
    ('ocr_page_results', (SELECT count(*)::bigint FROM ocr_page_results)),
    ('ocr_observations', (SELECT count(*)::bigint FROM ocr_observations)),
    ('document_triage_results', (SELECT count(*)::bigint FROM document_triage_results)),
    ('identity_reconciliations', (SELECT count(*)::bigint FROM identity_reconciliations)),
    ('model_extractions', (SELECT count(*)::bigint FROM model_extractions)),
    ('evidence_candidates', (SELECT count(*)::bigint FROM evidence_candidates)),
    ('casefiles', (SELECT count(*)::bigint FROM casefiles)),
    ('rule_results', (SELECT count(*)::bigint FROM rule_results)),
    ('member_actions', (SELECT count(*)::bigint FROM member_actions)),
    ('decision_records', (SELECT count(*)::bigint FROM decision_records)),
    ('review_tasks', (SELECT count(*)::bigint FROM review_tasks)),
    ('review_resolutions', (SELECT count(*)::bigint FROM review_resolutions)),
    ('component_failures', (SELECT count(*)::bigint FROM component_failures)),
    ('idempotency_keys', (SELECT count(*)::bigint FROM idempotency_keys))
) AS counts(table_name, row_count)
ORDER BY table_name;
SQL

echo
echo "Runtime DB cleaned."
