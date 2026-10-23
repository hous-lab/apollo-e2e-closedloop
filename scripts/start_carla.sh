#!/bin/bash
# Start CARLA headless (RenderOffScreen) on the host and wait for the world.
# No-op when a world is already reachable (idempotent).
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"

log() { echo "[start_carla] $*"; }

CARLA_PY="$CONDA_BASE/envs/$CONDA_ENV_CARLA/bin/python"
if "$CARLA_PY" -c "import carla; c=carla.Client('127.0.0.1',2000); c.set_timeout(5); c.get_world()" 2>/dev/null; then
    log "CARLA already up"
    exit 0
fi
if [ -z "$CARLA_ROOT" ] || [ ! -x "$CARLA_ROOT/CarlaUE4.sh" ]; then
    log "FATAL: CARLA_ROOT unset or CarlaUE4.sh missing under $CARLA_ROOT"
    exit 1
fi

log "starting CARLA (quality=$QUALITY_LEVEL args=$CARLA_EXTRA_ARGS)"
cd "$CARLA_ROOT"
__GL_SYNC_TO_VBLANK=0 nohup ./CarlaUE4.sh -RenderOffScreen -quality-level="$QUALITY_LEVEL" $CARLA_EXTRA_ARGS > "$RUN_DIR/carla.log" 2>&1 &

log "waiting for the world..."
UP=0
for i in $(seq 1 12); do
    sleep 10
    if "$CARLA_PY" -c "import carla; c=carla.Client('127.0.0.1',2000); c.set_timeout(10); c.get_world()" 2>/dev/null; then
        log "CARLA up after ~$((i*10))s"
        UP=1
        break
    fi
    log "  ...still waiting ($i)"
done
if [ "$UP" -ne 1 ]; then
    log "FATAL: CARLA did not come up within 120s (see $RUN_DIR/carla.log)"
    exit 1
fi
