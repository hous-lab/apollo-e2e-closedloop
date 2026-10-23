#!/bin/bash
# Launch (or relaunch) the Apollo control module inside the container.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    echo "FATAL: container not running" >&2
    exit 1
fi
# kill an existing mainboard first (idempotent relaunch)
docker exec "$CONTAINER_NAME" bash -c "pkill -f 'control.dag' 2>/dev/null" || true
sleep 2
docker exec -d "$CONTAINER_NAME" bash -c "cd /apollo && export APOLLO_ROOT_DIR=/apollo APOLLO_BAZEL_BIN=/apollo/bazel-bin; /apollo/bazel-bin/cyber/mainboard/mainboard -d /apollo/modules/control/dag/control.dag -p control > /apollo/control.log 2>&1 &"
echo "[start_control] control module launched (container log: /apollo/control.log)"
