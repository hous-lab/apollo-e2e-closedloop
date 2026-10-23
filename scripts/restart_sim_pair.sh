#!/bin/bash
# Paired CARLA + bridge restart (used when the sim pair is wedged).
# Kills the bridge inside the container, kills CARLA on the host, brings both
# back, then re-probes topics. CARLA RenderOffScreen wedging periodically is a
# known issue (docs/known_issues.md); scripts/watchdog.sh automates exactly
# this repair.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"

log() { echo "[restart_sim_pair] $*"; }

log "killing bridge in container $CONTAINER_NAME"
docker exec "$CONTAINER_NAME" pkill -f "carla_bridge/main.py" 2>/dev/null || true
sleep 2
log "killing CARLA on host"
pkill -f "CarlaUE4" || true
sleep 5
pkill -9 -f "CarlaUE4" || true
sleep 3

if [ -z "$CARLA_ROOT" ] || [ ! -x "$CARLA_ROOT/CarlaUE4.sh" ]; then
    log "FATAL: CARLA_ROOT unset or CarlaUE4.sh missing under $CARLA_ROOT"
    exit 1
fi
log "starting CARLA (quality=$QUALITY_LEVEL args=$CARLA_EXTRA_ARGS)"
cd "$CARLA_ROOT"
__GL_SYNC_TO_VBLANK=0 nohup ./CarlaUE4.sh -RenderOffScreen -quality-level="$QUALITY_LEVEL" $CARLA_EXTRA_ARGS > "$RUN_DIR/carla.log" 2>&1 &

log "waiting for CARLA to come up..."
CARLA_PY="$CONDA_BASE/envs/$CONDA_ENV_CARLA/bin/python"
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
log "relaunching bridge"
docker exec -d "$CONTAINER_NAME" bash "$CONTAINER_SCRIPTS_DIR/start_bridge.sh"
log "waiting for sensors..."
sleep 30
docker exec "$CONTAINER_NAME" bash -c \
    "export PYTHONPATH=$CONTAINER_BRIDGE_DIR:$CONTAINER_BRIDGE_DIR/carla_bridge:/apollo:/apollo/bazel-bin:/apollo/cyber/python:/apollo/bazel-bin/cyber/python/internal; timeout 15 python3.8 $CONTAINER_SCRIPTS_DIR/topic_probe.py 2>&1 | tail -3"
