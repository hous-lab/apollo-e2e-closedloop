#!/bin/bash
# run_bringup.sh - numbered bring-up conductor for the closed loop.
# Stages run in order, each appends its own log under run/, fail-fast.
#   stage 0  environment guardrails (check_env.sh)
#   stage 1  apollo container start + in-container setup
#   stage 2  refined-MPC overlay + control build (RUN_SKIP_BUILD=1 skips)
#   stage 3  CARLA server start
#   stage 4  bridge + control + topic probe
#   stage 5  relay + VAD service + gate 1 (waypoint sanity)
#   stage 6  synthetic trajectory bypass (optional; STAGE6=1)
#   stage 7  teleport + watchdog + gate 2 (closed-loop drive)
#   stage 8  gate 3 (latency table + GPU utilization)
# Usage: scripts/run_bringup.sh [--from-stage N] [--to-stage N]
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

FROM=0
TO=8
while [ $# -gt 0 ]; do
    case "$1" in
        --from-stage) FROM="$2"; shift 2 ;;
        --to-stage)   TO="$2"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

STAGE4_PROBE_WINDOW="${STAGE4_PROBE_WINDOW:-15}"
GATE1_WINDOW="${GATE1_WINDOW:-30}"
GATE2_WINDOW="${GATE2_WINDOW:-300}"
GATE3_DMON_S="${GATE3_DMON_S:-60}"
# in-container python3.8 needs the CyberRT python bindings on PYTHONPATH
CYBER_PY="export PYTHONPATH=/apollo:/apollo/bazel-bin:/apollo/cyber/python:/apollo/bazel-bin/cyber/python/internal"

log()  { echo "[bringup] $*"; }
die()  { echo "[bringup] FATAL: $*" >&2; exit 1; }
run_stage() {  # run_stage <n> <name> <cmd...>
    local n="$1" name="$2"; shift 2
    log "stage $n: $name"
    local lf="$RUN_DIR/stage${n}_${name}.log"
    : > "$lf"
    if ! "$@" >> "$lf" 2>&1; then
        log "stage $n FAILED - see $lf (tail below)"
        tail -n 25 "$lf"
        exit 1
    fi
    log "stage $n ok"
}

# ---------------------------------------------------------------- stage 0 --
if [ "$FROM" -le 0 ] && [ "$TO" -ge 0 ]; then
    run_stage 0 env "$SCRIPT_DIR/check_env.sh"
fi
# ---------------------------------------------------------------- stage 1 --
if [ "$FROM" -le 1 ] && [ "$TO" -ge 1 ]; then
    run_stage 1 container "$SCRIPT_DIR/apollo_container.sh" start
    run_stage 1 setup "$SCRIPT_DIR/container_setup.sh"
fi

# ---------------------------------------------------------------- stage 2 --
if [ "$FROM" -le 2 ] && [ "$TO" -ge 2 ]; then
    run_stage 2 mpc "$SCRIPT_DIR/apply_refined_mpc.sh"
    if [ "${RUN_SKIP_BUILD:-0}" = "1" ]; then
        log "stage 2: RUN_SKIP_BUILD=1 - skipping the control build"
    else
        run_stage 2 build docker exec -w /apollo "$CONTAINER_NAME" bash -c \

            "APOLLO_ROOT_DIR=/apollo APOLLO_BAZEL_BIN=/apollo/bazel-bin ./apollo.sh build_cpu control"
    fi
fi
# ---------------------------------------------------------------- stage 3 --
if [ "$FROM" -le 3 ] && [ "$TO" -ge 3 ]; then
    run_stage 3 carla "$SCRIPT_DIR/start_carla.sh"
