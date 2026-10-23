#!/bin/bash
# Watchdog: probe /apollo/localization/pose health every $WATCHDOG_INTERVAL_S,
# self-heal via the paired restart when the stream dies, relaunch control, and
# fail the run (exit 2) when the restart budget is exhausted.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"

LOG="$RUN_DIR/watchdog.log"
RESTART_SCRIPT="$SCRIPT_DIR/restart_sim_pair.sh"

log() { echo "$(date +%H:%M:%S) $*" >> "$LOG"; }
# a running `docker exec` child would otherwise defer the TERM until it exits
trap 'exit 0' TERM INT

PY_EXPORT="export PYTHONPATH=$CONTAINER_BRIDGE_DIR:$CONTAINER_BRIDGE_DIR/carla_bridge:/apollo:/apollo/bazel-bin:/apollo/cyber/python:/apollo/bazel-bin/cyber/python/internal"

log "watchdog start (interval=${WATCHDOG_INTERVAL_S}s, budget=${WATCHDOG_RESTART_BUDGET} restarts / ${WATCHDOG_WINDOW_S}s)"
while true; do
    sleep "$WATCHDOG_INTERVAL_S"
    POSE=$(docker exec "$CONTAINER_NAME" bash -c "$PY_EXPORT; timeout 10 python3.8 -c \"
from cyber_py3 import cyber
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
n=[0]
def cb(m): n[0]+=1
cyber.init('wd'); node=cyber.Node('wd')
node.create_reader('/apollo/localization/pose', LocalizationEstimate, cb)
import time; t0=time.time()
while time.time()-t0<8: time.sleep(0.5)
print(n[0])
\" 2>/dev/null | tail -1")
    POSE="${POSE:-0}"
    if [ "$POSE" -lt 2 ]; then
        log "DEAD pose stream ($POSE msgs in 8s) -> paired restart"
        echo "$(date +%s) restart" >> "$RUN_DIR/watchdog_restarts.log"
        bash "$RESTART_SCRIPT" >> "$RUN_DIR/restart.log" 2>&1
        sleep 5
        docker exec -d "$CONTAINER_NAME" bash -c "cd /apollo && export APOLLO_ROOT_DIR=/apollo APOLLO_BAZEL_BIN=/apollo/bazel-bin; /apollo/bazel-bin/cyber/mainboard/mainboard -d /apollo/modules/control/dag/control.dag -p control > /apollo/control.log 2>&1 &"
        log "pair restarted + control relaunched"
        NOW=$(date +%s)
        BUDGET_HITS=$(awk -v now="$NOW" -v win="$WATCHDOG_WINDOW_S" '$1 > now-win' "$RUN_DIR/watchdog_restarts.log" | wc -l)
        if [ "$BUDGET_HITS" -gt "$WATCHDOG_RESTART_BUDGET" ]; then
            log "FAIL: restart budget exhausted ($BUDGET_HITS restarts in ${WATCHDOG_WINDOW_S}s window)"
            exit 2
        fi
    else
        log "ok pose=$POSE"
    fi
done
