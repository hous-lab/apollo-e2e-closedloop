#!/usr/bin/env python3
"""Closed-loop drive measurement (in-container, python3.8).

Subscribes pose / chassis / control for $MEASURE_WINDOW seconds and reports
net displacement, speed stats, and control-command activity as one JSON line
prefixed MEASURE_DRIVE_JSON (stage-7 gate-2 evidence, captured by run_bringup).
"""
import json
import math
import os
import time

from cyber_py3 import cyber
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
from modules.common_msgs.chassis_msgs.chassis_pb2 import Chassis
from modules.common_msgs.control_msgs.control_cmd_pb2 import ControlCommand

WINDOW = float(os.environ.get("MEASURE_WINDOW", "30"))
st = {"x": None, "y": None, "first": None, "last": None, "speeds": [],
      "ctrl": 0, "max_thr": 0.0, "pose_n": 0}

def on_pose(m):
    p = m.pose.position
    st["x"], st["y"] = p.x, p.y
    if st["first"] is None:
        st["first"] = (p.x, p.y)
    st["last"] = (p.x, p.y)
    st["pose_n"] += 1


def on_chassis(m):
    st["speeds"].append(m.speed_mps)


def on_control(m):
    st["ctrl"] += 1
    try:
        st["max_thr"] = max(st["max_thr"], m.throttle)
    except AttributeError:
        import sys
        print("CTL-DUMP type=%s module=%s" % (type(m).__name__, type(m).__module__), file=sys.stderr, flush=True)
        print("CTL-DUMP full_name=%s" % m.DESCRIPTOR.full_name, file=sys.stderr, flush=True)
        print("CTL-DUMP fields=%s" % [f.name for f in m.DESCRIPTOR.fields], file=sys.stderr, flush=True)
        raise


def main():
    assert cyber.init("measure_drive")
    node = cyber.Node("measure_drive")
    node.create_reader("/apollo/localization/pose", LocalizationEstimate, on_pose)
    node.create_reader("/apollo/canbus/chassis", Chassis, on_chassis)
    node.create_reader("/apollo/control", ControlCommand, on_control)
    t0 = time.time()
    while time.time() - t0 < WINDOW:
        time.sleep(0.5)
    import statistics
    d = None
    if st["first"] and st["last"]:
        d = math.hypot(st["last"][0] - st["first"][0], st["last"][1] - st["first"][1])
    rep = {
        "window_s": WINDOW,
        "pose_n": st["pose_n"],
        "net_displacement_m": round(d, 3) if d is not None else None,
        "mean_speed_mps": round(statistics.fmean(st["speeds"]), 3) if st["speeds"] else 0.0,
        "max_speed_mps": round(max(st["speeds"]), 3) if st["speeds"] else 0.0,
        "control_msgs": st["ctrl"],
        "max_throttle": round(st["max_thr"], 3),
    }
    print("MEASURE_DRIVE_JSON " + json.dumps(rep))
    cyber.shutdown()


if __name__ == "__main__":
    main()
