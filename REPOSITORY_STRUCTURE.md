# Repository Structure — Warehouse Pallet Vision Demo

**Status:** Current public development snapshot (not a production release).

This document describes the **published demonstration repository** and the division of responsibilities. The original development workspace contains additional KUKA movement/calibration scripts and internal notes that are intentionally absent from this public snapshot.

## Layout

```text
warehouse-pallet-vision-demo/
├── README.md
├── REPOSITORY_STRUCTURE.md
├── previews/                              # Development screenshots
├── software/
│   ├── pyproject.toml
│   ├── data/                               # Fictional order CSVs and optional sample DB
│   ├── models/                             # Optional local model assets
│   ├── src/
│   │   ├── whpv_core/                     # Detection, matching, visualization, types
│   │   └── whpv_backend/                  # FastAPI, SQLite, dashboard, services
│   └── tests/                              # Python tests
└── sim/
    ├── isaac_sim/
    │   ├── assets/textures/               # Fruit/sign textures
    │   ├── scenes/Worlds/                 # USD scenes, including Same_zize_boxes.usd
    │   └── reports/                       # Optional generated development reports
    └── ros2_ws/
        ├── src/whpv_perception_ros/        # ROS 2 perception/matching adapters
        ├── src/whpv_bringup/              # Placeholder for integrated bringup
        └── src/whpv_robot_bridge/         # Placeholder; command bridge not complete
```

Some directories may contain placeholders or experimental files. Scene paths should be treated as **Isaac Sim assets**, not as a standalone runnable robotics application.

## Ownership and boundaries

| Component | Location | Responsibility |
| --- | --- | --- |
| Reusable detection and matching logic | `software/src/whpv_core/` | Image-array detection, eligible driver/client matching, 2D overlays and shared types; no Isaac/ROS dependencies in the core |
| Application API and state | `software/src/whpv_backend/` | FastAPI endpoints, SQLite persistence, order/count services and dashboard |
| Demo scenarios | `software/data/` | Synthetic CSV orders and optional local example database; not real customer data |
| Software verification | `software/tests/` | Core/backend/UI and integration test coverage |
| ROS 2 adapters | `sim/ros2_ws/src/whpv_perception_ros/` | Image transport, YOLO output and adapters to the shared core |
| Scene and visual assets | `sim/isaac_sim/` | Simulator scenes, pallet/box assets, textures and visual references |
| KUKA manipulation | Not yet included | Independently developed Isaac controller using saved poses and suction gripper; full tested release pending |
| Robot command bridge | Planned | End-to-end source-selection/command/feedback integration is not complete |

## Data paths

**Perception and matching:**

```text
Isaac Sim RGB -> ROS 2 -> YOLO class + bbox
                          -> candidate driver/client matches
                          -> annotated camera view
```

**Local orders and completion progress:**

```text
Fictional CSV -> FastAPI/SQLite -> driver / client / order requirements
                                     -> completed and remaining quantities
                                     -> operations dashboard
```

**Robot simulation (under integration):**

```text
Known source box / saved PICK pose -> KUKA transfer -> PLACE pose
                    -> API requirement completion update
```

The current robot transfer script uses a **predefined box sequence**, and the planned YOLO verification of expected visible products is not yet integrated. A 2D bounding box does **not** by itself provide a 3D grasp pose. The simulation has known box identities and preconfigured poses.

## What this repository is not

- Not a complete, reproducible YOLO-controlled KUKA system at the current release stage.
- Not a real-warehouse deployment or a real-camera benchmark.
- Not an autonomous robotic picking planner with depth-based pose estimation or collision guarantees.
- Not the commercial warehouse MVP; the latter will require independent product catalog, document import/review, local deployment and field validation.

## Publishing policy

The public repository may include source, tests, sample data, USD scenes and screenshots. Internal source-of-truth documents, iterative README files and unfinished KUKA calibration/movement scripts stay in the original development workspace until deliberately published. Only fictional or otherwise authorized data/assets should be committed.
