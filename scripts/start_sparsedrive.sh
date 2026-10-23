#!/bin/bash
# Start the host-side SparseDrive live service (TensorRT engines) against the relay.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"

case "$CAM_PROFILE" in
    2cam)
        RELAY_CAMS="front_6mm,front_12mm"
        CAM_FALLBACK="replicate"
        ;;
    *)
        RELAY_CAMS="front_6mm,front_12mm,front_right,back,back_left,back_right"
        CAM_FALLBACK=""
        ;;
esac
export SPARSEDRIVE_ENGINES_DIR SPARSEDRIVE_PLUGIN \
       SPARSEDRIVE_BB_ENGINE SPARSEDRIVE_HD_ENGINE SPARSEDRIVE_MAP_ENGINE SPARSEDRIVE_PLAN_ENGINE \
       SPARSEDRIVE_ANCHOR_NPZ TCP_PORT CAM_FALLBACK RELAY_CAMS

CONDA_PY="$CONDA_BASE/envs/$CONDA_ENV/bin/python"
if pgrep -f sparsedrive_live_service.py >/dev/null 2>&1; then
    echo "[start_sparsedrive] already running"
    exit 0
fi
nohup "$CONDA_PY" "$SCRIPT_DIR/sparsedrive_live_service.py" > "$RUN_DIR/sparsedrive_live.log" 2>&1 &
echo "[start_sparsedrive] sparsedrive_live_service pid=$! log=$RUN_DIR/sparsedrive_live.log"
