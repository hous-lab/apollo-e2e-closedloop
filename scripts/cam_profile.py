#!/usr/bin/env python3
"""Rewrite the bridge camera rig per $CAM_PROFILE (in-container, python3.8).

Profiles:
  6cam        keep the patched rig as-is (6x 800x600, GPU-server production profile)
  6cam-lowres all six cameras at 640x384 (laptop default; tick-budget proven on
              this rig in the G3 experiments - no downstream impact)
  2cam        keep only the front pair (debug; requires VAD_CAM_FALLBACK=replicate
              and RELAY_CAMS=front_6mm,front_12mm on the model side)

The relay and the model service read RELAY_CAMS / VAD_CAM_FALLBACK; start_vad.sh
and the bring-up stage that launches them derive both from $CAM_PROFILE.
"""
import json
import os

BRIDGE_CFG = os.environ.get(
    "BRIDGE_CFG_PATH",
    "/home/carla_apollo_bridge/carla_bridge/config/objects.json")
PROFILE = os.environ.get("CAM_PROFILE", "6cam-lowres")
LOWRES_W, LOWRES_H = 640, 384


def main():
    with open(BRIDGE_CFG) as f:
        cfg = json.load(f)
    ego = next(o for o in cfg["objects"] if o.get("id") == "ego_vehicle")
    cams = [s for s in ego["sensors"] if s.get("type") == "sensor.camera.rgb"]
    before = json.dumps(cfg, sort_keys=True)

    if PROFILE == "6cam":
        for c in cams:
            c["image_size_x"], c["image_size_y"] = 800, 600
    elif PROFILE == "6cam-lowres":
        for c in cams:
            c["image_size_x"], c["image_size_y"] = LOWRES_W, LOWRES_H
    elif PROFILE == "2cam":
        keep = {"front_6mm", "front_12mm"}
        ego["sensors"] = [s for s in ego["sensors"]
                          if s.get("type") != "sensor.camera.rgb" or s.get("id") in keep]
        cams = [s for s in ego["sensors"] if s.get("type") == "sensor.camera.rgb"]
    else:
        raise SystemExit("unknown CAM_PROFILE: %s (6cam | 6cam-lowres | 2cam)" % PROFILE)
    if json.dumps(cfg, sort_keys=True) != before:
        with open(BRIDGE_CFG, "w") as f:
            json.dump(cfg, f, indent=2)
        print("cam_profile: rewrote %s for profile %s" % (BRIDGE_CFG, PROFILE))
    print("cam_profile: profile=%s cameras=%s" % (
        PROFILE, ",".join(c["id"] for c in cams)))
    if PROFILE == "2cam":
        print("cam_profile: set RELAY_CAMS=front_6mm,front_12mm and "
              "VAD_CAM_FALLBACK=replicate on the model side")
    else:
        print("cam_profile: relay env stays at the default six cameras")


if __name__ == "__main__":
    main()
