#!/usr/bin/env python3
"""Synthetic ADCTrajectory publisher (inside the Apollo container, py3.8).

Model-bypass gate: publishes a 30-point straight-ahead trajectory at
constant speed from the current ego pose, 10 Hz for 30 s. Verifies the
downstream chain control -> bridge -> CARLA without any model in the loop
(bring-up stage 6).
"""
import math
import os
import time

from cyber_py3 import cyber
from cyber.proto.clock_pb2 import Clock
from modules.common_msgs.planning_msgs.planning_pb2 import ADCTrajectory
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate

N_POINTS = int(os.environ.get("SYNTH_N_POINTS", "30"))
PT_GAP = float(os.environ.get("SYNTH_PT_GAP", "0.3"))
SPEED = float(os.environ.get("SYNTH_SPEED", "3.0"))
N_FRAMES = int(os.environ.get("SYNTH_N_FRAMES", "300"))
ego = {"x": None, "y": None, "yaw": 0.0}
sim_t = [0.0]


def on_clock(m):
    sim_t[0] = m.clock


def on_pose(m):
    p = m.pose.position
    q = m.pose.orientation
    yaw = math.atan2(2.0 * (q.qz * q.qw + q.qx * q.qy),
                     1.0 - 2.0 * (q.qy * q.qy + q.qz * q.qz))
    ego["x"] = p.x
    ego["y"] = p.y
    ego["yaw"] = yaw


def build_traj(seq=[0]):
    t = ADCTrajectory()
    seq[0] += 1
    t.header.sequence_num = seq[0]
    t.header.module_name = "planning"
    t.header.timestamp_sec = sim_t[0] if sim_t[0] > 0 else time.time()
    t.header.frame_id = "world"
    for i in range(N_POINTS):
        pt = t.trajectory_point.add()
        pp = pt.path_point
        pp.x = ego["x"] + i * PT_GAP * math.cos(ego["yaw"])
        pp.y = ego["y"] + i * PT_GAP * math.sin(ego["yaw"])
        pp.theta = ego["yaw"]
        pp.kappa = 0.0
        pp.s = i * PT_GAP
        pt.v = SPEED
        pt.a = 0.0
        pt.relative_time = i * 0.1
    t.gear = 1  # GEAR_DRIVE
    return t


def main():
    assert cyber.init("synth_traj")
    node = cyber.Node("synth_traj")
    node.create_reader("/apollo/localization/pose", LocalizationEstimate, on_pose)
    node.create_reader("/clock", Clock, on_clock)
    w = node.create_writer("/apollo/planning", ADCTrajectory, 10)
    t0 = time.time()
    while ego["x"] is None and time.time() - t0 < 10:
        time.sleep(0.1)
    if ego["x"] is None:
        print("NO_POSE")
        return
    print("ego @ (%.1f, %.1f) yaw=%.2f" % (ego["x"], ego["y"], ego["yaw"]))
    n = 0
    while n < N_FRAMES:
        w.write(build_traj())
        n += 1
        time.sleep(0.1)
    print("published", n, "trajectories")


if __name__ == "__main__":
    main()
