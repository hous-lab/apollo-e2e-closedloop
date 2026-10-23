# apollo-e2e-closedloop

Drive a CARLA-simulated vehicle with an end-to-end planning model inside Apollo, closed-loop: the model sees the CARLA surround-view cameras, publishes its plan as ADCTrajectory on /apollo/planning, and the Apollo control module steers the CARLA ego from that plan.

The project demonstrates the integration of TensorRT-quantized end-to-end driving models into the Apollo CyberRT stack, with a model-agnostic relay so the model runs outside the Apollo container (host TensorRT 10.x) while everything Apollo-side stays stock except a small control overlay. VAD is integrated and validated; SparseDrive is the next model on the same toolchain (insertion checklist in docs/model_contract.md).

## Results

Measured on the validation host (RTX 4090 Laptop GPU, 32G RAM), CAM_PROFILE=6cam-lowres, engines backbone_int8 + head_withprev_fp16_fixed_v2 (see ckpts/README.md):

| metric | value | source |
|---|---|---|
| gate 1 (waypoint sanity, 30 s) | PASS - 195 frames, plan extent <= 2.82 m, infer p50 130 ms | run/gate1.json |
| gate 2 (closed loop, 300 s window) | PASS - net displacement 8.6 m, max speed 3.1 m/s, 0 watchdog restarts | run/gate2.json |
| gate 3 (latency, n=18061) | p50 191.7 ms, p90 228.1 ms, p99 376 ms, plan rate 5.2 Hz; GPU SM util 34.9% | run/latency_summary.json |

Earlier GPU-server (RTX A6000) closed-loop reference: ~130 m driven at sustained 0.33-0.66 m/s under real throttle, production 6cam 800x600 profile.

## Architecture in one screen

```
CARLA 0.9.15 -> bridge (Apollo dev container) -> relay (CyberRT <-> TCP msgpack)
                                                     | 127.0.0.1:9101
             host vad_live_service.py (TRT engines) <-
             ADCTrajectory -> /apollo/planning -> refined MPC -> ControlCommand -> CARLA ego
```

Full data path, design rationale, and the per-component log table: docs/architecture.md.

## Quick start

1. Get the prerequisites: CARLA 0.9.15, the Apollo v8 dev docker image, an Apollo v8.0.0 source tree, and the VAD TensorRT engines + plugin (download table in ckpts/README.md).
2. Fill scripts/env.sh inputs via environment variables (CARLA_ROOT, APOLLO_SRC, VAD_ENGINES_DIR, VAD_PLUGIN, conda env names); check_env.sh verifies every row and prints fix pointers on miss.
3. Bring the whole loop up in numbered stages with per-stage logs and fail-fast: scripts/run_bringup.sh (flags --from-stage/--to-stage; RUN_SKIP_BUILD=1 skips the long control build on rerun).
4. Watch gate 1/2/3 verdicts land in run/gate1.json, run/gate2.json, run/latency_summary.json.

Stage table, gate definitions, and per-stage troubleshooting: docs/bring_up.md and docs/validation.md.

## Hardware honesty

The laptop run shares one 32G RAM pool and one GPU across CARLA rendering, Apollo control, and TRT inference. It works with the defaults (6cam-lowres, serial gates, watchdog budget) but is not headroom-rich; on a 32G host keep other GPU/RAM consumers idle during a run. Gate 2's watchdog budget exists precisely because CARLA RenderOffScreen can stall periodically on this class of host - see docs/known_issues.md.

## Acknowledgements

- guardstrikelab/carla_apollo_bridge - the CARLA-Apollo bridge this project patches (see NOTICE for the full attribution list)
- Apollo (Apache-2.0) and CARLA (MIT) - the two stacks being integrated
- hustvl/VAD - the VAD model; engines are built from it by hous-lab/vad-trt-edge
- SparseDrive integration (next phase) reuses this toolchain unchanged outside models/sparsedrive/

License: Apache-2.0 (see LICENSE and NOTICE).
