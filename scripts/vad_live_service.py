#!/usr/bin/env python3
"""VAD live service (host side; conda env with TensorRT 10.x + torch).

Connects to the in-container relay over loopback TCP, turns each obs into a
6-waypoint world-frame plan via two TensorRT engines (backbone + head), and
streams the reply back. All knobs come from the environment contract in
scripts/env.sh - no hardcoded paths.

Known simplifications (documented, deliberate):
  - lidar2img is identity + a 2 m forward translation; can_bus/shift are
    zeros; prev_bev starts at zero each session; command index 0.
  - VAD_CAM_FALLBACK=replicate fills missing surround views with the front
    image (debug profile for weak hosts; numerics otherwise unchanged).
"""
import ctypes
import csv
import math
import os
import socket
import struct
import time

import cv2
import msgpack
import numpy as np
import torch

# --- environment contract (scripts/env.sh) ---------------------------------
PLUGIN = os.environ.get("VAD_PLUGIN", "")
ENGINES_DIR = os.environ.get("VAD_ENGINES_DIR", "")
BB_ENGINE = os.environ.get("VAD_BB_ENGINE", "backbone_int8.engine")
HD_ENGINE = os.environ.get("VAD_HD_ENGINE", "head_withprev_fp16_fixed_v2.engine")
TCP_PORT = int(os.environ.get("TCP_PORT", "9101"))
CAM_FALLBACK = os.environ.get("VAD_CAM_FALLBACK", "")
# Latency log: default <repo>/run/vad_latency.csv; VAD_LATENCY_CSV=none disables it.
LATENCY_CSV = os.environ.get("VAD_LATENCY_CSV",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'run', 'vad_latency.csv'))

if not PLUGIN or not os.path.isfile(PLUGIN):
    raise SystemExit("VAD_PLUGIN missing or not a file: %r (see ckpts/README.md and scripts/env.sh)" % PLUGIN)
if not ENGINES_DIR or not os.path.isdir(ENGINES_DIR):
    raise SystemExit("VAD_ENGINES_DIR missing or not a dir: %r (see ckpts/README.md)" % ENGINES_DIR)
BB_PATH = os.path.join(ENGINES_DIR, BB_ENGINE)
HD_PATH = os.path.join(ENGINES_DIR, HD_ENGINE)

MEAN = np.array([123.675, 116.28, 103.53], dtype=np.float32)
STD = np.array([58.395, 57.12, 57.375], dtype=np.float32)
CMD_IDX = 0  # B2D six-command one-hot; demo uses the straight command

# plugins must be registered before tensorrt loads the engines
ctypes.CDLL(PLUGIN, mode=ctypes.RTLD_GLOBAL)
import tensorrt as trt  # noqa: E402
trt.init_libnvinfer_plugins(trt.Logger(trt.Logger.WARNING), '')
import pycuda.driver as cuda  # noqa: E402
import pycuda.autoinit  # noqa: E402


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


BB, BB_CTX, BB_STREAM = load_engine(BB_PATH)
HD, HD_CTX, HD_STREAM = load_engine(HD_PATH)
BB_IN, BB_OUT = io_map(BB)
HD_IN, HD_OUT = io_map(HD)
BB_IN_NAME, BB_IN_SHAPE = BB_IN[0]
BB_H, BB_W = BB_IN_SHAPE[2], BB_IN_SHAPE[3]
PREV_BEV = torch.zeros([40000, 1, 256], dtype=torch.float32, device="cuda:0")
LIDAR2IMG = torch.eye(4, dtype=torch.float32).repeat(6, 1, 1).cuda()
LIDAR2IMG[:, 2, 3] = 1.0  # 2 m camera-height forward translation approximation
CAN_BUS = torch.zeros(1, 18, dtype=torch.float32, device="cuda:0")
SHIFT = torch.zeros(1, 2, dtype=torch.float32, device="cuda:0")


