# Repository Structure — Warehouse Pallet Vision Demo

This document describes the published **simulation demonstration** and the responsibilities of each module. See [`README.md`](README.md) for setup, videos, demonstrations and limitations.

## Main components

| Component | Location | Responsibility |
| --- | --- | --- |
| Setup and launch | `scripts/setup_demo.sh`, `scripts/launch_demo.sh` | Install Python/ROS dependencies and start five live services (backend, YOLO, bridge, matcher, overlay) |
| Shared perception | `software/src/whpv_core/` | YOLO integration, 2D detection data, visual overlays and common logic |
| Order backend | `software/src/whpv_backend/` | FastAPI, SQLite, live eligibility queries and dashboard |
| Fictional scenarios | `software/data/routes_demo.csv`, `software/data/routes_alternative.csv` | Three drivers, four boxes each; 12 source boxes total |
| Software tests | `software/tests/` | Backend and shared software tests |
| ROS 2 perception | `sim/ros2_ws/src/whpv_perception_ros/` | Camera subscriber, detector, order matcher, image overlay |
| YOLO snapshot | `sim/ros2_ws/scripts/whpv_yolo_snapshot_bridge.py` | Write fresh ROS YOLO results to a JSON file for Isaac Sim's controller |
| Simulated scene | `sim/isaac_sim/scenes/Worlds/IsaacSim_demonstration.usd` | Fixed KUKA robot, camera, boxes and pallets |
| Robot demonstration | `sim/isaac_sim/scripts/demonstration_script.py` | Read remaining orders, verify product using YOLO, execute predefined pick/place movements, and update API counts |
| Scene resources | `sim/isaac_sim/assets/` | Simulation visuals and textures |
| Preview images | `previews/` | Dashboard and annotated-camera screenshots |

## Runtime data paths

```text
Isaac Sim RGB camera
   -> ROS 2 /warehouse/camera/image_raw
   -> YOLO /warehouse/perception/detections_json
       |                             |
       v                             v
  Order matcher                Snapshot bridge
       |                             |
  FastAPI/SQLite                   yolo_latest.json
       |                             |
  Driver overlay                   Isaac Sim KUKA controller
       |                             |
  Annotated ROS image           Predefined pose transfer
                                     |
                              API completed-quantity update
                                     |
                                  Dashboard
```

The robot has a **fixed top-to-bottom pickup sequence** and **four saved destination slots per driver**. YOLO provides a product-class check in 2D before each transfer; it does **not** generate arbitrary 3D grasp poses or collision-free trajectories. The backend receives completion updates after commanded movements, not independent physical-placement verification.

## Generated local artifacts

Do **not** commit environment files, ROS build directories, YOLO model downloads, live snapshots, simulation reports, or test databases. Typical generated paths include:

- `.venv/`
- `sim/ros2_ws/{build,install,log}/`
- `sim/isaac_sim/reports/yolo_latest.json`
- `sim/isaac_sim/reports/kuka_all_boxes_backend_counts_report.txt`
- `yolo11n.pt`
- `/tmp/whpv-demo.*/` (launcher logs and temporary SQLite database)

The repository is a simulation/portfolio demo rather than a production warehouse solution. Documentation and example data are intended to be public; private project plans, credentials and experimental scripts should remain outside this repository.
