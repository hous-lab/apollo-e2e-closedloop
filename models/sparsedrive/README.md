# models/sparsedrive

SparseDriveV2 closed-loop integration. Reuses this pipeline unchanged - the
relay ([scripts/relay_cyber_tcp.py](../../scripts/relay_cyber_tcp.py)) and every orchestration script are
model-agnostic; SparseDrive adds its host-side service and engine pointers.

## What runs

[scripts/start_sparsedrive.sh](../../scripts/start_sparsedrive.sh) launches [scripts/sparsedrive_live_service.py](../../scripts/sparsedrive_live_service.py)
on the host (same conda env as the VAD service). Per frame it runs the 4-engine
TensorRT cascade from [hous-lab/sparsedrive-trt-edge](https://github.com/hous-lab/sparsedrive-trt-edge)
(x86 fp16 tier): backbone → head + map → motion plan, then decodes the
lat/lon anchor plan into 6 world-frame waypoints on the shared TCP contract
(`docs/model_contract.md`).

## Engine configuration (env.sh knobs)

| Knob | Default | Role |
|---|---|---|
| `SPARSEDRIVE_ENGINES_DIR` | (required) | directory with the 4 `.engine` files |
| `SPARSEDRIVE_PLUGIN` | (required) | `libplugins.so` (DeformableAggregation plugin, required by head/map/plan) |
| `SPARSEDRIVE_BB_ENGINE` | `backbone_fp16.engine` | image backbone, img [6,3,384,704] → feat_0..3 |
| `SPARSEDRIVE_HD_ENGINE` | `head_fp16.engine` | detection head → det_cls/reg/instance_feat |
| `SPARSEDRIVE_MAP_ENGINE` | `map_fp16.engine` | map head → map_cls/instance_feat/anchor_embed |
| `SPARSEDRIVE_PLAN_ENGINE` | `motion_plan_fp16.engine` | motion planning → traj_cls + lat/lon anchors |
| `SPARSEDRIVE_ANCHOR_NPZ` | (required) | demo npz with the `anchor_embed` bank (deploy-side constant) |

Engine filenames match the sparsedrive-trt-edge x86 fp16 output directory; the
int8 tier swaps `SPARSEDRIVE_BB_ENGINE`/`SPARSEDRIVE_HD_ENGINE` to the int8
files (same directory naming).

## Deployed-engine simplifications (see [docs/model_contract.md](../../docs/model_contract.md))

- The deployed motion engine takes no ego_status / command / timestamp / mask
  inputs - planning is camera-driven with a fixed target point tp_near=(0, 3)
  (lateral, forward) and no ego speed reaching the engine.
- Pseudo-projection: pinhole fov-90 at 704x384 with camera-yaw rotation,
  camera at the lidar origin.
- Bridge camera order permutes to SparseDrive order [0, 2, 1, 3, 4, 5];
  preprocessing is resize-to-width-704 + crop-top to 384 + ImageNet norm.
- Decode: argmax over sigmoid(traj_cls) → lat anchor path (col0 lateral,
  col1 forward) → ego (x fwd, y left) → world transform (shared with VAD).

Offline smoke (synthetic 6-camera frame, laptop idle): cascade p50 ~60 ms,
waypoints span 3-13 m forward. Closed-loop gates on this laptop: all three
PASS (gate 3: p50 74.9 ms, p99 130 ms, 13.35 Hz plan rate over n=5649) -
full table in the README results section.
