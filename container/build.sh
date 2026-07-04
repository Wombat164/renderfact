#!/usr/bin/env bash
# Canonical build of the renderfact render image.
set -euo pipefail
cd "$(dirname "$0")"
sudo podman build -t localhost/renderfact:latest -f Containerfile .
