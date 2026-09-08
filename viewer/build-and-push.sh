#!/usr/bin/env bash
# Builds the viewer image locally (Gitea Actions runner is arm on a Pi —
# wrong arch for this image), pushes it, then updates the image tag in the
# viewer Deployment manifest so it always matches what's actually running.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPONENT_DIR="$(dirname "${SCRIPT_DIR}")"
IMAGE="your-registry.example.com/your-namespace/reddit-archiver-viewer"

VIEWER_VERSION=$(grep -oP '^ARG VIEWER_VERSION=\K.*' "${SCRIPT_DIR}/Dockerfile")
TAG="${VIEWER_VERSION}"

echo "==> Building ${IMAGE}:${TAG}..."
docker buildx build --platform linux/amd64 \
  -t "${IMAGE}:${TAG}" \
  --push \
  "${SCRIPT_DIR}"

echo "==> Updating manifest image tags to ${TAG}..."
grep -rl "${IMAGE}:" "${COMPONENT_DIR}"/*.yaml | while read -r manifest; do
  sed -i -E "s#${IMAGE}:[A-Za-z0-9._-]+#${IMAGE}:${TAG}#g" "${manifest}"
  echo "    ${manifest}"
done

echo "==> Done. New tag: ${TAG}"