def prepare_planes(jpegs):
    """JPEGs -> 6 normalized planes; VAD_CAM_FALLBACK=replicate fills gaps."""
    planes = [None] * 6
    first = None
    for idx, jb in enumerate(jpegs[:6]):
        if not jb:
            continue
        arr = np.frombuffer(jb, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            continue
        img = cv2.resize(img, (BB_W, BB_H))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
        img = (img - MEAN) / STD
        planes[idx] = torch.from_numpy(img).permute(2, 0, 1)
        if first is None:
            first = planes[idx]
    if CAM_FALLBACK == "replicate":
        if first is None:
            return None
        planes = [p if p is not None else first for p in planes]
    if any(p is None for p in planes):
        return None
    return planes


def infer(jpegs):
    planes = prepare_planes(jpegs)
    if planes is None:
        return None
    six = torch.stack(planes).unsqueeze(0)  # (1,6,3,H,W)
    flat = six.reshape(6, 3, BB_H, BB_W).contiguous().cuda()
    outs = {n: torch.zeros(s, dtype=torch.float32, device="cuda:0") for n, s in BB_OUT}
    for i in range(BB.num_io_tensors):
        n = BB.get_tensor_name(i)
        src = flat if str(BB.get_tensor_mode(n)).endswith('INPUT') else outs[n]
        BB_CTX.set_tensor_address(n, int(src.data_ptr()))
    BB_CTX.execute_async_v3(stream_handle=BB_STREAM.handle)
    BB_STREAM.synchronize()
    feats = [outs['out.%d' % i].transpose(0, 1).contiguous().float()
             for i in range(0, 4)]
    fmap = {'img_metas.0[shift]': SHIFT.clone(), 'img_metas.0[can_bus]': CAN_BUS.clone(),
            'img_metas.0[lidar2img]': LIDAR2IMG.clone(), 'prev_bev': PREV_BEV.clone()}
    fmap.update({'mlvl_feats.%d' % i: feats[i] for i in range(4)})
    h_out = {n: torch.zeros(s, dtype=torch.float32, device="cuda:0") for n, s in HD_OUT}
    hmap = dict(fmap)
    hmap.update(h_out)
    for i in range(HD.num_io_tensors):
        n = HD.get_tensor_name(i)
        HD_CTX.set_tensor_address(n, int(hmap[n].data_ptr()))
    HD_CTX.execute_async_v3(stream_handle=HD_STREAM.handle)
    HD_STREAM.synchronize()
    ego_out = None
    for n in h_out:
        if 'ego_fut_preds' in n:
            ego_out = h_out[n]
    if ego_out is None:
        return None
    return ego_out[0][CMD_IDX].cpu().numpy()  # (6,2) ego frame


def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", TCP_PORT))
    f = s.makefile('rb')
    print('connected to relay', flush=True)
    seq = 0
    csv_fh = None
    csv_writer = None
    if LATENCY_CSV and LATENCY_CSV.lower() != "none":
        os.makedirs(os.path.dirname(LATENCY_CSV), exist_ok=True)
        new = not os.path.exists(LATENCY_CSV)
        csv_fh = open(LATENCY_CSV, 'a', newline='')
        csv_writer = csv.writer(csv_fh)
        if new:
            csv_writer.writerow(['seq', 'infer_ms'])
    try:
        while True:
            hdr = f.read(4)
            if len(hdr) < 4:
                break
            (n,) = struct.unpack(">I", hdr)
            body = b''
            while len(body) < n:
                chunk = f.read(n - len(body))
                if not chunk:
                    break
                body += chunk
            obs = msgpack.unpackb(body, raw=False)
            if not any(obs.get('jpegs', [])):
                continue
            t0 = time.time()
            eg = infer(obs['jpegs'])
            dt = (time.time() - t0) * 1000
            if eg is None:
                continue
            yaw = obs.get('yaw', 0.0)
            px, py = obs.get('x', 0.0), obs.get('y', 0.0)
            cos_y, sin_y = math.cos(yaw), math.sin(yaw)
            wp = [[float(x * cos_y - y * sin_y + px), float(x * sin_y + y * cos_y + py)]
                  for x, y in eg.tolist()]
            seq += 1
            rep = {'wp': wp, 'seq': seq}
            payload = msgpack.packb(rep, use_bin_type=True)
            s.sendall(struct.pack(">I", len(payload)) + payload)
            rel0 = (wp[0][0] - px, wp[0][1] - py)
            print('frame seq=%d infer=%.0fms ego0=(%.2f,%.2f) w0=(%.1f,%.1f) rel0=(%.1f,%.1f)' % (
                seq, dt, eg[0][0], eg[0][1], wp[0][0], wp[0][1], rel0[0], rel0[1]), flush=True)
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
