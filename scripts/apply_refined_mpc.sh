#!/bin/bash
# Overlay the refined MPC controller into the Apollo source tree.

# Apollo stays source-unmodified by design: control tuning ships as three
# overlay files (patches/apollo/refined_mpc/) derived from the bridge
# upstream refined_controller/ (see NOTICE), with one include fix for the
# Apollo v8 common_msgs layout. Idempotent; backs up the first-time originals
# next to themselves as *.orig.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"

SRC="$E2E_REPO_ROOT/patches/apollo/refined_mpc"
# v8 trees differ: some ship mpc_controller as a subdir, some flat in controller/
if [ -d "$APOLLO_SRC/modules/control/controller/mpc_controller" ]; then
    MPC_DIR="$APOLLO_SRC/modules/control/controller/mpc_controller"
else
    MPC_DIR="$APOLLO_SRC/modules/control/controller"
fi
CONF_DIR="$APOLLO_SRC/modules/control/conf"

if [ -z "$APOLLO_SRC" ] || [ ! -d "$APOLLO_SRC/modules/control" ]; then
    echo "FATAL: APOLLO_SRC unset or not an Apollo tree: $APOLLO_SRC" >&2
    exit 1
fi
for f in mpc_controller.cc mpc_controller.h control_conf.pb.txt; do
    if [ ! -f "$SRC/$f" ]; then
        echo "FATAL: missing $SRC/$f" >&2
        exit 1
    fi
done

overlay() {
    local src_f="$1" dst_f="$2"
    if [ ! -e "${dst_f}.orig" ]; then
        cp -p "$dst_f" "${dst_f}.orig"
        echo "backup: $dst_f.orig"
    fi
    if cmp -s "$src_f" "$dst_f"; then
        echo "up to date: $dst_f"
        return 0
    fi
    cp -f "$src_f" "$dst_f"
    echo "overlaid: $dst_f"
}

overlay "$SRC/mpc_controller.cc" "$MPC_DIR/mpc_controller.cc"
overlay "$SRC/mpc_controller.h" "$MPC_DIR/mpc_controller.h"
overlay "$SRC/control_conf.pb.txt" "$CONF_DIR/control_conf.pb.txt"

echo ""
echo "next: rebuild the control module inside the container, e.g.:"
echo "  bash scripts/apollo_container.sh exec bash -c 'cd /apollo && ./apollo.sh build_cpu'"
