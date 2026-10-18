#!/usr/bin/env bash
set -euo pipefail

# Builds BOTH architectures if Docker Buildx/QEMU support is configured.
# This does not publish an image to a registry.
docker buildx inspect --bootstrap
for platform in linux/amd64 linux/arm64; do
  echo "Building ${platform}..."
  docker buildx build --platform "$platform" --progress=plain --output=type=cacheonly .
done
echo "Both architecture builds succeeded."
