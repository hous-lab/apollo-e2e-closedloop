# env.sh - central environment contract for the apollo-e2e-closedloop pipeline.
# Every script sources this file. Override any value before sourcing:
#   export CARLA_ROOT=/path/to/CARLA_0.9.15 VAD_ENGINES_DIR=/path/to/engines \
#          VAD_PLUGIN=/path/to/libplugins.so ; source scripts/env.sh

# Resolve repo root from this file location.
E2E_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${E2E_REPO_ROOT}/run"
mkdir -p "$RUN_DIR"

# Machine-local values (absolute paths, conda base) live in run/local_env.sh -
# gitignored, never shipped. Values here are plain defaults; anything exported
# in the environment before sourcing still wins if local_env.sh guards likewise.
[ -f "$RUN_DIR/local_env.sh" ] && . "$RUN_DIR/local_env.sh"

# ---------------------------------------------------------------- CARLA ----
# Local CARLA 0.9.15 install (directory containing CarlaUE4.sh).
CARLA_ROOT="${CARLA_ROOT:-}"
QUALITY_LEVEL="${QUALITY_LEVEL:-Low}"
# Extra CARLA server args (e.g. -Town01). Empty = server default map.
CARLA_EXTRA_ARGS="${CARLA_EXTRA_ARGS:-}"

# --------------------------------------------------------------- Apollo ----
# Apollo v8.0.0 dev docker image.
APOLLO_IMAGE="${APOLLO_IMAGE:-registry.baidubce.com/apolloauto/apollo:dev-x86_64-18.04-20221124_1708}"
CONTAINER_NAME="${CONTAINER_NAME:-apollo_e2e_dev}"
# Host path of the Apollo v8.0.0 source tree (mounted at /apollo).
APOLLO_SRC="${APOLLO_SRC:-}"

# --------------------------------------------------------------- Bridge ----
# Upstream bridge fetched and patched at container setup time (Patch+fetch).
BRIDGE_REPO="${BRIDGE_REPO:-https://github.com/guardstrikelab/carla_apollo_bridge.git}"
BRIDGE_REF="${BRIDGE_REF:-b0c2e08}"
# Paths inside the container.
CONTAINER_BRIDGE_DIR="${CONTAINER_BRIDGE_DIR:-/home/carla_apollo_bridge}"
CONTAINER_SCRIPTS_DIR="${CONTAINER_SCRIPTS_DIR:-/apollo_scripts}"

# --------------------------------------------------------- Model (VAD) ----
# VAD TensorRT engines built by hous-lab/vad-trt-edge (x86 pipeline).
VAD_ENGINES_DIR="${VAD_ENGINES_DIR:-}"
VAD_PLUGIN="${VAD_PLUGIN:-}"
# Default pair = best x86 config in the vad-trt-edge README
# (INT8 backbone + FP16 head: L2(1s) 0.7828 @ 88.9 ms on a 4090 Laptop).
VAD_BB_ENGINE="${VAD_BB_ENGINE:-backbone_int8.engine}"
VAD_HD_ENGINE="${VAD_HD_ENGINE:-head_withprev_fp16_fixed_v2.engine}"
# Camera fallback: empty = require all 6 cameras; "replicate" = fill missing
# surround views with the front image (debug profile for weak hosts).
VAD_CAM_FALLBACK="${VAD_CAM_FALLBACK:-}"

# --------------------------------------------------------------- Python ----
# Host conda env with tensorrt 10.x + torch (VAD live service).
CONDA_ENV="${CONDA_ENV:-p1bevrc}"
# Host conda env for host-side CARLA probes (client API only).
CONDA_ENV_CARLA="${CONDA_ENV_CARLA:-carla_py310}"
# Conda base dir; auto-discovered when empty.
CONDA_BASE="${CONDA_BASE:-}"

# ----------------------------------------------------------------- Loop ----
# relay <-> model service TCP endpoint. The relay binds it inside the
# container; the model service connects from the host (net=host).
TCP_PORT="${TCP_PORT:-9101}"
# Watchdog self-heal budget: more than this many paired restarts inside
# WATCHDOG_WINDOW_S fails gate 2.
WATCHDOG_RESTART_BUDGET="${WATCHDOG_RESTART_BUDGET:-3}"
WATCHDOG_WINDOW_S="${WATCHDOG_WINDOW_S:-600}"
# pose probe interval (s).
WATCHDOG_INTERVAL_S="${WATCHDOG_INTERVAL_S:-75}"

# ------------------------------------------------------ Camera profile ----
# 6cam        = 800x600 surround rig (GPU-server production profile)
# 6cam-lowres = 640x384 (laptop default; no downstream impact, G3-proven)
# 2cam        = front pair only (debug)
CAM_PROFILE="${CAM_PROFILE:-6cam-lowres}"
