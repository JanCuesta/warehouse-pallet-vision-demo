"""
Warehouse Pallet Vision Demo
============================

KUKA KR210 robotic sorting with YOLO and FastAPI/SQLite.

WORKFLOW
--------
1. Read outstanding product requirements from the FastAPI backend.
2. Select the next box from a fixed top-to-bottom pickup sequence.
3. Confirm the expected product using fresh YOLO camera detections.
4. Select an eligible destination driver and its next free pallet slot.
5. Execute the predefined KUKA pick-and-place movement.
6. Increment the corresponding completed quantity in the backend.

DESIGN
------
- The robot uses saved named PICK and PLACE poses in Isaac Sim.
- YOLO validates visible products; it does not compute 3D grasp poses.
- Pickup order and physical box locations are predefined.
- Destination assignment depends on outstanding order requirements.
- Robot control runs directly in Isaac Sim, not through a ROS 2
  robot-command bridge.
- ROS 2 is used for camera perception and the YOLO snapshot bridge.

EXECUTION
---------
- Start the FastAPI server, YOLO detector, and snapshot bridge.
- Open the validated USD scene in Isaac Sim.
- Stop the simulation and disable Robot Poser Track Target.
- Run this script using the Isaac Sim Script Editor.
- Do not save the USD scene after boxes have moved.

LIMITATIONS
-----------
This is a controlled simulation demonstration, not a production
warehouse robotics system.

Movement uses predefined poses and interpolated joint targets.
Successful command execution does not independently prove grasp
or placement success. No general collision-free motion planning,
3D grasp localization, or production safety control is provided.
"""

import asyncio
import json
import traceback
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from pathlib import Path

import numpy as np
import omni.kit.app
import omni.timeline
import omni.usd
from pxr import Gf, Usd, UsdGeom
from isaacsim.robot.poser import get_named_pose, list_named_poses
from isaacsim.robot.poser.math import Transform
try:
    from isaacsim.robot.poser import RobotPoser
except ImportError:
    from isaacsim.robot.poser.robot_poser import RobotPoser
from isaacsim.robot.surface_gripper import _surface_gripper
from isaacsim.core.prims import SingleArticulation
from isaacsim.core.utils.types import ArticulationAction



# =====================================================================
# 1. PROJECT PATHS
# =====================================================================

# Absolute path to the PUBLIC repository checkout.
# Update this to match your local installation.
PROJECT_ROOT = Path.home() / "projects/warehouse-pallet-vision-demo"

# Generated files shared between the YOLO bridge and KUKA controller.
VISION_SNAPSHOT_PATH = (
    PROJECT_ROOT / "sim/isaac_sim/reports/yolo_latest.json"
)

OUTPUT = (
    PROJECT_ROOT / "sim/isaac_sim/reports/"
    "kuka_all_boxes_backend_counts_report.txt"
)


# =====================================================================
# 2. DEMONSTRATION EXECUTION
# =====================================================================

MAX_TRANSFERS = 12
# Maximum number of remaining boxes to process in this run.

PLAN_ONLY = False
# True: show the planned transfers without moving the robot
# or updating the backend.

RESUME_FROM_DRIVER_COUNTS = True
# True: skip the first N boxes when the database already records
# N completed boxes. Use only when the simulated scene reflects
# the same physical progress as the backend.


# =====================================================================
# 3. BACKEND AND PALLET CAPACITY
# =====================================================================

BACKEND_URL = "http://127.0.0.1:8000"
# Local FastAPI server used for orders and completed quantities.

BACKEND_TIMEOUT_SECONDS = 2.0
# HTTP request timeout in seconds.

CAPACITY_PER_DRIVER = 4
# Maximum boxes placed on each destination pallet.

DRIVER_NAMES = {
    "A": "Driver A",
    "B": "Driver B",
    "C": "Driver C",
}


# =====================================================================
# 4. FIXED INCOMING BOX SEQUENCE
# =====================================================================

# The incoming pallet has 3 layers and 4 columns.
# Pick top layer first, then middle, then bottom.
#
# Box names must match both the USD scene and saved PICK pose names.

