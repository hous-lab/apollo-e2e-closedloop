# Model contract: how a model plugs into the loop

This doc is the model insertion contract: the relay, bridge, control overlay, and bring-up stages are model-agnostic, and a new end-to-end model only adds a host-side service plus engine pointers. Two models are integrated this way - VAD and SparseDriveV2.

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

## SparseDriveV2 deltas

Implemented in scripts/sparsedrive_live_service.py (same TCP contract, same world transform, and the same log line format - check_gate1.py needed zero changes; only the gate-1 infer band differs, 20,200 vs 80,250 ms, per engine timing).

1. Engines: 4-engine fp16 cascade from hous-lab/sparsedrive-trt-edge (backbone, head, map, motion_plan) plus libplugins.so and the demo-npz anchor_embed constant bank, wired through the SPARSEDRIVE_* env knobs in scripts/env.sh.
2. Camera mapping: bridge camera order [front_6mm, front_12mm(+55 left), front_right(-55), back, back_left, back_right] permutes to the SparseDrive order [FRONT, FRONT_RIGHT, FRONT_LEFT, BACK, BACK_LEFT, BACK_RIGHT] with indices [0, 2, 1, 3, 4, 5]; preprocessing is resize-to-width-704 (aspect kept) + crop-top to 384 rows + ImageNet norm; CAM_FALLBACK=replicate works like the VAD knob.
3. Motion engine inputs (16): feat_flat [1,6,22440,256], spat_shape [4,2] i32, lvl_start [4] i32, det_cls/reg/instance_feat (head outputs), det_anchor_embed (constant bank), map_cls/instance_feat/anchor_embed (map outputs), projection_mat [6,4,4], image_wh [6,2], tp_near [2] = (0, 3) (lateral, forward), queue_temp_feat/anchor [21,1,901,256] (zeros with slot QL-1 = current frame), period [1,901] = 20. The deployed engine takes no ego_status / command / timestamp / mask inputs - those exist only in the PyTorch reference path.
4. Decode: argmax over sigmoid(traj_cls [1,1024]) gives row=idx//16 (lateral anchor), col=idx%16 (lon anchor); lat_anchor[row] is a [15,2] path in (lateral, forward) layout with lateral + left; the service converts to ego (x fwd, y left) and samples anchor points 2,4,6,8,10,12 (3-13 m forward) as the 6 output waypoints.
5. Simplifications: fixed target point tp_near=(0,3) and no ego speed reaching the engine, pseudo-projection (pinhole fov-90 at 704x384 with camera-yaw rotation, camera at lidar origin), constant det_anchor_embed bank, single-frame queue. Same approximation class as the VAD list above - they bound demo quality, not integration correctness.
