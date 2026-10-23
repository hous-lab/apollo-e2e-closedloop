#!/bin/bash
# Stage-0 guardrails: verify every external dependency before anything starts.
# Fail fast with a pointer for each miss. Sources scripts/env.sh.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"

FAIL=0
ok()   { echo "  [ok]   $*"; }
miss() { echo "  [MISS] $*" >&2; FAIL=1; }

echo "== apollo-e2e-closedloop environment check =="
echo "docker / image"
if command -v docker >/dev/null 2>&1; then
    ok "docker present"
else
    miss "docker not installed"
fi
if docker image inspect "$APOLLO_IMAGE" >/dev/null 2>&1; then
    ok "apollo image $APOLLO_IMAGE"
else
    miss "apollo image not present locally: $APOLLO_IMAGE (docker pull it)"
fi

echo "CARLA"
if [ -n "$CARLA_ROOT" ] && [ -x "$CARLA_ROOT/CarlaUE4.sh" ]; then
    ok "CARLA at $CARLA_ROOT"
else
    miss "CARLA_ROOT unset or CarlaUE4.sh missing (export CARLA_ROOT=...)"
fi
if "$CONDA_BASE/envs/$CONDA_ENV_CARLA/bin/python" -c "import carla" 2>/dev/null; then
    ok "host carla python api ($CONDA_ENV_CARLA)"
else
    miss "host conda env $CONDA_ENV_CARLA lacks the carla module"
fi

echo "Apollo source tree"
if [ -n "$APOLLO_SRC" ] && { [ -f "$APOLLO_SRC/modules/control/controller/mpc_controller/mpc_controller.cc" ] || \
    [ -f "$APOLLO_SRC/modules/control/controller/mpc_controller.cc" ]; }; then
    ok "apollo tree at $APOLLO_SRC"
else
    miss "APOLLO_SRC unset or not an Apollo v8 tree (export APOLLO_SRC=...)"
fi

echo "VAD engines + plugin"
if [ -n "$VAD_ENGINES_DIR" ] && [ -f "$VAD_ENGINES_DIR/$VAD_BB_ENGINE" ] && [ -f "$VAD_ENGINES_DIR/$VAD_HD_ENGINE" ]; then
    ok "engines: $VAD_BB_ENGINE + $VAD_HD_ENGINE in $VAD_ENGINES_DIR"
else
    miss "engines missing under VAD_ENGINES_DIR (download pointers in ckpts/README.md)"
fi
if [ -n "$VAD_PLUGIN" ] && [ -f "$VAD_PLUGIN" ]; then
    ok "plugin $VAD_PLUGIN"
else
    miss "VAD_PLUGIN unset or missing"
fi

echo "host python envs"
if [ -x "$CONDA_BASE/envs/$CONDA_ENV/bin/python" ]; then
    if "$CONDA_BASE/envs/$CONDA_ENV/bin/python" -c "import tensorrt, torch, cv2, msgpack, pycuda" 2>/dev/null; then
        ok "conda env $CONDA_ENV has tensorrt/torch/cv2/msgpack/pycuda"
    else
        miss "conda env $CONDA_ENV missing one of tensorrt/torch/cv2/msgpack/pycuda"
    fi
else
    miss "conda env $CONDA_ENV python not found under $CONDA_BASE"
fi

echo "resources"
FREE_GB=$(df -BG --output=avail /home | tail -1 | tr -dc "0-9")
if [ "${FREE_GB:-0}" -ge 20 ]; then
    ok "free disk >= 20G ($FREE_GB G)"
else
    miss "free disk < 20G ($FREE_GB G)"
fi
FREE_RAM=$(free -g | awk '/^Mem:/ {print $7}')
if [ "${FREE_RAM:-0}" -ge 8 ]; then
    ok "available RAM >= 8G ($FREE_RAM G)"
else
    miss "available RAM < 8G ($FREE_RAM G) - CARLA + TRT need headroom on a 32G laptop"
fi
if command -v nvidia-smi >/dev/null 2>&1; then
    if nvidia-smi >/dev/null 2>&1; then
        ok "nvidia-smi reachable"
    else
        miss "nvidia-smi present but failing"
    fi
fi

if [ "$FAIL" -ne 0 ]; then
    echo ""
    echo "environment check FAILED - fix the [MISS] rows above and rerun." >&2
    exit 1
fi
echo ""
echo "environment check PASSED"
