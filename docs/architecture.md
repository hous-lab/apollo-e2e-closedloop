# Architecture

## Data path

CARLA renders and steps the world; the bridge turns CARLA actors into Apollo CyberRT messages; the relay and the model service close the loop. Everything below assumes the Apollo v8 dev container described in [environment.md](environment.md).

```
CARLA 0.9.15 (RenderOffScreen, quality Low)
   |  6x camera JPEGs + pose/chassis/clock
   v
bridge main.py (Apollo dev container, python3.8)
   |  publishes 6x CompressedImage + pose/chassis/clock
   v
relay_cyber_tcp.py (same container)
   |  CyberRT -> TCP msgpack (127.0.0.1:9101)
   +-----------------------------+
                                 |
                                 v
vad_live_service.py (host, TensorRT engines)
   |  obs -> 6-waypoint plan (world frame)
   v
ADCTrajectory -> /apollo/planning
   |
   v
mpc_controller (refined gains, built into Apollo control)
   |
   v
ControlCommand -> bridge -> CARLA ego vehicle
```

Two design choices are worth spelling out because they are unusual.

**The model runs outside the Apollo container.** The Apollo v8 dev image ships TensorRT 8.x inside; our engines are built with TensorRT 10.x on the host, and a TRT 10 engine cannot be deserialized by a TRT 8 runtime. The engine process therefore lives where the engines were built for: the host. The relay bridges the gap: it speaks CyberRT in-container and plain TCP (msgpack, length-prefixed) to the host over loopback, so the host service needs zero Apollo/proto dependencies (msgpack + numpy + torch/TRT only). It also keeps the heavy TRT/torch host env out of the Apollo image.

**The relay is model-agnostic.** Its TCP contract is one message pair: container-to-host `{jpegs[6], x, y, yaw, v, sim_t}` and host-to-container `{wp, seq}` where wp is 6 world-frame `[x, y]` pairs. Anything that turns the observation into waypoints can serve the endpoint - that is the seam where SparseDrive plugs in later (see [model_contract.md](model_contract.md)).

## Why an MPC overlay instead of an Apollo fork

Closed-loop runs here all use the overlay; the stock MPC gains were never benchmarked on this pipeline, and "stock gains stall closed-loop driving" is the bridge upstream's stated rationale for shipping this refined controller - treat it as a plausible hypothesis, not our measurement (see the failed-routes section in [known_issues.md](known_issues.md)). Separately, the controller sources do not compile on Apollo v8.0.0 headers without one include fix - that one we did hit in the stage-2 build. The overlay is three files under [patches/apollo/refined_mpc/](../patches/apollo/refined_mpc/), applied by [scripts/apply_refined_mpc.sh](../scripts/apply_refined_mpc.sh) with a first-time `.orig` backup and byte-compare idempotency:

- `modules/control/controller/mpc_controller/mpc_controller.cc` - refined control law (from the bridge upstream, refined_controller lineage)
- `modules/control/controller/mpc_controller/mpc_controller.h` - same file with one include fix: line 29 points at `modules/common_msgs/config_msgs/vehicle_config.pb.h` (the v8 common_msgs location) instead of the v7-era `modules/common/configs/proto/vehicle_config.pb.h`
- `modules/control/conf/control_conf.pb.txt` - retuned matrix_q / matrix_r gains; the tuned values come from the bridge upstream conf and are copied verbatim

The Apollo source tree otherwise stays untouched: everything model- and experiment-specific lives in this repo (scripts, patches, docs), which is what keeps the "one shared toolchain, per-model configs" layout working for the SparseDrive phase.

## Camera profiles

The camera rig lives in the bridge's `carla_bridge/config/objects.json`. [scripts/cam_profile.py](../scripts/cam_profile.py) rewrites it per profile; selection is the CAM_PROFILE env var (default 6cam-lowres):

| profile | cameras | resolution | use |
|---|---|---|---|
| 6cam | 6 | 800x600 | production rig, high-end host |
| 6cam-lowres | 6 | 640x384 | laptop default; closed-loop validated, no downstream impact |
| 2cam | 2 | 640x384 | debug: front pair only, needs VAD_CAM_FALLBACK=replicate |

RELAY_CAMS and the model-side fallback derive from the profile (bring-up sets both): the 2cam profile relays front_6mm + front_12mm and the model service runs with VAD_CAM_FALLBACK=replicate, filling the four missing surround views with the front image. The relay's TCP contract stays 6-slot either way; the fallback lives entirely on the model side.

## Components and logs

| component | runs | log |
|---|---|---|
| CARLA server | host (RenderOffScreen) | run/carla.log |
| bridge main.py | in-container | container /home/bridge.log |
| [relay_cyber_tcp.py](../scripts/relay_cyber_tcp.py) | in-container | stage log (bring-up captures relay startup) |
| [vad_live_service.py](../scripts/vad_live_service.py) | host | run/vad_live.log |
| control module | in-container | container /apollo/control.log |
| watchdog | host loop | run/watchdog.log + run/watchdog_restarts.log |
| topic probe / drive measure | in-container | run/stage4_probe.log / run/stage7_gate2.log |
| gate evaluators | host | run/gate1.json / run/gate2.json / run/latency_summary.json |