SOURCE_BOXES = [
    # Top layer
    "box_09_orange",
    "box_10_apple",
    "box_11_banana",
    "box_12_orange",

    # Middle layer
    "box_05_banana",
    "box_06_orange",
    "box_07_apple",
    "box_08_banana",

    # Bottom layer
    "box_01_apple",
    "box_02_banana",
    "box_03_orange",
    "box_04_apple",
]


# =====================================================================
# 5. OPTIONAL INTERMEDIATE ROBOT POSES
# =====================================================================

# These switches control which named waypoints the robot visits.
# False skips the waypoint but preserves PICK/PLACE movements.

GO_HOME = False
# Visit HOME at startup and between pickup/placement movements.

GO_INCOMING = False
# Visit INC before and after each pickup.

GO_PALLET = {
    "A": False,
    "B": False,
    "C": False,
}
# Visit the corresponding PALLET_A/B/C waypoint around placement.


# =====================================================================
# 6. ROBOT MOVEMENT DURATIONS
# =====================================================================

# All durations are in simulated seconds.
# Lower duration = faster commanded motion.
# These are NOT joint velocities in radians per second.

HOME_MOVE_SECONDS = 3.0
# Time to move to the HOME waypoint.

INCOMING_MOVE_SECONDS = 3.0
# Time to move to the incoming pallet waypoint.

PALLET_MOVE_SECONDS = {
    "A": 2.5,
    "B": 2.5,
    "C": 2.5,
}
# Time to reach each pallet waypoint when enabled.

PICK_ABOVE_MOVE_SECONDS = 3.0
# Time to travel toward the raised PICK approach pose.

PLACE_ABOVE_MOVE_SECONDS = 3.0
# Time to travel toward the raised PLACE approach pose.

VERTICAL_TRAVEL_SECONDS = 1.5
# Duration of each vertical descent or ascent.

GRIP_HOLD_SECONDS = 1.0
# Wait after activating or releasing the suction gripper.

PHYSICS_STARTUP_SECONDS = 0.30
# Initial simulation settling time before robot movement.


# =====================================================================
# 7. PICK AND PLACE APPROACH HEIGHTS
# =====================================================================

APPROACH_HEIGHT_M = 0.5
# Vertical clearance above each saved PICK pose, in metres.

PLACE_APPROACH_HEIGHT_M = 1.0
# Vertical clearance above each saved PLACE pose, in metres.
# Both approach and retreat use their corresponding height.


# =====================================================================
# 8. YOLO DETECTION VALIDATION
# =====================================================================

VISION_ENABLED = True
# Require YOLO validation before each pickup.

VISION_MIN_CONFIDENCE = 0.50
# Minimum accepted YOLO confidence, from 0.0 to 1.0.

VISION_CONFIRM_FRAMES = 2
# Number of fresh matching detection messages required.

VISION_FRAME_MAX_AGE_S = 3.0
# Maximum age of a camera detection snapshot in seconds.

VISION_WAIT_TIMEOUT_S = 20.0
# Maximum wall-clock time to wait for a valid detection.

VISION_COLUMN_QUADRANTS = {
    1: "bottom_left",
    2: "bottom_right",
    3: "top_left",
    4: "top_right",
}
# Maps the four fixed box columns to overhead-camera image regions.

VISION_MANUAL_GRID = None
# None: automatically calibrate the grid from four visible boxes.
# Can be replaced with calibrated normalized grid coordinates.


# =====================================================================
# 9. ISAAC SIM SCENE PATHS
# =====================================================================

ROBOT_PATH = "/World/Kuka_KR210"

GRIPPER_PATH = ROBOT_PATH + "/tool0/SurfaceGripper"

GRIPPER_ATTACHMENT_PATH = (
    ROBOT_PATH + "/tool0/surface_gripper/suction_joint"
)

BOXES_PATH = "/World/Boxes"

JOINT_NAMES = tuple(f"joint_a{i}" for i in range(1, 7))


# =====================================================================
# 10. SCENE GEOMETRY VALIDATION
# =====================================================================

BOX_HEIGHT_M = 0.25
# Expected simulated box height, in metres.

BOX_HEIGHT_TOL_M = 0.006
# Allowed deviation when validating box geometry.


# =====================================================================
# 11. GENERATED APPROACH WAYPOINTS
# =====================================================================

