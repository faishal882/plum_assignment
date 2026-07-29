#!/usr/bin/env bash
set -euo pipefail

# Stop any local API, worker, and Phoenix processes, then restart them.
#
# Usage:
#   scripts/restart-dev-stack.sh
#
# Optional env overrides:
#   API_HOST=127.0.0.1 API_PORT=8000 PHOENIX_HOST=127.0.0.1 PHOENIX_PORT=6006 scripts/restart-dev-stack.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/data/dev-stack"
LOG_DIR="$RUN_DIR/logs"
PID_DIR="$RUN_DIR/pids"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
PHOENIX_HOST="${PHOENIX_HOST:-127.0.0.1}"
PHOENIX_PORT="${PHOENIX_PORT:-6006}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Stop any local API, worker, and Phoenix processes, then restart them.

Usage:
  scripts/restart-dev-stack.sh

Optional env overrides:
  API_HOST=127.0.0.1 API_PORT=8000 PHOENIX_HOST=127.0.0.1 PHOENIX_PORT=6006 scripts/restart-dev-stack.sh
EOF
  exit 0
elif [[ -n "${1:-}" ]]; then
  echo "Unknown argument: $1" >&2
  echo "Usage: scripts/restart-dev-stack.sh" >&2
  exit 2
fi

mkdir -p "$LOG_DIR" "$PID_DIR"

stop_pattern() {
  local label="$1"
  local pattern="$2"

  echo "Stopping $label if running..."
  if pgrep -f "$pattern" >/dev/null 2>&1; then
    pkill -TERM -f "$pattern" || true
    for _ in {1..20}; do
      if ! pgrep -f "$pattern" >/dev/null 2>&1; then
        echo "  stopped $label"
        return 0
      fi
      sleep 0.25
    done
    echo "  $label did not exit after TERM; sending KILL"
    pkill -KILL -f "$pattern" || true
  else
    echo "  no $label process found"
  fi
}

start_service() {
  local label="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  echo "Starting $label..."
  (
    cd "$ROOT_DIR"
    exec "$@"
  ) >"$log_file" 2>&1 &
  local pid=$!
  echo "$pid" >"$pid_file"
  echo "  pid: $pid"
  echo "  log: $log_file"
}

wait_for_http() {
  local label="$1"
  local url="$2"
  local attempts="${3:-40}"

  printf "Waiting for %s at %s" "$label" "$url"
  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo " OK"
      return 0
    fi
    printf "."
    sleep 0.5
  done
  echo " not ready yet"
  return 1
}

# Stop in dependency-safe order: worker first, then API, then Phoenix.
stop_pattern "claims worker" "claims-worker run-loop"
stop_pattern "FastAPI/uvicorn API" "uvicorn claims_backend.api.app:app"
stop_pattern "Phoenix server" "phoenix serve.*--port ${PHOENIX_PORT}|phoenix.server.main"

# Clean stale pid files after stopping.
rm -f "$PID_DIR"/*.pid

start_service \
  "Phoenix" \
  "$PID_DIR/phoenix.pid" \
  "$LOG_DIR/phoenix.log" \
  uv run phoenix serve --host "$PHOENIX_HOST" --port "$PHOENIX_PORT"

start_service \
  "FastAPI API" \
  "$PID_DIR/api.pid" \
  "$LOG_DIR/api.log" \
  uv run uvicorn claims_backend.api.app:app --host "$API_HOST" --port "$API_PORT" --reload

start_service \
  "claims worker" \
  "$PID_DIR/worker.pid" \
  "$LOG_DIR/worker.log" \
  uv run claims-worker run-loop

echo
wait_for_http "Phoenix" "http://${PHOENIX_HOST}:${PHOENIX_PORT}" 20 || true
wait_for_http "API health" "http://${API_HOST}:${API_PORT}/health/live" 40 || true

echo
cat <<EOF
Dev stack restarted.

PIDs:
  Phoenix: $(cat "$PID_DIR/phoenix.pid")
  API:     $(cat "$PID_DIR/api.pid")
  Worker:  $(cat "$PID_DIR/worker.pid")

Logs:
  $LOG_DIR/phoenix.log
  $LOG_DIR/api.log
  $LOG_DIR/worker.log

Useful checks:
  curl http://${API_HOST}:${API_PORT}/health/live
  curl http://${API_HOST}:${API_PORT}/health/ready
  open http://${PHOENIX_HOST}:${PHOENIX_PORT}
EOF
