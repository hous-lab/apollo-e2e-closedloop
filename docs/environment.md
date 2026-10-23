# Environment

## Machines this pipeline was validated on

| role | GPU | notes |
|---|---|---|
| GPU server | RTX A6000 | closed-loop experiments ran here first; production camera profile (6cam 800x600) |
| laptop | RTX 4090 Laptop GPU, 32G RAM | full pipeline re-validated locally; default profile 6cam-lowres (640x384) |

The laptop is the harder host: CARLA rendering + Apollo control + TRT inference all share one 32G RAM pool and one GPU. The mitigations below are what make it work.

## Software stack

| layer | version |
|---|---|
| CARLA | 0.9.15, `-RenderOffScreen -quality-level=Low`, `__GL_SYNC_TO_VBLANK=0` |
| Apollo | v8.0.0 dev image `registry.baidubce.com/apolloauto/apollo:dev-x86_64-18.04-20221124_1708` |
| bridge | guardstrikelab/carla_apollo_bridge @ b0c2e08 + our 4-patch series |
| bridge python | python3.8 (the image's python), deps via pip, recipe below |
| VAD runtime | host conda env: TensorRT 10.x, torch, pycuda, cv2, msgpack |
| CARLA python | separate host conda env, carla 0.9.15 client package |

The dev container runs with `--net host --shm-size 4G --gpus all`, the Apollo source mounted at /apollo, and the name/ports fixed by scripts/env.sh (CONTAINER_NAME, TCP_PORT). The relay binds 127.0.0.1:9101 inside the container; with net=host the host-side service connects on loopback directly.

## In-container python3.8 deps (bridge runtime)

The dev image ships only python3.6; the bridge wants python3.8. scripts/container_setup.sh installs python3.8 from the Ubuntu bionic mirror (the image's apt sources already point there) and then the pip deps, idempotently (each step skips when its own probe succeeds):

carla==0.9.15 loguru==0.7.0 transforms3d==0.4.1 networkx pyyaml numpy opencv-python-headless protobuf==3.20.3 msgpack

Plus a pip<24 upgrade first (newer pip refuses some of these pins on py3.8). Any PyPI mirror works; container_setup.sh accepts PIP_INDEX_URL (the original flow used a regional mirror for speed). protobuf must stay at 3.20.3 - the Apollo CyberRT python bindings were built against the 3.x ABI.

## Host conda envs

Two environments keep the host side clean:

- CONDA_ENV (default p1bevrc): tensorrt 10.x, torch, pycuda, cv2, msgpack. Runs vad_live_service.py and the gate evaluators. The engines must be built under the same major TRT version as this env's runtime.
- CONDA_ENV_CARLA (default carla_py310): carla 0.9.15 client + numpy. Runs teleport_drive.py and the CARLA client probes (start_carla.sh, restart_sim_pair.sh). Keep it separate so the client API version cannot drift from the server.

## Resource expectations

Disk: >= 20G free for the Apollo container layer + logs (check_env.sh enforces). RAM: the laptop needs >= 8G available beyond page cache; CARLA + control + VAD together sit around 16-20G resident in practice. GPU: the TRT engines occupy ~3-4G; CARLA RenderOffScreen another ~2-4G at 6cam-lowres; leave headroom for the display server if one is running.
