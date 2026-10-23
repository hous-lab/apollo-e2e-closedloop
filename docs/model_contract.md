# Model contract: how a model plugs into the loop

This doc is the insertion checklist for adding a second end-to-end model (SparseDrive next phase) to the same toolchain. The relay, bridge, control overlay, and bring-up stages are model-agnostic; only the host-side model service differs.

## TCP protocol (relay <-> model service)

One request/response pair per frame, msgpack, 4-byte big-endian length prefix (struct format ">I"):

container -> host request:
{ "jpegs": [bytes x 6], "x": float, "y": float, "yaw": float, "v": float, "sim_t": float }
host -> container response: { "wp": [[x, y] x 6], "seq": int }

Field notes: jpegs is always a 6-slot list in bridge camera order; empty slots arrive as b"" (the model side decides how to fill or reject them). x/y/yaw/v come from CARLA pose, sim_t from /clock. The length prefix travels before every message in both directions.

## Waypoint frames and the ADCTrajectory mapping

The model outputs an ego-frame (6, 2) array (x forward, y left). The host service rotates it into the world frame with the CARLA yaw and translates by (x, y):

    wp_world[i] = R(yaw) @ ego_wp[i] + (ego_x, ego_y)

The relay receives {wp, seq} and publishes one ADCTrajectory per reply on /apollo/planning:

| field | value | why |
|---|---|---|
| trajectory_point i | p.x/p.y from wp_world[i], theta = 0.0, s = 0.5*i, v = TRAJ_SPEED (default 3.0 m/s), relative_time = 0.1*i | MPC needs a geometrically sensible sequence; v is a fixed cruise target, not a model output |
| gear | GEAR_DRIVE | forward demo |

Honest simplifications, all deliberate and documented: theta and v are constants, lidar2img is identity + a 2 m forward translation (camera height approximation), can_bus/shift are zeros, prev_bev starts at zero each session, and the driving command index is fixed to the straight command. These approximations were validated closed-loop (the vehicle tracks the plan) - they bound demo quality, not integration correctness.

## SparseDrive insertion checklist

Same toolchain, model-specific deltas only:

1. Engines: build SparseDrive TRT engines on the host (same TRT major as CONDA_ENV). Add models/sparsedrive/ pointers + env knobs (SPARSEDRIVE_* names) in scripts/env.sh, mirroring the VAD_* block.
2. Host service: write sparsedrive_live_service.py implementing the same TCP contract (connect loopback, msgpack, >I length prefix), with its own pre/post processing. The relay needs zero changes.
3. Camera mapping: map SparseDrive's camera contract onto the 6-slot jpegs list (or a subset + fallback policy like VAD_CAM_FALLBACK=replicate).
4. Output adaptation: whatever the model emits (waypoints, planning trajectories, ego query), reduce it to 6 world-frame [x, y] waypoints per frame before replying - that is all the relay consumes.
5. Bring-up: reuse run_bringup.sh stages as-is; CAM_PROFILE and per-model env vars are the only inputs that change. Gate 1 waypoints come from the new service's log format, so extend check_gate1.py's LINE regex for the new service's log lines.
6. Keep model-specific files under models/<name>/ (pointers + notes) and model-specific knobs in env.sh blocks; no forks of shared scripts.
