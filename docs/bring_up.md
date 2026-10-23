# Bring-up guide

scripts/run_bringup.sh is the numbered conductor: it sources scripts/env.sh, runs stages in order, writes one log per stage under run/, and fail-fasts with the log tail on the first failure. Rerun from any stage:

    scripts/run_bringup.sh --from-stage N [--to-stage M]

Stage table (acceptance = the gate that backs each stage):

| stage | what runs | acceptance |
|---|---|---|
| 0 | check_env.sh guardrails | every [ok] row green, exit 0 |
| 1 | apollo container + in-container setup (bridge fetch @ b0c2e08 + patches + py38 deps + script deploy + camera profile) | setup exits 0 |
| 2 | refined-MPC overlay + control build (RUN_SKIP_BUILD=1 skips the build) | overlay idempotency check passes, build exits 0 |
| 3 | CARLA server (RenderOffScreen, Low) | client reaches world within 120 s |
| 4 | bridge + control + topic probe | probe counts grow: pose > 0 and camera > 0 in 15 s |
| 5 | relay + model service (MODEL env, default vad; MODEL=sparsedrive runs the SparseDriveV2 service) + gate 1 | run/gate1.json verdict PASS |
| 6 | synthetic trajectory bypass (optional, STAGE6=1) | ego moves under synthetic traj, drive JSON captured |
| 7 | teleport to a clean spawn + watchdog + gate 2 | run/gate2.json verdict PASS |
| 8 | gate 3: GPU dmon sample + latency table | run/latency_summary.json produced |

## Gates

**Gate 1 (waypoint sanity).** run_bringup collects GATE1_WINDOW (default 30 s) of model-service frames from the run/<model>_live.log line stream and judges: at least 10 frames, every parsed number finite, every waypoint within 50 m of the ego, infer time in a wide soft band (per-model: VAD 80-250 ms, SparseDriveV2 20-200 ms; warnings only). Result: run/gate1.json.

**Gate 2 (closed-loop drive).** After teleporting the ego to a clean spawn, the watchdog arms (fresh restart budget per run) and measure_drive.py subscribes pose/chassis/control for GATE2_WINDOW (default 300 s). PASS needs net displacement > 5 m, max speed >= 0.3 m/s, and watchdog restarts <= WATCHDOG_RESTART_BUDGET (default 3 per WATCHDOG_WINDOW_S). Result: run/gate2.json.

**Gate 3 (latency table).** While the loop keeps running, nvidia-smi dmon samples GPU util/mem for GATE3_DMON_S (default 60 s) into run/gpu_dmon.log; measure_latency.py folds run/vad_latency.csv into run/latency_summary.json (n / mean / p50 / p90 / p99 / max, plan rate at p50). This is the table that lands in the README.

## Per-stage troubleshooting pointers

| symptom | where to look |
|---|---|
| stage 0 [MISS] rows | the row text - every miss prints its own fix pointer |
| stage 1 patch apply fails | run/stage1_setup.log + patches/bridge/README.md |
| stage 2 build errors around vehicle_config include | docs/known_issues.md (include fix regression) |
| stage 3 CARLA timeout | run/carla.log; also check no stale CARLA process holds the GPU |
| stage 4 probe counts stuck at 0 | container /home/bridge.log (CARLA connection), /apollo/control.log (control startup) |
| stage 5 gate 1 frames < 10 | run/sparsedrive_live.log or run/vad_live.log for connect/missing-engine messages |
| stage 7 displacement near zero | stage7_watchdog.log for restarts; container control.log for trajectory reception |
