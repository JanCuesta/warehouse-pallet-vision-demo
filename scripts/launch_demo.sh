#!/usr/bin/env bash
# Warehouse Pallet Vision Demo launcher (Ubuntu / ROS 2 Jazzy).
# Starts FastAPI, YOLO, and the corrected ROS->JSON snapshot bridge.
# Optionally launches the Isaac Sim GUI. KUKA movement is started manually
# from Isaac Sim's Script Editor after checking the scene and live detections.

set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ROS_SETUP="/opt/ros/jazzy/setup.bash"
VENV_ACTIVATE="$ROOT/.venv/bin/activate"
PYTHON="$ROOT/.venv/bin/python"
WORKSPACE_SETUP="$ROOT/sim/ros2_ws/install/setup.bash"
BRIDGE="$ROOT/sim/ros2_ws/scripts/whpv_yolo_snapshot_bridge.py"
CONTROLLER="$ROOT/sim/isaac_sim/scripts/demonstration_script.py"
SCENE="$ROOT/sim/isaac_sim/scenes/Worlds/IsaacSim_demonstration.usd"
REPORT="$ROOT/sim/isaac_sim/reports/kuka_all_boxes_backend_counts_report.txt"

ISAAC_MODE=auto
CHECK_ONLY=false
RUN_DIR=""
CORE_PIDS=()
ALL_PIDS=()

usage() {
  cat <<'HELP'
Usage: ./scripts/launch_demo.sh [--check | --no-isaac | --with-isaac]

  (no args)     Start FastAPI, YOLO, and snapshot bridge. Launch Isaac Sim
                too if a launcher is found.
  --no-isaac    Start only the three services; open Isaac Sim yourself.
  --with-isaac  Require an Isaac Sim launcher (see variable below).
  --check       Check prerequisites and paths without starting anything.

Optional environment variables:
  ISAAC_SIM_LAUNCHER=/absolute/path/to/isaac-sim.sh
  WHPV_DB_PATH=/absolute/path/to/an/existing-or-new-demo.sqlite3
  WHPV_CSV_PATH=/absolute/path/to/routes_demo.csv

Default: a fresh SQLite database is used on every launch.
Logs are saved to a printed temporary directory. Ctrl+C stops the
processes started by this launcher (including Isaac Sim if launched).

This does NOT execute the KUKA Script Editor controller automatically.
HELP
}

while (($#)); do
  case "$1" in
    --check) CHECK_ONLY=true ;;
    --no-isaac) ISAAC_MODE=no ;;
    --with-isaac) ISAAC_MODE=yes ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

check_required_file() {
  local path="$1" description="$2"
  if [[ ! -f "$path" ]]; then
    printf 'MISSING: %-19s %s\n' "$description" "$path" >&2
    return 1
  fi
  printf 'OK:      %-19s %s\n' "$description" "$path"
}

prerequisites() {
  local bad=0
  command -v setsid >/dev/null || { echo "MISSING: setsid (util-linux)" >&2; bad=1; }
  check_required_file "$ROS_SETUP" "ROS 2 Jazzy setup" || bad=1
  check_required_file "$VENV_ACTIVATE" "Python virtualenv" || bad=1
  check_required_file "$PYTHON" "Virtualenv Python" || bad=1
  check_required_file "$WORKSPACE_SETUP" "Built ROS workspace" || bad=1
  check_required_file "$ROOT/software/data/routes_demo.csv" "Example orders" || bad=1
  check_required_file "$BRIDGE" "YOLO snapshot bridge" || bad=1
  check_required_file "$CONTROLLER" "KUKA controller" || bad=1
  check_required_file "$SCENE" "Validated USD scene" || bad=1
  if ((bad)); then
    cat >&2 <<'HELP'

Prepare the public checkout first. For a new Python environment:
  cd ~/projects/warehouse-pallet-vision-demo
  python3 -m venv --system-site-packages .venv
  source .venv/bin/activate
  python -m pip install -e ./software fastapi uvicorn

If the ROS workspace was not built:
  source /opt/ros/jazzy/setup.bash
  cd sim/ros2_ws
  colcon build --symlink-install --packages-select whpv_perception_ros
HELP
    return 1
  fi
  if [[ "$ROOT" != "$HOME/projects/warehouse-pallet-vision-demo" ]]; then
    echo "WARNING: controller/bridge may still contain the old absolute demo path." >&2
    echo "         Check VISION_SNAPSHOT_PATH, SNAPSHOT_PATH, and OUTPUT." >&2
  fi
  return 0
}

