#!/usr/bin/env python3
"""Teleport the ego vehicle to a clean spawn point and prime the throttle.

Host-side CARLA client probe used before a closed-loop measurement window:
parking a stuck/stopped ego at a fresh spawn resets the scenario, and a few
manual throttle ticks get the vehicle moving before the planner takes over.

Requires the host CARLA python API (conda env CONDA_ENV_CARLA in env.sh).
"""
import os
import time

import carla

HOST = os.environ.get("CARLA_HOST", "127.0.0.1")
PORT = int(os.environ.get("CARLA_PORT", "2000"))
SPAWN_INDEX = int(os.environ.get("TELEPORT_SPAWN_INDEX", "8"))
THROTTLE = float(os.environ.get("TELEPORT_THROTTLE", "0.75"))

c = carla.Client(HOST, PORT)
c.set_timeout(20)
w = c.get_world()
m = w.get_map()
w.wait_for_tick(10.0)
veh = [a for a in w.get_actors() if a.type_id.startswith("vehicle")]
v = veh[0]
sp = m.get_spawn_points()[SPAWN_INDEX]
v.set_transform(carla.Transform(sp.location, sp.rotation))
v.set_target_velocity(carla.Vector3D(0, 0, 0))
print("teleported to", round(sp.location.x, 1), round(sp.location.y, 1), flush=True)
time.sleep(1)
for i in range(4):
    v.apply_control(carla.VehicleControl(throttle=THROTTLE, brake=0.0, steer=0.02, gear=1))
    try:
        w.wait_for_tick(3.0)
    except Exception:
        pass
    vel = v.get_velocity()
    print("tick %d: speed=%.2f m/s loc=(%.0f,%.0f)" % (
        i, abs(vel.x) + abs(vel.y) + abs(vel.z),
        v.get_location().x, v.get_location().y), flush=True)
