#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "${HEX_PYTHON:-python3}" -m hexai "$@"