find_isaac_launcher() {
  if [[ -n "${ISAAC_SIM_LAUNCHER:-}" ]]; then
    if [[ -f "$ISAAC_SIM_LAUNCHER" ]]; then
      printf '%s\n' "$ISAAC_SIM_LAUNCHER"
      return 0
    fi
    printf 'ISAAC_SIM_LAUNCHER does not exist: %s\n' "$ISAAC_SIM_LAUNCHER" >&2
    return 1
  fi
  if command -v isaac-sim.sh >/dev/null 2>&1; then
    command -v isaac-sim.sh
    return 0
  fi
  local path
  for path in "$HOME/isaacsim/isaac-sim.sh" "$HOME/isaac-sim/isaac-sim.sh"; do
    if [[ -f "$path" ]]; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

prerequisites
if "$CHECK_ONLY"; then
  echo
  echo "Preflight passed. Public checkout: $ROOT"
  echo "The launcher does not verify Isaac USD asset references or live YOLO data."
  exit 0
fi

# Don't silently attach to a different FastAPI process/database on port 8000.
if "$PYTHON" - <<'PY'
import socket
with socket.socket() as sock:
    sock.settimeout(0.5)
    already_listening = sock.connect_ex(('127.0.0.1', 8000)) == 0
raise SystemExit(0 if already_listening else 1)
PY
then
  echo "ERROR: port 8000 is already in use. Stop the old FastAPI server first." >&2
  exit 1
fi

ISAAC_LAUNCHER=""
if [[ "$ISAAC_MODE" != no ]]; then
  if ! ISAAC_LAUNCHER="$(find_isaac_launcher)"; then
    if [[ "$ISAAC_MODE" == yes ]]; then
      echo "ERROR: Isaac Sim launcher not found. Set ISAAC_SIM_LAUNCHER." >&2
      exit 1
    fi
    echo "NOTE: Isaac Sim launcher not found; launch the GUI manually."
  fi
fi

RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/whpv-demo.XXXXXXXX")"
export WHPV_CSV_PATH="${WHPV_CSV_PATH:-$ROOT/software/data/routes_demo.csv}"
export WHPV_DB_PATH="${WHPV_DB_PATH:-$RUN_DIR/warehouse_demo.sqlite3}"

if [[ ! -f "$WHPV_CSV_PATH" ]]; then
  echo "ERROR: CSV not found: $WHPV_CSV_PATH" >&2
  exit 1
fi
mkdir -p -- "$(dirname -- "$WHPV_DB_PATH")"

cleanup() {
  trap - EXIT
  if ((${#ALL_PIDS[@]})); then
    echo
    echo "Stopping processes started by the demo launcher..."
    local pid
    for pid in "${ALL_PIDS[@]}"; do
      kill -TERM -- "-$pid" 2>/dev/null || true
    done
    sleep 1
    for pid in "${ALL_PIDS[@]}"; do
      kill -KILL -- "-$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    done
  fi
  echo "Logs and test DB retained at: $RUN_DIR"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

start_service() {
  local label="$1"
  shift
  setsid "$@" >"$RUN_DIR/$label.log" 2>&1 &
  LAST_PID=$!
  CORE_PIDS+=("$LAST_PID")
  ALL_PIDS+=("$LAST_PID")
  printf 'Started %-9s PID %s; log: %s\n' "$label" "$LAST_PID" "$RUN_DIR/$label.log"
}

start_service backend bash -c '
  cd -- "$1"
  exec "$2" -m uvicorn whpv_backend.dashboard_app:app --host 127.0.0.1 --port 8000
' _ "$ROOT" "$PYTHON"
BACKEND_PID="$LAST_PID"

# Check real HTTP readiness so YOLO and KUKA don't connect to an absent API.
backend_ready=false
for ((attempt=0; attempt<40; attempt++)); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "ERROR: Backend exited. Last log lines:" >&2
    tail -n 25 "$RUN_DIR/backend.log" >&2
    exit 1
  fi
  if "$PYTHON" - <<'PY' >/dev/null 2>&1
from urllib.request import urlopen
try:
    with urlopen('http://127.0.0.1:8000/api/orders', timeout=1) as response:
        assert response.status == 200
except Exception:
    raise SystemExit(1)
PY
  then
    backend_ready=true
    break
  fi
  sleep 0.5
done
if [[ "$backend_ready" != true ]]; then
  echo "ERROR: Backend did not pass GET /api/orders. Log:" >&2
  tail -n 25 "$RUN_DIR/backend.log" >&2
  exit 1
fi

# Use the checkout's virtualenv Python explicitly.  The generated `ros2 run`
# entry-point can have a /usr/bin/python3 shebang even when the venv is active,
# which would make editable `whpv_core` unavailable to the detector.
start_service yolo bash -c '
  source "$1"
  source "$2"
  source "$3"
  cd -- "$4"
  exec "$5" -m whpv_perception_ros.yolo_node
' _ "$ROS_SETUP" "$VENV_ACTIVATE" "$WORKSPACE_SETUP" "$ROOT" "$PYTHON"

# Run the bridge with the same environment (ROS modules remain available
# because this venv was created with --system-site-packages).
start_service bridge bash -c '
  source "$1"
  source "$2"
  source "$3"
  cd -- "$4"
  exec "$5" "$6"
' _ "$ROS_SETUP" "$VENV_ACTIVATE" "$WORKSPACE_SETUP" "$ROOT" "$PYTHON" "$BRIDGE"

if [[ -n "$ISAAC_LAUNCHER" ]]; then
  setsid bash "$ISAAC_LAUNCHER" >"$RUN_DIR/isaac.log" 2>&1 &
  ISAAC_PID=$!
  ALL_PIDS+=("$ISAAC_PID")
  printf 'Started Isaac Sim  PID %s; log: %s\n' "$ISAAC_PID" "$RUN_DIR/isaac.log"
fi

# Catch immediately failing ROS installations/model dependencies.
sleep 2
for pid in "${CORE_PIDS[@]}"; do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "ERROR: One of the demo processes exited on startup." >&2
    echo "Review logs in $RUN_DIR" >&2
    exit 1
  fi
done

cat <<HELP

==================================================================
Warehouse Pallet Vision Demo -- services running
==================================================================
Public checkout:   $ROOT
Dashboard:         http://127.0.0.1:8000/dashboard
Fresh demo DB:     $WHPV_DB_PATH
ROS YOLO topic:    /warehouse/perception/detections_json
Snapshot file:     $ROOT/sim/isaac_sim/reports/yolo_latest.json
Logs:              $RUN_DIR/{backend,yolo,bridge}.log

Next, in Isaac Sim:
  1. Open $SCENE
  2. Press PLAY briefly; verify actual YOLO detections/snapshot.
  3. Press STOP; disable Robot Poser Track Target.
  4. Open $CONTROLLER in Script Editor.
  5. Confirm MAX_TRANSFERS=12, PLAN_ONLY=False, VISION_ENABLED=True.
  6. Run the controller; it starts its own simulation timeline.

Monitor KUKA: tail -n 0 -F "$REPORT"
Monitor ROS:  tail -f "$RUN_DIR/yolo.log" "$RUN_DIR/bridge.log"
Stop services: Ctrl+C in THIS launcher terminal.
==================================================================
HELP

# Remain in the foreground until Ctrl+C or a required service exits.
set +e
wait -n "${CORE_PIDS[@]}"
exit_code=$?
set -e
echo "A required service exited (status $exit_code); stopping this demo session." >&2
exit 1