# Derived from the configured PICK and PLACE approach heights.
# These should normally not require manual modification.

LOW_TO_HIGH_OFFSETS_M = tuple(
    round(APPROACH_HEIGHT_M * fraction, 4)
    for fraction in (0.05, 0.50, 1.00)
)

PLACE_LOW_TO_HIGH_OFFSETS_M = tuple(
    round(PLACE_APPROACH_HEIGHT_M * fraction, 4)
    for fraction in (0.05, 0.50, 1.00)
)




# =====================================================================
# CODE
# =====================================================================

def offsets_for_pose(pose_name):
    return (PLACE_LOW_TO_HIGH_OFFSETS_M if pose_name.startswith("PLACE_")
            else LOW_TO_HIGH_OFFSETS_M)


class OrderBackend:
    """Small HTTP wrapper for the dashboard's existing FastAPI endpoints."""

    def __init__(self, base_url, timeout):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request_json(self, path, method="GET", data=None):
        payload = None if data is None else json.dumps(data).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = Request(self.base_url + path, data=payload,
                      headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout) as response:
                return json.load(response)
        except (URLError, HTTPError, ValueError) as exc:
            raise RuntimeError(
                f"FastAPI {method} {path} failed: {exc}. "
                f"Start the dashboard at {self.base_url}"
            ) from exc

    def orders(self):
        return self.request_json("/api/orders")

    def complete_one(self, requirement_id, new_quantity):
        response = self.request_json(
            f"/api/requirements/{requirement_id}", method="PATCH",
            data={"completed_quantity": new_quantity},
        )
        if (type(response.get("completed_quantity")) is not int or
                response["completed_quantity"] != new_quantity):
            raise RuntimeError("Backend returned an unexpected completed quantity")
        return response


def flatten_orders(tree):
    """Convert /api/orders tree to rows + driver completed totals.

    The demo is explicitly three drivers with four requested boxes each.
    """
    if not isinstance(tree, dict) or not isinstance(tree.get("drivers"), list):
        raise ValueError("Unexpected /api/orders response")

    rows = []
    counts = {}
    totals = {}
    for driver in tree["drivers"]:
        name = driver["driver"]
        if name not in DRIVER_NAMES.values() or name in counts:
            raise ValueError(f"Unexpected/duplicated demo driver: {name}")
        counts[name] = driver["completed_quantity"]
        totals[name] = driver["required_quantity"]
        for client in driver["clients"]:
            for order in client["orders"]:
                for req in order["requirements"]:
                    row = dict(req)
                    if row["driver"] != name or row["client"] != client["client"]:
                        raise ValueError("Inconsistent requirement driver or client")
                    if row["order_id"] != order["order_id"]:
                        raise ValueError("Inconsistent order_id")
                    rows.append(row)

    if set(counts) != set(DRIVER_NAMES.values()):
        raise ValueError("The demo requires Driver A, Driver B and Driver C")
    for name in counts:
        if (type(counts[name]) is not int or type(totals[name]) is not int or
                not 0 <= counts[name] <= totals[name] or
                totals[name] != CAPACITY_PER_DRIVER):
            raise ValueError(
                f"{name}: expected exactly {CAPACITY_PER_DRIVER} required boxes, "
                f"got required={totals[name]}, completed={counts[name]}"
            )
    for r in rows:
        if (type(r.get("id")) is not int or
                type(r.get("required_quantity")) is not int or
                type(r.get("completed_quantity")) is not int or
                not 0 <= r["completed_quantity"] <= r["required_quantity"]):
            raise ValueError(f"Invalid requirement in /api/orders: {r}")
    for name in counts:
        if sum(r["completed_quantity"] for r in rows if r["driver"] == name) != counts[name]:
            raise ValueError(f"Inconsistent completed total for {name}")
    return rows, counts


