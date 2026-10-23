#!/bin/bash
# Start/stop/exec the Apollo v8 dev container (idempotent).
#
#   scripts/apollo_container.sh start        # create-or-start, background
#   scripts/apollo_container.sh stop         # docker stop (no removal)
#   scripts/apollo_container.sh exec CMD...  # run a command inside
#
# The container mounts the host Apollo source tree at /apollo; Apollo itself
# is never modified at runtime except through scripts/apply_refined_mpc.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"

case "${1:-start}" in
  start)
    if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
        echo "[apollo_container] already running"
        exit 0
    fi
    if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
        echo "[apollo_container] starting existing container"
        docker start "$CONTAINER_NAME"
        exit 0
    fi
    echo "[apollo_container] creating $CONTAINER_NAME"
    docker run -d --name "$CONTAINER_NAME" \
        --net host --shm-size 4G --gpus all \
        -v "$APOLLO_SRC":/apollo \
        "$APOLLO_IMAGE" tail -f /dev/null
    ;;
  stop)
    if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
        docker stop "$CONTAINER_NAME"
    fi
    ;;
  exec)
    shift
    docker exec "$CONTAINER_NAME" "$@"
    ;;
  *)
    echo "usage: $0 {start|stop|exec CMD...}" >&2
    exit 2
    ;;
esac
