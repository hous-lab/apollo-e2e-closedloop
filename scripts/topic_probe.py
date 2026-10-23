#!/usr/bin/env python3
"""CyberRT topic-rate probe (inside the Apollo container, python3.8).

Counts messages per second on clock / first camera / pose / chassis for a
fixed window (default 15 s). Stage-4 bring-up check: every count must grow
with time before the model side is started.
"""
import os
import time

from cyber_py3 import cyber
from cyber.proto.clock_pb2 import Clock
from modules.common_msgs.sensor_msgs.sensor_image_pb2 import CompressedImage
from modules.common_msgs.localization_msgs.localization_pb2 import LocalizationEstimate
from modules.common_msgs.chassis_msgs.chassis_pb2 import Chassis

CAMS = os.environ.get(
    "RELAY_CAMS",
    "front_6mm,front_12mm,front_right,back,back_left,back_right").split(",")
WINDOW = float(os.environ.get("PROBE_WINDOW", "15"))
counts = {"camera": 0, "pose": 0, "chassis": 0, "clock": 0}


def main():
    assert cyber.init("g1_probe")
    node = cyber.Node("g1_probe")
    node.create_reader("/clock", Clock,
                       lambda m: counts.__setitem__("clock", counts["clock"] + 1))
    node.create_reader("/apollo/sensor/camera/%s/image/compressed" % CAMS[0], CompressedImage,
                       lambda m: counts.__setitem__("camera", counts["camera"] + 1))
    node.create_reader("/apollo/localization/pose", LocalizationEstimate,
                       lambda m: counts.__setitem__("pose", counts["pose"] + 1))
    node.create_reader("/apollo/canbus/chassis",  Chassis,
                       lambda m: counts.__setitem__("chassis", counts["chassis"] + 1))
    t0 = time.time()
    while time.time() - t0 < WINDOW:
        time.sleep(1)
        print("t+%ds camera=%d pose=%d chassis=%d clock=%d" % (
            int(time.time() - t0), counts["camera"], counts["pose"],
            counts["chassis"], counts["clock"]))
    cyber.shutdown()


if __name__ == "__main__":
    main()
