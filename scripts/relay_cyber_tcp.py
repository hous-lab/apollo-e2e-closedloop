#!/usr/bin/env python3
"""CyberRT <-> TCP relay (runs inside the Apollo container, python3.8).

Model-agnostic boundary of the pipeline: forwards the latest frame of each
camera channel plus pose/chassis/clock to a loopback TCP endpoint, and
publishes whatever waypoint plan comes back as /apollo/planning. Any
end-to-end model answering the contract in docs/model_contract.md can drive
Apollo without touching it; the host-side counterpart is
scripts/vad_live_service.py.
"""
import math
import os
import socket
import struct
import threading
import time

import msgpack

from cyber_py3 import cyber
from cyber.proto.clock_pb2 import Clock
from modules.common_msgs.sensor_msgs.sensor_image_pb2 import CompressedImage
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
from modules.common_msgs.chassis_msgs.chassis_pb2 import Chassis
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory

CAMS = os.environ.get(
    "RELAY_CAMS",
    "front_6mm,front_12mm,front_right,back,back_left,back_right").split(",")
TCP_PORT = int(os.environ.get("TCP_PORT", "9101"))
TRAJ_SPEED = float(os.environ.get("TRAJ_SPEED", "3.0"))
STATE = {"jpegs": {k: b"" for k in CAMS}, "cam_ts": 0.0, "x": 0.0, "y": 0.0, "yaw": 0.0,
         "v": 0.0, "sim_t": 0.0}


def make_cam_cb(key):
    def on_cam(m):
        STATE["jpegs"][key] = m.data
        STATE["cam_ts"] = m.measurement_time
    return on_cam


def on_pose(m):
    p = m.pose.position
    q = m.pose.orientation
    yaw = math.atan2(2.0 * (q.qz * q.qw + q.qx * q.qy),
                     1.0 - 2.0 * (q.qy * q.qy + q.qz * q.qz))
    STATE["x"] = p.x
    STATE["y"] = p.y
    STATE["yaw"] = yaw


def on_chassis(m):
    STATE["v"] = m.speed_mps


def on_clock(m):
    STATE["sim_t"] = m.clock


def build_traj(wp, sim_t, seq):
    t = ADCTrajectory()
    t.header.sequence_num = seq
    t.header.module_name = "planning"
    t.header.timestamp_sec = sim_t
    t.header.frame_id = "world"
    for i, (x, y) in enumerate(wp):
        pt = t.trajectory_point.add()
        pp = pt.path_point
        pp.x = float(x)
        pp.y = float(y)
        pp.theta = 0.0
        pp.s = 0.5 * i
        pt.v = TRAJ_SPEED
        pt.a = 0.0
        pt.relative_time = 0.1 * i
    t.gear = 1
    return t


def client_loop(conn):
    # stable node name across reconnects (a timestamped name leaked nodes)
    node = cyber.Node("relay_pub")
    w = node.create_writer("/apollo/planning", ADCTrajectory, 10)
    seq = [0]
    f = conn.makefile("rb")
    conn.settimeout(2.0)
    try:
        while True:
            # 1) send the latest obs snapshot
            obs = {"jpegs": [STATE["jpegs"][k] for k in CAMS], "cam_ts": STATE["cam_ts"],
                   "x": STATE["x"], "y": STATE["y"], "yaw": STATE["yaw"],
                   "v": STATE["v"], "sim_t": STATE["sim_t"]}
            data = msgpack.packb(obs, use_bin_type=True)
            conn.sendall(struct.pack(">I", len(data)) + data)
            # 2) receive the model reply and publish it as planning. A skip on the
            # model side (incomplete camera set, failed decode) must not deadlock
            # this loop: a reply-read timeout simply resends the next snapshot.
            try:
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
                tr = msgpack.unpackb(body, raw=False)
                t = build_traj(tr["wp"], STATE["sim_t"], seq[0] + 1)
                w.write(t)
                seq[0] += 1
            except socket.timeout:
                continue
    except Exception as e:
        print("client_loop end:", e)
    finally:
        conn.close()


def main():
    assert cyber.init("vad_relay")
    node = cyber.Node("vad_relay")
    for k in CAMS:
        node.create_reader("/apollo/sensor/camera/%s/image/compressed" % k,
                           CompressedImage, make_cam_cb(k))
    node.create_reader("/apollo/localization/pose", LocalizationEstimate, on_pose)
    node.create_reader("/apollo/canbus/chassis", Chassis, on_chassis)
    node.create_reader("/clock", Clock, on_clock)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", TCP_PORT))
    srv.listen(1)
    print("relay listening :%d cams=%s" % (TCP_PORT, ",".join(CAMS)), flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=client_loop, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