def plan_from_counts(source_boxes, rows, counts):
    """Simple deterministic assignment. Pure Python: no Isaac dependencies.

    Choose the first alphabetic eligible driver with room, then the first
    client/order with remaining demand. Slot number is completed count + 1.
    """
    quantities = {r["id"]: r["completed_quantity"] for r in rows}
    slots_used = dict(counts)
    plan = []
    for source_box in source_boxes:
        product = source_box.rsplit("_", 1)[-1].lower()
        candidates = sorted(
            (r for r in rows
             if r["product"].strip().lower() == product
             and quantities[r["id"]] < r["required_quantity"]
             and slots_used[r["driver"]] < CAPACITY_PER_DRIVER),
            key=lambda r: (r["driver"], r["client"],
                           r["order_id"] or "", r["id"]),
        )
        if not candidates:
            raise ValueError(
                f"No remaining order/capacity for {source_box} ({product}). "
                "Check the demo database and box list."
            )
        r = candidates[0]
        name = r["driver"]
        slot = slots_used[name] + 1
        letter = next(k for k, v in DRIVER_NAMES.items() if v == name)
        plan.append({
            "driver": letter,
            "slot": slot,
            "source_box": source_box,
            "requirement_id": r["id"],
            "client": r["client"],
            "order_id": r["order_id"],
            "product": product,
            "expected_completed": quantities[r["id"]],
            "expected_driver_count": slots_used[name],
        })
        quantities[r["id"]] += 1
        slots_used[name] += 1
    return plan


def get_run_plan(backend):
    rows, counts = flatten_orders(backend.orders())
    completed_total = sum(counts.values())
    if RESUME_FROM_DRIVER_COUNTS:
        # Only valid if physical boxes were already moved in this fixed order.
        sources = SOURCE_BOXES[completed_total:]
    else:
        if completed_total != 0:
            raise RuntimeError(
                "Backend has completed units, but RESUME_FROM_DRIVER_COUNTS=False. "
                "Use a fresh demo DB before starting from the original USD scene."
            )
        sources = SOURCE_BOXES

    chosen_sources = sources[:MAX_TRANSFERS]
    plan = plan_from_counts(chosen_sources, rows, counts)
    return plan, counts


def names_for_transfer(driver, slot, source_box):
    pick = "PICK_" + source_box.removeprefix("box_")
    place = f"PLACE_{driver}_{slot:02d}"
    return pick, place


def to_joint_dict(result):
    """Robot Poser returns full joint prim paths; articulation uses DOF names."""
    converted = {}
    for path, value in result.joints.items():
        name = str(path).rsplit("/", 1)[-1]
        if name in converted:
            raise RuntimeError(f"Duplicated joint name: {name}")
        converted[name] = float(value)
    if set(converted) != set(JOINT_NAMES):
        raise RuntimeError(f"Unexpected pose joint names: {sorted(converted)}")
    if not all(np.isfinite(v) for v in converted.values()):
        raise RuntimeError("Non-finite IK joint value")
    return converted


def calculate_vertical_offsets(stage, robot_prim, saved, pose_name):
    """IK for same XY and same rotation, +Z world offset from saved pose."""
    if not saved.start_link or not saved.end_link:
        raise RuntimeError(f"{pose_name} has no saved start/end link")
    if saved.target_position is None or saved.target_orientation is None:
        raise RuntimeError(f"{pose_name} has no saved Cartesian target")

    start_prim = stage.GetPrimAtPath(saved.start_link)
    end_prim = stage.GetPrimAtPath(saved.end_link)
    if not start_prim.IsValid() or not end_prim.IsValid():
        raise RuntimeError(f"{pose_name} has invalid start/end links")

    poser = RobotPoser(stage, robot_prim, start_prim, end_prim)
    pose_t = np.array(saved.target_position, dtype=np.float64)
    pose_q = np.array(saved.target_orientation, dtype=np.float64)

    # Robot Poser solves in the base-link coordinate frame. Convert global
    # vertical (+world Z) into that frame so offset is truly world-vertical.
    stage_m_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
    base_world = UsdGeom.XformCache(Usd.TimeCode.Default()).GetLocalToWorldTransform(start_prim)
    base_up = base_world.GetInverse().TransformDir(Gf.Vec3d(0.0, 0.0, 1.0))
    world_up_in_base = np.array([base_up[0], base_up[1], base_up[2]], dtype=float)
    if not np.isfinite(world_up_in_base).all() or np.linalg.norm(world_up_in_base) < 1e-10:
        raise RuntimeError("Could not compute vertical axis in the robot base")
    world_up_in_base /= np.linalg.norm(world_up_in_base)

    calculated = {}
    seed = saved.joints
    for offset_m in offsets_for_pose(pose_name):
        offset_stage = offset_m / stage_m_per_unit
        raised_t = pose_t + world_up_in_base * offset_stage
        raised_target = Transform(t=raised_t, q=pose_q)
        result = poser.solve_ik(
            raised_target, seed=seed, tolerance=0.005, iters=120,
            null_space_bias=0.0,
        )
        if not result.success:
            raise RuntimeError(
                f"IK FAILED for {pose_name} + {offset_m:.2f} m. "
                "The clearance waypoint may be unreachable with this orientation; "
                "no robot motion has been started."
            )
        calculated[offset_m] = to_joint_dict(result)
        seed = result.joints
        print(f"[KUKA preflight] IK OK: {pose_name} + {offset_m:.2f} m")
    return calculated


