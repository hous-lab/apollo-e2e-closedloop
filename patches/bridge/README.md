Bridge patch series

Five patches against
[guardstrikelab/carla_apollo_bridge](https://github.com/guardstrikelab/carla_apollo_bridge)
at the pinned base commit `b0c2e08` ("Update GettingStarted.md").
[scripts/container_setup.sh](../../scripts/container_setup.sh) clones the upstream repo at that commit into the
Apollo container and applies the series with `git apply` (each
patch applies cleanly on the pinned base and the closed-loop validation in
[docs/validation.md](../../docs/validation.md) is run against the full series).

| Patch | File | What it changes and why |
|---|---|---|
| `0001-e2e-camera-rig-six-cameras.patch` | `carla_bridge/config/objects.json` | replaces the upstream 2-camera + lidar/radar/gnss/imu rig with a 6-camera surround rig (front_6mm yaw 0, front_12mm yaw 55, front_right yaw -55, back yaw 180, back_left yaw 125, back_right yaw -125; all 800x600 fov 90) - the image set the VAD model consumes; lidar/radar/gnss/imu removed (camera-only model) |
| `0002-host-loopback-settings.patch` | `carla_bridge/config/settings.yaml` | CARLA host `172.17.0.1` -> `127.0.0.1` (bridge runs in the Apollo container with `--net=host`, so the simulator is on loopback) |
| `0003-loguru-warning-fix.patch` | `carla_bridge/core/actor_factory.py` | `log.warn` -> `log.warning`: loguru 0.7 removed `.warn`; the AttributeError killed the bridge tick thread whenever a sensor update path hit the warning |
| `0004-tick-loop-reconnect.patch` | `carla_bridge/main.py` | tick-loop hardening: whole-loop try/except + `reconnect_carla()` - 3 consecutive tick failures rebuild the `carla.Client` and back off 5 s; previously a CARLA sync-mode hiccup silently killed the tick thread |
| `0005-bridge-sync-drain-tolerate-late-frames.patch` | `carla_bridge/sensor/sensor.py` | synchronous-mode drain fix: upstream drains each sensor queue once per tick and only processes a frame whose CARLA frame number equals the current tick; if the current-tick image has not arrived over the CARLA stream yet (arrival order depends on image size and spawn order), it is consumed-and-dropped or left queued, and the camera starves forever (observed on a laptop GPU: first-spawned camera published one frame then went silent). The patch keeps the newest stale frame from the drain and publishes it when the queue empties without a current-tick match, so every camera publishes every tick regardless of stream arrival timing. |

The vendored `carla-0.9.14-*.egg` is intentionally NOT patched: `git diff`
reports a phantom 29 MB -> 133 B change on it (LFS clean-filter artifact),
the egg is actually unmodified, and the container stack uses
`pip install carla==0.9.15` instead (the egg is never put on PYTHONPATH).
