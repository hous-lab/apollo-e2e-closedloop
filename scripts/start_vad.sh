#!/bin/bash
# Start the host-side VAD live service (TensorRT engines) against the relay.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"

case "$CAM_PROFILE" in
    2cam)
        RELAY_CAMS="front_6mm,front_12mm"
        VAD_CAM_FALLBACK="replicate"
        ;;
    *)
        RELAY_CAMS="front_6mm,front_12mm,front_right,back,back_left,back_right"
        VAD_CAM_FALLBACK=""
        ;;
esac
export VAD_PLUGIN VAD_ENGINES_DIR VAD_BB_ENGINE VAD_HD_ENGINE TCP_PORT VAD_CAM_FALLBACK RELAY_CAMS

CONDA_PY="$CONDA_BASE/envs/$CONDA_ENV/bin/python"
if pgrep -f vad_live_service.py >/dev/null 2>&1; then
    echo "[start_vad] already running"
    exit 0
fi
nohup "$CONDA_PY" "$SCRIPT_DIR/vad_live_service.py" > "$RUN_DIR/vad_live.log" 2>&1 &
echo "[start_vad] vad_live_service pid=$! log=$RUN_DIR/vad_live.log"
