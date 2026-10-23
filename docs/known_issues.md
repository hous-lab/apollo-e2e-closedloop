# Known issues and field notes

Field notes from running this pipeline on a single-GPU laptop and a GPU server. Each entry: symptom, root cause, what the pipeline does about it.

## CARLA RenderOffScreen hangs periodically

Symptom: the CARLA server stops ticking (camera counts freeze), sometimes after tens of minutes.
Root cause: an Unreal/SDL offscreen-render stall we never fully pinned down; frequency depends on host and quality level.
Mitigation: scripts/watchdog.sh probes /apollo/localization/pose every WATCHDOG_INTERVAL_S and, when the flow stops, does a paired restart (bridge + CARLA) via restart_sim_pair.sh, then relaunches control. Stage-7 gate 2 fails the run when restarts exceed WATCHDOG_RESTART_BUDGET (default 3 per 10 min) - a healthy run should not need self-heal.
Status: open upstream; paired restart keeps runs alive through occasional stalls.

## A fresh CARLA client must wait_for_tick() before acting

Symptom: the first transform/actor queries after connecting return nothing or garbage.
Root cause: the client connects before the server finishes its first tick.
Fix: scripts/teleport_drive.py and restart_sim_pair.sh wait for ticks before the first actor operation. Any new host-side client must do the same.
Status: closed (pattern documented here).

## loguru .warn was removed

Symptom: bridge python crashes at import/callback with AttributeError on the logger.
Root cause: loguru 0.7 dropped the deprecated `.warn` alias; the upstream bridge predates that.
Fix: patches/bridge patches rewrite .warn to .warning.
Status: closed (patched).

## MPC controller does not compile on Apollo v8.0.0 headers

Symptom: control build fails on `vehicle_config.pb.h`.
Root cause: the refined MPC sources reference the v7-era include path `modules/common/configs/proto/vehicle_config.pb.h`; v8 moved the message to common_msgs (`modules/common_msgs/config_msgs/vehicle_config.pb.h`).
Fix: patches/apollo/refined_mpc/mpc_controller.h ships the include fix; apply_refined_mpc.sh overlays it. A regression here is the first suspect when a stage-2 build breaks on that header.
Status: closed (fixed in overlay).

## Bridge HEAD verification is mandatory after clone

Symptom: patches fail to apply, or apply but behave differently than expected.
Root cause: mirrors and moving refs can serve a different commit than the ref you expect.
Fix: container_setup.sh clones at BRIDGE_REF=b0c2e08 and verifies the checked-out HEAD's first 7 chars equal the ref before patching; it aborts otherwise.
Status: closed (guard in place).

## 32G RAM budget on the laptop

Symptom: OOM-killer hits CARLA or control mid-run.
Root cause: CARLA + Apollo control + TRT inference share one 32G pool.
Mitigation: 6cam-lowres camera profile (tick budget), gates run strictly serially, and check_env.sh enforces >= 8G available before starting. If a stage-3/4 OOM appears, drop the camera profile first (CAM_PROFILE=2cam is a debug profile, 6cam-lowres is the default).
Status: managed by defaults.

## TRT engine version pairing

Symptom: vad_live_service exits with a deserialization error.
Root cause: a TRT 10.x engine cannot load in a TRT 8.x runtime (this is also why the model service runs on the host, not in the Apollo container - see architecture.md).
Fix: build engines under the same TRT major version as CONDA_ENV's runtime; pointers in ckpts/README.md.
Status: closed (documented pairing).

## pip >= 24 drops py3.8-era pins

Symptom: in-container pip refuses the bridge dependency set.
Root cause: pip 24 removed support for some legacy metadata handling that the py3.8 image's tooling relies on.
Fix: container_setup.sh upgrades pip to <24 first, then installs the pinned set from a configurable mirror (PIP_INDEX_URL).
Status: closed (in container_setup.sh).

## First-spawned camera starves in synchronous drain

