#!/usr/bin/env python3
"""SparseDriveV2 live service: TCP obs -> 4-engine TRT cascade -> 6 waypoints.

Same TCP contract as vad_live_service.py (docs/model_contract.md):
  request  msgpack = {jpegs: [6], x, y, yaw, v, sim_t}
  reply    msgpack = {wp: [[x, y] x 6], seq}

Per frame: 6 compressed cameras (bridge order) -> reorder to SparseDrive camera
order -> decode + resize/crop to 704x384 RGB + ImageNet norm -> backbone ->
feat_0..3 -> head + map heads -> motion plan -> argmax over traj_cls -> lateral
anchor path (lat, fwd) -> ego frame (x fwd, y left) -> world transform.

Deployed-engine simplifications (documented in docs/model_contract.md):
  - the deployed motion engine takes no ego_status / command / timestamp / mask
    inputs at all: planning is camera-driven with a fixed target point
    tp_near = (0, 3) (lateral, forward meters); no ego speed reaches the engine.
  - pseudo-projection: pinhole fov-90 at 704x384 with camera-yaw rotation and
    the camera at the lidar origin (same approximation class as the VAD
    identity lidar2img).
  - det_anchor banks are deploy-side constants (demo npz 'anchor_embed' key);
    queues are fresh single-frame queues (zeros with slot QL-1 = current frame).
"""

import csv
import ctypes
import math
import os
import socket
import struct
import time

import cv2
import msgpack
import numpy as np

# ------------------------------------------------------------- env knobs ---
ENGINES_DIR = os.environ["SPARSEDRIVE_ENGINES_DIR"]
PLUGIN = os.environ["SPARSEDRIVE_PLUGIN"]
ENGINE_FILES = {
    "bb":   os.environ.get("SPARSEDRIVE_BB_ENGINE", "backbone_fp16.engine"),
    "hd":   os.environ.get("SPARSEDRIVE_HD_ENGINE", "head_fp16.engine"),
    "map":  os.environ.get("SPARSEDRIVE_MAP_ENGINE", "map_fp16.engine"),
    "plan": os.environ.get("SPARSEDRIVE_PLAN_ENGINE", "motion_plan_fp16.engine"),
}
ANCHOR_NPZ = os.environ["SPARSEDRIVE_ANCHOR_NPZ"]
CAM_FALLBACK = os.environ.get("CAM_FALLBACK", "")
TCP_PORT = int(os.environ.get("TCP_PORT", "9101"))
LATENCY_CSV = os.environ.get("SPARSEDRIVE_LATENCY_CSV",
                             os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                          "run", "sparsedrive_latency.csv"))

# Bridge camera order: front_6mm(0deg), front_12mm(+55 left), front_right(-55),
# back(180), back_left(+125), back_right(-125). SparseDrive camera order is
# FRONT, FRONT_RIGHT, FRONT_LEFT, BACK, BACK_LEFT, BACK_RIGHT, so the bridge
# slots permute to [0, 2, 1, 3, 4, 5] before preprocessing.
CAM_PERM = [0, 2, 1, 3, 4, 5]
# Optical-axis yaw per SparseDrive camera slot (rad), used by the pseudo-projection.
CAM_YAW = [0.0, math.radians(-55.0), math.radians(55.0),
           math.pi, math.radians(125.0), math.radians(-125.0)]

# ------------------------------------------------------------- constants ---
W_IMG, H_IMG = 704, 384
MEAN = np.array([0.485, 0.456, 0.406], np.float32).reshape(1, 1, 3)
STD = np.array([0.229, 0.224, 0.225], np.float32).reshape(1, 1, 3)
FEAT_SHAPES = [(96, 176), (48, 88), (24, 44), (12, 22)]   # per-level (h, w)
QL, N_INST, N_MAPQ = 21, 900, 100
WP_IDX = (2, 4, 6, 8, 10, 12)   # anchor points kept as output waypoints (fwd ~3-13 m)
TP_NEAR = (0.0, 3.0)            # target point (lat, fwd): 3 m straight ahead

