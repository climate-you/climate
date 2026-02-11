#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

INPUT="${1:-$ROOT_DIR/drafts/three_wire_globe_clouds/data/clouds_8192x4096.jpg}"
OUTPUT="${2:-$ROOT_DIR/web/public/data/textures/clouds_4096_mercator_alpha.webp}"
WIDTH="${3:-4096}"
HEIGHT="${4:-2048}"
QUALITY="${5:-46}"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required but was not found in PATH" >&2
  exit 1
fi

if [[ ! -f "$INPUT" ]]; then
  echo "Input file not found: $INPUT" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"

FILTER_COMPLEX="[0:v]v360=input=equirect:output=mercator:w=${WIDTH}:h=${HEIGHT}:interp=lanczos,format=gray[a];color=white:s=${WIDTH}x${HEIGHT}[white];[white][a]alphamerge"
FILTER_COMPLEX_WEBP="${FILTER_COMPLEX},format=yuva420p"

case "$OUTPUT" in
  *.png)
    ffmpeg -y -i "$INPUT" \
      -filter_complex "$FILTER_COMPLEX" \
      -frames:v 1 -update 1 "$OUTPUT"
    ;;
  *.webp)
    ffmpeg -y -i "$INPUT" \
      -filter_complex "$FILTER_COMPLEX_WEBP" \
      -frames:v 1 \
      -c:v libwebp -compression_level 6 -q:v "$QUALITY" \
      "$OUTPUT"
    ;;
  *)
    echo "Unsupported output extension for $OUTPUT (use .png or .webp)" >&2
    exit 1
    ;;
esac

echo "Generated $OUTPUT"