fi
# ---------------------------------------------------------------- stage 4 --
if [ "$FROM" -le 4 ] && [ "$TO" -ge 4 ]; then
    docker exec -d "$CONTAINER_NAME" bash /apollo_scripts/start_bridge.sh
    log "stage 4: bridge launched (log: container /home/bridge.log)"
    run_stage 4 control "$SCRIPT_DIR/start_control.sh"
    sleep 10
    probe_lf="$RUN_DIR/stage4_probe.log"
    : > "$probe_lf"
    if ! docker exec "$CONTAINER_NAME" bash -c \
        "$CYBER_PY; PROBE_WINDOW=$STAGE4_PROBE_WINDOW python3.8 $CONTAINER_SCRIPTS_DIR/topic_probe.py" \
        >> "$probe_lf" 2>&1; then
        die "stage 4: topic probe failed - see $probe_lf"
    fi
    tail -n 3 "$probe_lf" | sed 's/^/[probe] /'
    POSE_N=$(tail -n 1 "$probe_lf" | grep -oP 'pose=\K\d+' || echo 0)
    CAM_N=$(tail -n 1 "$probe_lf" | grep -oP 'camera=\K\d+' || echo 0)
    [ "$POSE_N" -gt 0 ] && [ "$CAM_N" -gt 0 ] || die "stage 4: probe saw pose=$POSE_N camera=$CAM_N"
    log "stage 4 ok (pose=$POSE_N camera=$CAM_N)"
fi

# ---------------------------------------------------------------- stage 5 --
if [ "$FROM" -le 5 ] && [ "$TO" -ge 5 ]; then
    if [ "$CAM_PROFILE" = "2cam" ]; then RELAY_CAMS="front_6mm,front_12mm"; else
        RELAY_CAMS="front_6mm,front_12mm,front_right,back,back_left,back_right"; fi
    run_stage 5 relay docker exec -d -e RELAY_CAMS="$RELAY_CAMS" -e TCP_PORT="$TCP_PORT" \
        "$CONTAINER_NAME" bash -c "$CYBER_PY; python3.8 $CONTAINER_SCRIPTS_DIR/relay_cyber_tcp.py"
    case "$MODEL" in
        sparsedrive) run_stage 5 model "$SCRIPT_DIR/start_sparsedrive.sh" ;;
        *)           run_stage 5 model "$SCRIPT_DIR/start_vad.sh" ;;
    esac
    MODEL_LOG="$RUN_DIR/vad_live.log"
    [ "$MODEL" = "sparsedrive" ] && MODEL_LOG="$RUN_DIR/sparsedrive_live.log"
    # infer band is engine-dependent: VAD p50 ~130 ms under CARLA contention,
    # SparseDrive cascade p50 ~16-40 ms (smaller engines, less to copy).
    case "$MODEL" in
        sparsedrive) GATE1_BAND="20,200" ;;
        *)           GATE1_BAND="80,250" ;;
    esac
    log "stage 5: gate 1 - collecting ${GATE1_WINDOW}s of waypoints ($MODEL, band $GATE1_BAND ms)"
    run_stage 5 gate1 "$SCRIPT_DIR/check_gate1.py" \
        --log "$MODEL_LOG" --window "$GATE1_WINDOW" --infer-band "$GATE1_BAND" --radius 50
fi
# ---------------------------------------------------------------- stage 6 --
if [ "$FROM" -le 6 ] && [ "$TO" -ge 6 ]; then
    if [ "${STAGE6:-0}" = "1" ]; then
        docker exec -d -e SYNTH_N_FRAMES="${SYNTH_N_FRAMES:-300}" \
            "$CONTAINER_NAME" bash -c "$CYBER_PY; python3.8 $CONTAINER_SCRIPTS_DIR/synth_traj_pub.py"
        log "stage 6: synthetic trajectory published - watching ${SYNTH_WATCH_S:-40}s"
        sleep 2
        s6lf="$RUN_DIR/stage6_measure.log"
        : > "$s6lf"
        docker exec -e MEASURE_WINDOW="${SYNTH_WATCH_S:-40}" \
            "$CONTAINER_NAME" bash -c "$CYBER_PY; python3.8 $CONTAINER_SCRIPTS_DIR/measure_drive.py" >> "$s6lf" 2>&1 \
            || die "stage 6: measure_drive failed - see $s6lf"
        grep MEASURE_DRIVE_JSON "$s6lf" | tail -n 1 | sed 's/MEASURE_DRIVE_JSON //' > "$RUN_DIR/gate2.json"
    else
        log "stage 6: skipped (set STAGE6=1 to run the synthetic bypass)"
    fi