# ------------------------------------------------------------ projection ---
def projection_mats():
    """Pseudo lidar2img [6,4,4]: pinhole fov-90 at 704x384, camera-yaw rotation,
    camera at lidar origin. Same approximation class as the VAD identity
    lidar2img - documented in docs/model_contract.md."""
    fx = fy = (W_IMG / 2.0) / math.tan(math.radians(45.0))   # hfov 90
    cx, cy = W_IMG / 2.0, H_IMG / 2.0
    mats = np.zeros((6, 4, 4), np.float32)
    for i, th in enumerate(CAM_YAW):
        R = np.array([[math.sin(th), -math.cos(th), 0.0],    # cam x = right
                      [0.0, 0.0, -1.0],                      # cam y = down
                      [math.cos(th), math.sin(th), 0.0]],    # cam z = optical axis
                     np.float32)
        P = np.zeros((4, 4), np.float32)
        P[:3, :3] = np.dot(np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], np.float32), R)
        P[3, 3] = 1.0
        mats[i] = P
    return mats

# ---------------------------------------------------------- preprocessing ---
def prepare_plane(jpeg_bytes):
    """jpeg -> BGR decode -> resize to width 704 (aspect kept) -> crop top so the
    bottom 384 rows remain -> RGB float ImageNet norm -> CHW torch plane."""
    img = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    oh = max(H_IMG, int(round(h * 704.0 / w)))
    img = cv2.resize(img, (704, oh), interpolation=cv2.INTER_LINEAR)
    img = img[oh - H_IMG:, :, :]                     # drop the sky band
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - MEAN) / STD
    return torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1)))

def prepare_planes(jpegs):
    """6 torch planes in SparseDrive camera order, or None if unfillable.
    jpegs arrive in bridge order. CAM_FALLBACK=replicate fills missing surround
    slots with the front camera (debug profile)."""
    planes = [None] * 6
    for sd_slot in range(6):
        b = jpegs[CAM_PERM[sd_slot]]
        if b:
            planes[sd_slot] = prepare_plane(b)
    if CAM_FALLBACK == "replicate":
        first = next((p for p in planes if p is not None), None)
        if first is None:
            return None
        planes = [p if p is not None else first for p in planes]
    if any(p is None for p in planes):
        return None
    return planes

# ------------------------------------------------------------- TRT cascade ---
# plugins must be registered before tensorrt deserializes the engines
ctypes.CDLL(PLUGIN, mode=ctypes.RTLD_GLOBAL)
import tensorrt as trt  # noqa: E402
import torch  # noqa: E402
import pycuda.driver as cuda  # noqa: E402
import pycuda.autoinit  # noqa: E402,F401
trt.init_libnvinfer_plugins(trt.Logger(trt.Logger.WARNING), "")

def load_engine(path):
    eng = trt.Runtime(trt.Logger(trt.Logger.WARNING)).deserialize_cuda_engine(
        open(path, 'rb').read())
    return eng, eng.create_execution_context(), cuda.Stream()

def io_map(eng):
    ins, outs = [], []
    for i in range(eng.num_io_tensors):
        n = eng.get_tensor_name(i)
        s = tuple(eng.get_tensor_shape(n))
        (ins if str(eng.get_tensor_mode(n)).endswith('INPUT') else outs).append((n, s))
    return ins, outs

def image_wh():
    return np.tile(np.array([W_IMG, H_IMG], np.float32), (6, 1))

BB, BB_CTX, BB_STREAM = load_engine(os.path.join(ENGINES_DIR, ENGINE_FILES["bb"]))
HD, HD_CTX, HD_STREAM = load_engine(os.path.join(ENGINES_DIR, ENGINE_FILES["hd"]))
MAP, MAP_CTX, MAP_STREAM = load_engine(os.path.join(ENGINES_DIR, ENGINE_FILES["map"]))
PLAN, PLAN_CTX, PLAN_STREAM = load_engine(os.path.join(ENGINES_DIR, ENGINE_FILES["plan"]))
BB_IN, BB_OUT = io_map(BB)
HD_IN, HD_OUT = io_map(HD)
MAP_IN, MAP_OUT = io_map(MAP)
PLAN_IN, PLAN_OUT = io_map(PLAN)
print("engines loaded:", ENGINE_FILES, flush=True)

