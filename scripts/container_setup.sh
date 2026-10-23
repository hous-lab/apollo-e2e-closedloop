#!/bin/bash
# One-shot in-container setup, run from the host against a running container:
#   1. fetch the upstream bridge @ $BRIDGE_REF inside the container
#   2. apply the patch series from patches/bridge/
#   3. install the python3.8 in-container deps
#   4. deploy container-side scripts to $CONTAINER_SCRIPTS_DIR
#   5. rewrite the camera rig per $CAM_PROFILE (scripts/cam_profile.py)
# Idempotent - each step detects its own done state. Re-run safely.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    echo "FATAL: container not running (bash scripts/apollo_container.sh start)" >&2
    exit 1
fi

cexec() { docker exec "$CONTAINER_NAME" "$@"; }
ccopy() { docker cp "$@"; }

PROXY_ENV=()
if [ -n "${https_proxy:-}" ]; then
    PROXY_ENV=(-e https_proxy="$https_proxy" -e HTTPS_PROXY="$https_proxy")
fi
echo "== 1. fetch upstream bridge @ $BRIDGE_REF =="
if cexec test -d /home/carla_apollo_bridge/.git; then
    echo "   bridge already fetched"
else
    if ! docker exec "${PROXY_ENV[@]}" "$CONTAINER_NAME" git clone "$BRIDGE_REPO" /home/carla_apollo_bridge; then
        echo "   https clone failed - local bundle fallback (BRIDGE_LOCAL_CLONE, default ../carla_apollo_bridge)"
        LOCAL_CLONE="${BRIDGE_LOCAL_CLONE:-$E2E_REPO_ROOT/../carla_apollo_bridge}"
        if [ ! -d "$LOCAL_CLONE/.git" ]; then
            echo "FATAL: no local clone at $LOCAL_CLONE and github unreachable" >&2
            exit 1
        fi
        LH=$(git -C "$LOCAL_CLONE" rev-parse HEAD)
        [ "${LH:0:7}" = "$BRIDGE_REF" ] || { echo "FATAL: local clone HEAD $LH != $BRIDGE_REF" >&2; exit 1; }
        tar -C "$LOCAL_CLONE" -cf "$E2E_REPO_ROOT/run/e2e_bridge.tar" .
        ccopy "$E2E_REPO_ROOT/run/e2e_bridge.tar" "$CONTAINER_NAME":/tmp/e2e_bridge.tar
        cexec bash -c "mkdir -p /home/carla_apollo_bridge && tar -C /home/carla_apollo_bridge -xf /tmp/e2e_bridge.tar"
    else
        cexec bash -c "cd /home/carla_apollo_bridge && git checkout -q $BRIDGE_REF"
    fi
fi
# the tar fallback extracts a host-owned working tree; git refuses to read it as
# container-root ("dubious ownership") - self-heal before any git op (idempotent)
cexec bash -c 'git config --global --add safe.directory /home/carla_apollo_bridge' || true
BRIDGE_HEAD=$(cexec bash -c 'cd /home/carla_apollo_bridge && git rev-parse HEAD')
if [ "${BRIDGE_HEAD:0:7}" != "$BRIDGE_REF" ]; then
    echo "FATAL: bridge HEAD $BRIDGE_HEAD != pinned $BRIDGE_REF (mirror variance risk)" >&2
    exit 1
fi
echo "   bridge HEAD verified: $BRIDGE_HEAD"
echo "== 2. apply patch series =="
if cexec grep -q back_left /home/carla_apollo_bridge/carla_bridge/config/objects.json; then
    echo "   patches already applied"
else
    mkdir -p /tmp/e2e_patches
    ccopy "$E2E_REPO_ROOT/patches/bridge/." /tmp/e2e_patches
    cexec bash -c 'cd /home/carla_apollo_bridge && for p in /tmp/e2e_patches/0*.patch; do git apply --whitespace=nowarn "$p" || exit 1; done'
    echo "   patches applied"
fi

echo "== 3. python3.8 + deps =="
if ! cexec bash -c 'command -v python3.8 >/dev/null && ldconfig -p | grep -q libpython3.8.so'; then
    echo "   image lacks python3.8 (this dev image ships only 3.6) - apt install from the bionic mirror"
    cexec bash -c 'apt-get update -qq || true; apt-get install -y -qq python3.8 python3.8-distutils python3.8-venv libpython3.8'
fi
DEPCMD='python3.8 -c "import carla, loguru, transforms3d, networkx, yaml, numpy, cv2, google.protobuf, msgpack"'
if cexec bash -c "$DEPCMD" >/dev/null 2>&1; then
    echo "   deps present"
else
    echo "   installing py38 deps (tuna mirror)..."
    # ensurepip is disabled for the system python on Ubuntu - bootstrap pip via
    # get-pip.py (bootstrap.pypa.io serves the last py3.8-compatible release), then
    # pin pip<24: newer pip rejects some of these pins on py3.8 (see docs/known_issues.md)
    cexec bash -c 'python3.8 -m pip -V >/dev/null 2>&1 || { curl -fsSL https://bootstrap.pypa.io/pip/3.8/get-pip.py -o /tmp/get-pip.py && python3.8 /tmp/get-pip.py -i https://pypi.tuna.tsinghua.edu.cn/simple -q; }; python3.8 -m pip install --upgrade "pip<24" -i https://pypi.tuna.tsinghua.edu.cn/simple'
    cexec bash -c 'python3.8 -m pip install carla==0.9.15 loguru==0.7.0 transforms3d==0.4.1 networkx pyyaml numpy opencv-python-headless protobuf==3.20.3 msgpack -i https://pypi.tuna.tsinghua.edu.cn/simple'
fi
echo "== 4. deploy container-side scripts =="
cexec mkdir -p "$CONTAINER_SCRIPTS_DIR"
for f in relay_cyber_tcp.py topic_probe.py synth_traj_pub.py start_bridge.sh cam_profile.py measure_drive.py; do
    ccopy "$E2E_REPO_ROOT/scripts/$f" "$CONTAINER_NAME:$CONTAINER_SCRIPTS_DIR/$f"
done
echo "   deployed to $CONTAINER_SCRIPTS_DIR"
echo "== 5. camera profile ($CAM_PROFILE) =="
cexec bash -c "CAM_PROFILE=$CAM_PROFILE python3.8 $CONTAINER_SCRIPTS_DIR/cam_profile.py"
echo ""
echo "container setup complete. next: bash scripts/apply_refined_mpc.sh, then"
echo "build control inside the container (see docs/bring_up.md)."