def preflight(stage, transfers):
    """Validate and precompute all necessary IK poses before starting physics."""
    if not 1 <= MAX_TRANSFERS <= len(SOURCE_BOXES):
        raise ValueError(f"MAX_TRANSFERS must be between 1 and {len(SOURCE_BOXES)}")
    if not transfers:
        raise ValueError("No transfers selected: all boxes may already be completed")
    if not np.isfinite(APPROACH_HEIGHT_M) or APPROACH_HEIGHT_M <= 0:
        raise ValueError("APPROACH_HEIGHT_M must be positive")
    if not np.isfinite(PLACE_APPROACH_HEIGHT_M) or PLACE_APPROACH_HEIGHT_M <= 0:
        raise ValueError("PLACE_APPROACH_HEIGHT_M must be positive")
    durations = [HOME_MOVE_SECONDS, INCOMING_MOVE_SECONDS,
                 PICK_ABOVE_MOVE_SECONDS, PLACE_ABOVE_MOVE_SECONDS,
                 VERTICAL_TRAVEL_SECONDS, GRIP_HOLD_SECONDS,
                 PHYSICS_STARTUP_SECONDS]
    if set(GO_PALLET) != {"A", "B", "C"}:
        raise ValueError("GO_PALLET must define A, B and C")
    durations.extend(PALLET_MOVE_SECONDS.values())
    if set(PALLET_MOVE_SECONDS) != {"A", "B", "C"}:
        raise ValueError("PALLET_MOVE_SECONDS must define A, B and C")
    if any(not np.isfinite(s) or s <= 0 for s in durations):
        raise ValueError("All movement durations must be positive finite numbers")
    if not all(type(v) is bool for v in [GO_HOME, GO_INCOMING, *GO_PALLET.values()]):
        raise ValueError("GO_HOME, GO_INCOMING and GO_PALLET must be booleans")

    chosen = transfers
    required = set()
    if GO_HOME:
        required.add("HOME")
    if GO_INCOMING:
        required.add("INC")
    for driver, slot, source_box in chosen:
        if driver not in {"A", "B", "C"} or not 1 <= slot <= 4:
            raise ValueError(f"Invalid transfer destination: {driver} slot {slot}")
        if not source_box.startswith("box_"):
            raise ValueError(f"Invalid source box: {source_box}")
        pick, place = names_for_transfer(driver, slot, source_box)
        required.update((pick, place))
        if GO_PALLET[driver]:
            required.add("PALLET_" + driver)

    for path in (ROBOT_PATH, GRIPPER_PATH, GRIPPER_ATTACHMENT_PATH):
        if not stage.GetPrimAtPath(path).IsValid():
            raise RuntimeError(f"Missing prim: {path}")
    axis = stage.GetPrimAtPath(GRIPPER_ATTACHMENT_PATH).GetAttribute(
        "isaac:forwardAxis"
    ).Get()
    if axis != "X":
        raise RuntimeError(f"Expected working suction axis X; got {axis}")

    robot_prim = stage.GetPrimAtPath(ROBOT_PATH)
    registered = set(list_named_poses(stage, robot_prim))
    missing = sorted(required - registered)
    if missing:
        raise RuntimeError(f"Missing saved poses: {missing}")

    named = {}
    saved_results = {}
    for name in sorted(required):
        stored = get_named_pose(stage, robot_prim, name)
        if stored is None or not stored.success or not stored.joints:
            raise RuntimeError(f"Invalid saved pose: {name}")
        named[name] = to_joint_dict(stored)
        saved_results[name] = stored

    bbox_cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render]
    )
    for _, _, source_box in chosen:
        body = stage.GetPrimAtPath(f"{BOXES_PATH}/{source_box}/Body")
        if not body.IsValid():
            raise RuntimeError(f"Missing box body: {source_box}")
        bound = bbox_cache.ComputeWorldBound(body).ComputeAlignedRange()
        height = float(bound.GetMax()[2] - bound.GetMin()[2]) * float(
            UsdGeom.GetStageMetersPerUnit(stage)
        )
        if abs(height - BOX_HEIGHT_M) > BOX_HEIGHT_TOL_M:
            raise RuntimeError(
                f"{source_box}: box height {height:.3f} m, "
                f"expected {BOX_HEIGHT_M:.3f} m"
            )

    offsets = {}
    for driver, slot, source_box in chosen:
        pick, place = names_for_transfer(driver, slot, source_box)
        for name in (pick, place):
            if name not in offsets:
                offsets[name] = calculate_vertical_offsets(
                    stage, robot_prim, saved_results[name], name
                )
    return named, offsets