def _torch(a):
    return torch.from_numpy(np.ascontiguousarray(a)).cuda()

PROJ = _torch(projection_mats())                       # [6,4,4]
IWH = _torch(image_wh())                               # [6,2]
TP_NEAR = _torch(np.array(TP_NEAR, np.float32))        # [2] (lat, fwd)
PERIOD = torch.full((1, N_INST + 1), QL - 1, dtype=torch.long, device="cuda:0")
QUEUE_ZEROS = torch.zeros(QL, 1, N_INST + 1, 256, dtype=torch.float32, device="cuda:0")
_anchor = np.load(ANCHOR_NPZ)["anchor_embed"].reshape(1, N_INST, 256).astype(np.float32)
ANCHOR_EMBED = _torch(_anchor)                         # [1,900,256] constant bank
del _anchor
print("statics ready: proj=%s iwh=%s anchor=%s period=%s" % (
    tuple(PROJ.shape), tuple(IWH.shape), tuple(ANCHOR_EMBED.shape), tuple(PERIOD.shape)), flush=True)


def infer(jpegs):
    """Obs -> 4-engine cascade -> [15,2] path (col0 lateral, col1 forward)."""
    planes = prepare_planes(jpegs)
    if planes is None:
        return None
    img = torch.stack(planes).contiguous().cuda()    # (6,3,384,704) float32
    bb_out = {n: torch.empty(s, dtype=torch.float32, device="cuda:0") for n, s in BB_OUT}
    for i in range(BB.num_io_tensors):
        n = BB.get_tensor_name(i)
        src = img if str(BB.get_tensor_mode(n)).endswith('INPUT') else bb_out[n]
        BB_CTX.set_tensor_address(n, int(src.data_ptr()))
    BB_CTX.execute_async_v3(stream_handle=BB_STREAM.handle)
    BB_STREAM.synchronize()
    feats = [bb_out['feat_%d' % i] for i in range(4)]
    return _motion_stage(feats)


def _motion_stage(feats):
    hd_out = {n: torch.empty(s, dtype=torch.float32, device="cuda:0") for n, s in HD_OUT}
    map_out = {n: torch.empty(s, dtype=torch.float32, device="cuda:0") for n, s in MAP_OUT}
    fmap = dict(hd_out); fmap.update(map_out)
    fmap.update({'feat_%d' % i: feats[i] for i in range(4)})
    fmap.update({'projection_mat': PROJ, 'image_wh': IWH})
    for i in range(HD.num_io_tensors):
        n = HD.get_tensor_name(i)
        HD_CTX.set_tensor_address(n, int(fmap[n].data_ptr()))
    HD_CTX.execute_async_v3(stream_handle=HD_STREAM.handle)
    HD_STREAM.synchronize()
    for i in range(MAP.num_io_tensors):
        n = MAP.get_tensor_name(i)
        MAP_CTX.set_tensor_address(n, int(fmap[n].data_ptr()))
    MAP_CTX.execute_async_v3(stream_handle=MAP_STREAM.handle)
    MAP_STREAM.synchronize()
    flat = torch.cat([feats[i].reshape(6, 256, -1).permute(0, 2, 1).reshape(-1, 256)
                      for i in range(4)], dim=0).view(1, 6, -1, 256).contiguous()
    spat = torch.tensor(FEAT_SHAPES, dtype=torch.int32, device="cuda:0")
    lvl = torch.tensor(np.cumsum([0] + [h * w for h, w in FEAT_SHAPES])[:-1],
                       dtype=torch.int32, device="cuda:0")
    qf = QUEUE_ZEROS.clone()
    qa = QUEUE_ZEROS.clone()
    qf[QL - 1, :, :N_INST, :] = hd_out['det_instance_feat']
    qa[QL - 1, :, :N_INST, :] = ANCHOR_EMBED
    pmap = {
        'feat_flat': flat, 'spat_shape': spat, 'lvl_start': lvl,
        'det_cls': hd_out['det_cls'], 'det_reg': hd_out['det_reg'],
        'det_instance_feat': hd_out['det_instance_feat'],
        'det_anchor_embed': ANCHOR_EMBED,
        'map_cls': map_out['map_cls'],
        'map_instance_feat': map_out['map_instance_feature'],
        'map_anchor_embed': map_out['map_anchor_embed'],
        'projection_mat': PROJ, 'image_wh': IWH,
        'tp_near': TP_NEAR,
        'queue_temp_feat': qf, 'queue_temp_anchor': qa,
        'period': PERIOD,
    }
    plan_out = {n: torch.empty(s, dtype=torch.float32, device="cuda:0") for n, s in PLAN_OUT}
    for i in range(PLAN.num_io_tensors):
        n = PLAN.get_tensor_name(i)
        src = pmap[n] if str(PLAN.get_tensor_mode(n)).endswith("INPUT") else plan_out[n]
        PLAN_CTX.set_tensor_address(n, int(src.data_ptr()))
    PLAN_CTX.execute_async_v3(stream_handle=PLAN_STREAM.handle)
    PLAN_STREAM.synchronize()
    idx = int(torch.argmax(torch.sigmoid(plan_out["traj_cls"][0]).flatten()).item())
    row, col = divmod(idx, 16)
    path = plan_out["lat_anchor"][0, row].cpu().numpy()   # [15,2] (lat, fwd)
    vel = plan_out["lon_anchor"][0, col].cpu().numpy()    # [6] m/s @0.5 s
    wp_ego = [[float(p[1]), float(p[0])] for p in path[list(WP_IDX)]]
    return wp_ego, float(vel.mean())


