#!/usr/bin/env bash
# Warehouse Pallet Vision Demo — setup for Ubuntu 24.04 / ROS 2 Jazzy.
# Safe to rerun. Creates/uses only the .venv and ROS build in this checkout.
# Requires ROS 2 Jazzy, Python 3.12, and colcon to be installed already.
# Isaac Sim is installed and opened separately.

set -Eeo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ROS_SETUP="/opt/ros/jazzy/setup.bash"
VENV="$ROOT/.venv"
ROS_WS="$ROOT/sim/ros2_ws"

info() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[[ -f "$ROS_SETUP" ]] || fail "ROS 2 Jazzy not found ($ROS_SETUP). Install/source ROS 2 Jazzy first."
[[ -d "$ROOT/software" ]] || fail "Missing software/ in $ROOT. Run this script from the demo checkout."
[[ -f "$ROS_WS/src/whpv_perception_ros/package.xml" ]] || fail "Missing ROS 2 perception package in $ROS_WS."
command -v /usr/bin/python3 >/dev/null || fail "Missing /usr/bin/python3."
command -v colcon >/dev/null || fail "colcon not found. Install python3-colcon-common-extensions."

# System ROS Jazzy bindings on Ubuntu 24.04 use the system Python 3.12.
/usr/bin/python3 - <<'PY' || fail "This setup expects Ubuntu 24.04 with system Python 3.12."
import sys
assert sys.version_info[:2] == (3, 12), f"Found system Python {sys.version.split()[0]}"
PY

info "Configuring ROS 2 Jazzy environment"
# shellcheck disable=SC1091
source "$ROS_SETUP"

if [[ ! -f "$VENV/bin/activate" ]]; then
  info "Creating Python virtual environment (with ROS system-site-packages)"
  /usr/bin/python3 -m venv --system-site-packages "$VENV"
else
  info "Reusing existing virtual environment"
fi

# Without system-site-packages, ROS-installed cv_bridge/rclpy won't be visible.
if ! grep -Eq '^include-system-site-packages[[:space:]]*=[[:space:]]*true[[:space:]]*$' "$VENV/pyvenv.cfg"; then
  fail "$VENV was not created with --system-site-packages. Back it up or rename it, then rerun."
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
PYTHON="$VENV/bin/python"

# Keep pip's resolver from replacing NumPy 1.x with NumPy 2.x. The Ubuntu
# ROS Jazzy cv_bridge extension in this setup needs NumPy 1.x.
CONSTRAINTS="$(mktemp "${TMPDIR:-/tmp}/whpv-constraints.XXXXXXXX.txt")"
trap 'rm -f -- "$CONSTRAINTS"' EXIT
cat > "$CONSTRAINTS" <<'PINS'
numpy==1.26.4
opencv-python==4.10.0.84
setuptools>=68,<80
PINS

info "Installing compatible NumPy, OpenCV, and Python tooling"
"$PYTHON" -m pip install -c "$CONSTRAINTS" \
  "numpy==1.26.4" "opencv-python==4.10.0.84" \
  "setuptools>=68,<80" wheel cffi

info "Installing shared detection/backend software and web server"
# whpv-core declares ultralytics as a dependency; pip installs it here.
"$PYTHON" -m pip install -c "$CONSTRAINTS" \
  -e "$ROOT/software" fastapi uvicorn

info "Building ROS 2 perception package"
(
  cd -- "$ROS_WS"
  colcon build --symlink-install --packages-select whpv_perception_ros
)
# shellcheck disable=SC1091
source "$ROS_WS/install/setup.bash"

info "Checking imports and actual ROS image conversion"
"$PYTHON" - <<'PY'
import numpy
import cv2
import whpv_core
import whpv_backend
import ultralytics
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
import whpv_perception_ros.yolo_node
import whpv_perception_ros.order_matching_node
import whpv_perception_ros.visualization_node

assert numpy.__version__ == '1.26.4', numpy.__version__
assert cv2.__version__.startswith('4.10.'), cv2.__version__

msg = Image()
msg.height, msg.width = 1, 1
msg.encoding, msg.step = 'rgb8', 3
msg.data = bytes([255, 0, 0])
converted = CvBridge().imgmsg_to_cv2(msg, desired_encoding='bgr8')
assert converted.shape == (1, 1, 3), converted.shape
print(f'PASS: NumPy {numpy.__version__}, OpenCV {cv2.__version__}')
print('PASS: cv_bridge conversion and YOLO/matcher/overlay imports')
PY

info "Checking installed package dependencies"
if ! "$PYTHON" -m pip check; then
  printf '\nWARNING: pip reports dependency conflicts. Resolve them before publishing\n' >&2
  printf 'the setup as fully reproducible. NumPy/cv_bridge checks above passed.\n' >&2
fi

info "Checking launcher prerequisites"
if [[ -f "$ROOT/scripts/launch_demo.sh" ]]; then
  bash "$ROOT/scripts/launch_demo.sh" --check
else
  printf 'WARNING: scripts/launch_demo.sh was not found.\n' >&2
fi

cat <<DONE

Setup complete in: $ROOT

Run services (opens Isaac Sim separately):
  cd "$ROOT"
  ./scripts/launch_demo.sh --no-isaac

Dashboard: http://127.0.0.1:8000/dashboard
Driver overlay ROS topic: /warehouse/visualization/driver_overlay
To view it while the camera publishes:
  source /opt/ros/jazzy/setup.bash
  source "$ROS_WS/install/setup.bash"
  ros2 run rqt_image_view rqt_image_view

Note: The first YOLO launch may download the public yolo11n.pt model
if it is not cached; internet access may be needed for that first run.
Isaac Sim must be installed and started separately.
DONE