async def run_all_transfers(stage, named, offsets, plan, backend, initial_counts):
    app = omni.kit.app.get_app()
    timeline = omni.timeline.get_timeline_interface()
    lines = []

    def log(message):
        full = "[KUKA backend demo] " + message
        print(full)
        lines.append(full)
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    async def wait_sim(seconds):
        start = float(timeline.get_current_time())
        frame_count = 0
        while float(timeline.get_current_time()) - start < seconds:
            await app.next_update_async()
            frame_count += 1
            if not timeline.is_playing():
                raise RuntimeError("Simulation was paused/stopped during transfer")
            if frame_count > 3000:
                raise RuntimeError("Simulation timeline did not advance")

    try:
        timeline.set_end_time(max(
            float(timeline.get_end_time()),
            float(timeline.get_current_time()) + 2400.0,
        ))
        timeline.play()
        await wait_sim(PHYSICS_STARTUP_SECONDS)
        active_stage = omni.usd.get_context().get_stage()
        if active_stage is None or active_stage.GetRootLayer().identifier != stage.GetRootLayer().identifier:
            raise RuntimeError("USD stage changed during startup")

        arm = SingleArticulation(
            prim_path=ROBOT_PATH, name="warehouse_kr210_vertical_test_controller"
        )
        arm.initialize()
        actual_dofs = set(arm.dof_names or [])
        if not set(JOINT_NAMES).issubset(actual_dofs):
            raise RuntimeError(f"Unexpected robot DOFs: {sorted(actual_dofs)}")
        indices = np.array([arm.get_dof_index(n) for n in JOINT_NAMES], dtype=np.int64)
        gripper = _surface_gripper.acquire_surface_gripper_interface()
        gripper.open_gripper(GRIPPER_PATH)

        def joint_array(joints):
            return np.array([joints[n] for n in JOINT_NAMES], dtype=float)

        def actual_joint_array():
            # Start each trajectory from the measured simulated configuration,
            # not the last commanded target (which may not have been reached).
            joints = arm.get_joint_positions()
            if joints is None:
                raise RuntimeError("Cannot read actual KUKA joint positions")
            values = np.asarray(joints, dtype=float)[indices]
            if not np.isfinite(values).all():
                raise RuntimeError("Non-finite actual joint positions")
            return values

        async def follow_joint_path(points, label, seconds):
            """Stream position targets every simulation update (no waypoint holds).

            A single quintic ease-in/out is applied to the *whole path*.
            Linear interpolation between IK knots keeps the implementation
            minimal, though it does not guarantee exact Cartesian straightness
            or perfectly smooth joint velocity at internal knot boundaries.
            """
            if seconds <= 0:
                raise ValueError("Trajectory duration must be positive")
            q = np.stack(points)
            if not np.isfinite(q).all() or len(q) < 2:
                raise RuntimeError("Invalid joint trajectory")
            log(f"MOVE {label} ({seconds:.1f}s, {len(q)} knots)")
            started = float(timeline.get_current_time())
            frame_count = 0
            while True:
                if not timeline.is_playing():
                    raise RuntimeError("Simulation stopped during trajectory")
                elapsed = float(timeline.get_current_time()) - started
                u = min(1.0, max(0.0, elapsed / seconds))
                # Quintic time scaling: zero velocity and acceleration at ends.
                eased = 10*u**3 - 15*u**4 + 6*u**5
                segment_position = eased * (len(q) - 1)
                i = min(len(q) - 2, int(segment_position))
                fraction = segment_position - i
                target = q[i] * (1.0 - fraction) + q[i + 1] * fraction
                arm.apply_action(ArticulationAction(
                    joint_positions=target, joint_indices=indices
                ))
                if u >= 1.0:
                    # Let physics consume the final position command once.
                    await app.next_update_async()
                    break
                await app.next_update_async()
                frame_count += 1
                if frame_count > 3000:
                    raise RuntimeError("Simulation timeline did not advance")

        async def move_joints(joints, label, seconds):
            await follow_joint_path(
                [actual_joint_array(), joint_array(joints)], label, seconds
            )

        async def move_named(name, seconds):
            await move_joints(named[name], name, seconds)

        async def approach(pose_name, to_raised_seconds):
            pose_offsets = offsets_for_pose(pose_name)
            high = pose_offsets[-1]
            await move_joints(offsets[pose_name][high],
                              f"{pose_name} + {high:.2f}m", to_raised_seconds)
            # From the raised point down to PICK/PLACE in one continuous leg.
            lower = list(reversed(pose_offsets[:-1]))
            waypoints = [actual_joint_array()] + [
                joint_array(offsets[pose_name][h]) for h in lower
            ] + [joint_array(named[pose_name])]
            await follow_joint_path(waypoints, f"DESCEND {pose_name}",
                                    VERTICAL_TRAVEL_SECONDS)

        async def retreat(pose_name):
            # The robot has just gripped/released at the saved PICK/PLACE pose.
            waypoints = [actual_joint_array()] + [
                joint_array(offsets[pose_name][h]) for h in offsets_for_pose(pose_name)
            ]
            await follow_joint_path(waypoints, f"ASCEND {pose_name}",
                                    VERTICAL_TRAVEL_SECONDS)

        log(f"START: {len(plan)} transfer(s), driven by FastAPI quantities")
        log(f"INITIAL COUNTS: {initial_counts}")
        log(f"WAYPOINTS: HOME={GO_HOME}, INC={GO_INCOMING}, PALLET={GO_PALLET}")
        log("Times: HOME={:.2f}s INC={:.2f}s PALLET={} PICK-above={:.2f}s PLACE-above={:.2f}s vertical={:.2f}s".format(
            HOME_MOVE_SECONDS, INCOMING_MOVE_SECONDS, PALLET_MOVE_SECONDS,
            PICK_ABOVE_MOVE_SECONDS, PLACE_ABOVE_MOVE_SECONDS,
            VERTICAL_TRAVEL_SECONDS))

        expected_counts = dict(initial_counts)
        if GO_HOME:
            await move_named("HOME", HOME_MOVE_SECONDS)

        for transfer_index, transfer in enumerate(plan, start=1):
            driver = transfer["driver"]
            slot = transfer["slot"]
            source_box = transfer["source_box"]
            requirement_id = transfer["requirement_id"]
            pick, place = names_for_transfer(driver, slot, source_box)

            # Ensure dashboard data was not edited while this sequence ran.
            live_rows, live_counts = flatten_orders(backend.orders())
            if live_counts != expected_counts:
                raise RuntimeError(
                    "Backend counts changed outside this robot script: "
                    f"expected {expected_counts}, found {live_counts}. "
                    "Stopping before the next movement."
                )
            matching = [r for r in live_rows if r["id"] == requirement_id]
            if (len(matching) != 1 or
                    matching[0]["completed_quantity"] != transfer["expected_completed"] or
                    matching[0]["product"].strip().lower() != transfer["product"]):
                raise RuntimeError(
                    f"Requirement {requirement_id} changed; stopping before movement"
                )
            log(
                f"[{transfer_index:02d}/{len(plan):02d}] {source_box} "
                f"-> Driver {driver} slot {slot:02d}, "
                f"{transfer['client']} / {transfer['order_id']} "
                f"(requirement {requirement_id})"
            )

            # PICK: same working optional waypoints + smooth vertical path.
            if GO_INCOMING:
                await move_named("INC", INCOMING_MOVE_SECONDS)
            log("STATUS: PICKING")
            await approach(pick, PICK_ABOVE_MOVE_SECONDS)
            gripper.close_gripper(GRIPPER_PATH)
            log("GRIP: close and hold")
            await wait_sim(GRIP_HOLD_SECONDS)
            await retreat(pick)
            if GO_INCOMING:
                await move_named("INC", INCOMING_MOVE_SECONDS)
            if GO_HOME:
                await move_named("HOME", HOME_MOVE_SECONDS)

            # PLACE: destination pallet and slot are chosen from SQLite counts.
            if GO_PALLET[driver]:
                await move_named("PALLET_" + driver, PALLET_MOVE_SECONDS[driver])
            log("STATUS: PLACING")
            await approach(place, PLACE_ABOVE_MOVE_SECONDS)
            gripper.open_gripper(GRIPPER_PATH)
            log("RELEASE: open and hold")
            await wait_sim(GRIP_HOLD_SECONDS)
            await retreat(place)
            if GO_PALLET[driver]:
                await move_named("PALLET_" + driver, PALLET_MOVE_SECONDS[driver])
            if GO_HOME:
                await move_named("HOME", HOME_MOVE_SECONDS)

            # IMPORTANT: update only AFTER the full transfer was commanded.
            # In this demo, a completed commanded movement counts as one box.
            # The current script does not physically verify suction/placement.
            new_qty = transfer["expected_completed"] + 1
            try:
                backend.complete_one(requirement_id, new_qty)
            except Exception as exc:
                raise RuntimeError(
                    f"ROBOT MOVED {source_box} but DB update FAILED: {exc}. "
                    "Inspect scene and dashboard; do not rerun blindly."
                ) from exc
            expected_counts[DRIVER_NAMES[driver]] += 1
            log(f"DB UPDATED: Driver {driver} {expected_counts[DRIVER_NAMES[driver]]}/4, "
                f"requirement {requirement_id}: {new_qty}")
            log(f"DONE [{transfer_index:02d}/{len(plan):02d}] (commanded)")

        timeline.pause()
        log(f"STATUS: FINISHED — {len(plan)} transfers commanded and counted")
        log("Inspect scene. Press STOP to reset physics, and don't save moved boxes.")
    except Exception as exc:
        if timeline.is_playing():
            timeline.pause()
        log("STATUS: FAILED — " + str(exc))
        log(traceback.format_exc())
        log("Timeline PAUSED. Inspect the scene, then press STOP to reset.")