def main():

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", TCP_PORT))
    f = s.makefile("rb")
    print("connected to relay", flush=True)
    seq = 0
    csv_fh = None
    csv_writer = None
    if LATENCY_CSV and LATENCY_CSV.lower() != "none":
        os.makedirs(os.path.dirname(LATENCY_CSV), exist_ok=True)
        new = not os.path.exists(LATENCY_CSV)
        csv_fh = open(LATENCY_CSV, "a", newline="")
        csv_writer = csv.writer(csv_fh)
        if new:
            csv_writer.writerow(['seq', 'infer_ms'])
    try:
        while True:
            hdr = f.read(4)
            if len(hdr) < 4:
                break
            (n,) = struct.unpack(">I", hdr)
            body = b""
            while len(body) < n:
                chunk = f.read(n - len(body))
                if not chunk:
                    break
                body += chunk
            obs = msgpack.unpackb(body, raw=False)
            if not any(obs.get("jpegs", [])):
                continue
            t0 = time.time()
            out = infer(obs["jpegs"])
            dt = (time.time() - t0) * 1000
            if out is None:
                continue
            wp_ego, vel_mean = out
            yaw = obs.get("yaw", 0.0)
            px, py = obs.get("x", 0.0), obs.get("y", 0.0)
            cos_y, sin_y = math.cos(yaw), math.sin(yaw)
            wp = [[float(x * cos_y - y * sin_y + px), float(x * sin_y + y * cos_y + py)]
                  for x, y in wp_ego]
            seq += 1
            rep = {"wp": wp, "seq": seq}
            payload = msgpack.packb(rep, use_bin_type=True)
            s.sendall(struct.pack(">I", len(payload)) + payload)
            rel0 = (wp[0][0] - px, wp[0][1] - py)
            print('frame seq=%d infer=%.0fms ego0=(%.2f,%.2f) w0=(%.1f,%.1f) rel0=(%.1f,%.1f)' % (
                seq, dt, wp_ego[0][0], wp_ego[0][1], wp[0][0], wp[0][1], rel0[0], rel0[1]), flush=True)
            if csv_writer is not None:
                csv_writer.writerow([seq, round(dt, 2)])
                csv_fh.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if csv_fh is not None:
            csv_fh.close()


if __name__ == "__main__":
    main()