fi
# ---------------------------------------------------------------- stage 7 --
if [ "$FROM" -le 7 ] && [ "$TO" -ge 7 ]; then
    run_stage 7 teleport "$CONDA_BASE/envs/$CONDA_ENV_CARLA/bin/python" "$SCRIPT_DIR/teleport_drive.py"
    log "stage 7: gate 2 - watchdog armed, closed-loop window ${GATE2_WINDOW}s"
    : > "$RUN_DIR/watchdog_restarts.log"   # fresh budget window per stage-7 run
    "$SCRIPT_DIR/watchdog.sh" >> "$RUN_DIR/stage7_watchdog.log" 2>&1 &
    WD_PID=$!
    g2lf="$RUN_DIR/stage7_gate2.log"
    : > "$g2lf"
    if ! docker exec -e MEASURE_WINDOW="$GATE2_WINDOW" \
        "$CONTAINER_NAME" bash -c "$CYBER_PY; python3.8 $CONTAINER_SCRIPTS_DIR/measure_drive.py" >> "$g2lf" 2>&1; then
        kill "$WD_PID" 2>/dev/null; sleep 1; kill -9 "$WD_PID" 2>/dev/null || true
        die "stage 7: measure_drive failed - see $g2lf"
    fi
    kill "$WD_PID" 2>/dev/null; sleep 1; kill -9 "$WD_PID" 2>/dev/null || true
    grep MEASURE_DRIVE_JSON "$g2lf" | tail -n 1 | sed 's/MEASURE_DRIVE_JSON //' > "$RUN_DIR/gate2_drive.json"
    # grep -c prints "0" and exits 1 on no match; `|| echo 0` would append a second line
    RESTARTS=$(grep -c . "$RUN_DIR/watchdog_restarts.log" 2>/dev/null || true)
    RESTARTS="${RESTARTS:-0}"
    python3 - "$RUN_DIR/gate2_drive.json" "$RESTARTS" "$WATCHDOG_RESTART_BUDGET" > "$RUN_DIR/gate2.json" <<'PYCHK'
import json, sys, os
p = sys.argv[1]
rep = {}
if os.path.isfile(p):
    try:
        rep = json.load(open(p))
    except Exception:
        rep = {}
disp = rep.get("net_displacement_m") or 0
speed = rep.get("max_speed_mps") or 0
restarts, budget = int(sys.argv[2]), int(sys.argv[3])
ok = disp > 5.0 and speed >= 0.3 and restarts <= budget
print(json.dumps({"verdict": "PASS" if ok else "FAIL",
                  "displacement_m": disp, "max_speed_mps": speed,
                  "watchdog_restarts": restarts, "restart_budget": budget}))
PYCHK
    echo "[bringup] gate 2 verdict: $(cat "$RUN_DIR/gate2.json")"
    python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))["verdict"]=="PASS" else 1)' \
        "$RUN_DIR/gate2.json" || die "stage 7: gate 2 FAIL"
    log "stage 7 ok"
fi
# ---------------------------------------------------------------- stage 8 --
if [ "$FROM" -le 8 ] && [ "$TO" -ge 8 ]; then
    MODEL_CSV="$RUN_DIR/vad_latency.csv"
    [ "$MODEL" = "sparsedrive" ] && MODEL_CSV="$RUN_DIR/sparsedrive_latency.csv"
    nvidia-smi dmon -s um -d 1 -o TD > "$RUN_DIR/gpu_dmon.log" 2>&1 &
    DMON_PID=$!
    log "stage 8: gate 3 - sampling GPU for ${GATE3_DMON_S}s while $MODEL serves live traffic"
    sleep "$GATE3_DMON_S"
    kill "$DMON_PID" 2>/dev/null || true
    run_stage 8 latency "$CONDA_BASE/envs/$CONDA_ENV/bin/python" "$SCRIPT_DIR/measure_latency.py" \
        --csv "$MODEL_CSV" --dmon-log "$RUN_DIR/gpu_dmon.log" --out "$RUN_DIR/latency_summary.json"
fi
log "bring-up complete: stages $FROM..$TO (evidence in $RUN_DIR/)"
