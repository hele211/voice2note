#!/bin/bash
# Download a whisper.cpp GGML model into ./models/
# Usage: ./scripts/download-model.sh [tiny|base|small|medium|large-v3|...]   (default: small)
set -e
MODEL="${1:-small}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/models"
mkdir -p "$DIR"
OUT="$DIR/ggml-${MODEL}.bin"
URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${MODEL}.bin"
if [ -f "$OUT" ]; then
  echo "Already present: $OUT"
  exit 0
fi
echo "Downloading ggml-${MODEL}.bin ..."
curl -fL --retry 3 -o "$OUT" "$URL"
echo "Done: $OUT ($(du -h "$OUT" | cut -f1))"