Symptom: exactly one camera (front_6mm, first in the actor registry) publishes one frame then goes silent while the other five flow at full tick rate; topic_probe shows 5 live topics + 1 frozen.
Root cause: the upstream bridge drains each sensor queue once per tick and only processes a frame whose CARLA frame number equals the current tick. front_6mm is drained FIRST but its image arrives LAST over the CARLA stream (spawn order and payload size decide arrival order), so at drain time the queue holds only older frames, the current-tick frame is consumed-and-dropped, and the camera never publishes again. On the previous GPU server the timing slack masked it; the laptop tick budget removed the slack.
Fix: patches/bridge/0005 keeps the newest stale frame from each drain and publishes it on queue-empty, so every camera publishes every tick. After the patch all six cameras sit at a uniform 2.3 Hz.
Status: closed (patched).

## Waypoint log mixes world and ego frames

Symptom: gate 1 "fails" with |w0| around 300+ m on hosts whose spawn point is far from the CARLA world origin.
Root cause: the vad_live_service log line prints the world-frame waypoint; its magnitude is distance from world origin, not plan extent. On the earlier GPU server the ego spawned near the origin, so the ambiguity never surfaced. The ego-relative quantity is rel0 = w0 - (px, py).
Fix: vad_live_service.py logs rel0 explicitly and check_gate1.py judges plan extent on rel0; |w0| is kept in the report as info.
Status: reference frames made explicit in the log line and the gate.

## Apollo v8 ControlCommand field names

Symptom: consumer scripts die with AttributeError on m.pad_msg.throttle or m.gear.
Root cause: Apollo v8 ControlCommand.throttle is a direct field (field 3, 0-100 percent) - not nested under pad_msg - and the gear field is named gear_location, not gear.
Fix: consumers read m.throttle and m.gear_location; measure_drive.py prints a CTL-DUMP diagnostic and aborts if the descriptor ever changes again.
Status: closed (documented + diagnostic).

## Watchdog probe window vs pose cadence

Symptom: the watchdog fired on a healthy pose stream once.
Root cause: the probe counted messages over 5 s; at 2.3 Hz tick and ~0.115x sim clock the nominal count is only ~11, and one stalled tick pushes the count under the death threshold. A running docker exec child also deferred SIGTERM, so a stale watchdog could outlive its run.
Fix: probe window 8 s with death threshold < 2 messages, plus a TERM/INT trap and kill -9 fallback in run_bringup so the watchdog cannot leak.
Status: closed (hardened).

## Model drifts off-road and wedges - expected from the documented simplifications

Symptom: the ego accelerates and drives, then curves off the road and wedges in terrain (throttle commanded, speed zero).
Root cause: the documented VAD service simplifications - can_bus fed as zeros (the model believes the ego is static, so no lane-keeping term in the plan), CMD_IDX=0, constant TRAJ_SPEED - mean the plan does not track the road curvature indefinitely. The GPU-server run stayed on-road for ~130 m because its drift happened to be gentle; the laptop spawn drives further and then leaves the road. This is the validated integration with a documented model-side simplification, not an integration failure.
Mitigation: each stage-7 attempt starts from a clean teleport spawn; retries are legitimate. Check the front camera image to confirm off-road view before blaming the control path.
Status: behavior class documented (see docs/model_contract.md for the simplification list).

## GPU-contention inference tail on a shared laptop GPU

Symptom: infer p50 192 ms but p99 376 ms / max 476 ms; gate 1 saw 16 of 195 frames outside the 80-250 ms soft band.
Root cause: CARLA rendering and Apollo control share the GPU with TRT inference; the tail frames line up with CARLA render load.
Mitigation: gate 1 judges the median plus an outlier budget instead of every frame; the tail is quantified in the README gate 3 row and in run/gate1.json soft_warnings.
Status: quantified and documented, not a defect.

## Control mainboard leaks memory when left serving

Symptom: after the gates finish, the closed loop kept idling on the laptop; ~40 minutes later the control mainboard process sat at 13.5 G resident, 17 G of swap was in use, and the OS started killing unrelated background tasks.
Root cause: the refined-MPC path allocates per planning cycle and does not release it - the resident set grows with continuous /apollo/planning traffic. The exact allocation site inside the control module is not pinned down.
Mitigation: do not leave the closed loop idling; tear the stack down after measurement windows, or restart control (stage 4) for long sessions. Defunct mainboard zombies may linger inside the container after a kill; they hold no memory and clear on container restart.
Status: open, workaround documented (leak only shows under continuous traffic, so the staged-gate measurement flow is unaffected).
