#!/bin/bash
# Launch the patched bridge inside the Apollo container (background).
# Usage: docker exec -d $CONTAINER_NAME bash /apollo_scripts/start_bridge.sh
# Container-side copy deployed by scripts/container_setup.sh.
set -e
BRIDGE_DIR="${CONTAINER_BRIDGE_DIR:-/home/carla_apollo_bridge}"
APOLLO_PY_PATHS="/apollo:/apollo/bazel-bin:/apollo/cyber/python:/apollo/bazel-bin/cyber/python/internal"
export PYTHONPATH="${BRIDGE_DIR}:${BRIDGE_DIR}/carla_bridge:${APOLLO_PY_PATHS}"
cd "$BRIDGE_DIR"
exec python3.8 carla_bridge/main.py >> /home/bridge.log 2>&1