def main():
    previous = globals().get("KUKA_ALL_BOXES_TASK")
    if previous is not None and not previous.done():
        raise RuntimeError("All-boxes KUKA transfer task already running")
    timeline = omni.timeline.get_timeline_interface()
    if timeline.is_playing():
        raise RuntimeError("Press STOP before launching this test")
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("No USD stage open")
    backend = OrderBackend(BACKEND_URL, BACKEND_TIMEOUT_SECONDS)
    plan, counts = get_run_plan(backend)
    if not plan:
        print("[KUKA demo] All 12 boxes already completed in backend; no transfer needed")
        return None
    for item in plan:
        print(f"[KUKA plan] {item['source_box']} -> {item['driver']}{item['slot']:02d} "
              f"(requirement {item['requirement_id']})")
    if PLAN_ONLY:
        print("[KUKA demo] PLAN_ONLY=True; no physics, motion or database updates")
        return None
    print(f"[KUKA demo] Precomputing IK for {len(plan)} planned transfers...")
    named, offsets = preflight(stage, [
        (item["driver"], item["slot"], item["source_box"]) for item in plan
    ])
    print(f"[KUKA demo] PREFLIGHT OK — starting {len(plan)} transfers")
    return asyncio.ensure_future(run_all_transfers(
        stage, named, offsets, plan, backend, counts
    ))


KUKA_ALL_BOXES_TASK = main()




