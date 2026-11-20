#!/usr/bin/env bash
set -euo pipefail

tag="${1:?Usage: bash scripts/run-lab5-local.sh TAG NEW_OUTPUT_DIR}"
output="${2:?Set the output directory}"
assets="${LAB5_ASSETS:-var/lab5-assets}"
model_sha=fec9d28c7f8dab7c6857d54b56c8264cce57d6f6d9003bd4110f6457f071c65a
engine_sha=ffaf53f17a4601493e6ffb5869c9f0c7d400bb7e124fe0096eee3b65a5862568
mkdir -p "$assets"
if [[ ! -f "$assets/engine.tar.gz" ]]; then
  curl -fL --retry 2 --max-time 240 \
    'https://github.com/ggml-org/llama.cpp/releases/download/b12292/llama-b12292-bin-ubuntu-x64.tar.gz' \
    -o "$assets/engine.tar.gz.part"
  mv "$assets/engine.tar.gz.part" "$assets/engine.tar.gz"
fi
if [[ ! -f "$assets/model.gguf" ]]; then
  curl -fL --retry 2 --max-time 420 \
    'https://huggingface.co/bartowski/mistralai_Ministral-3-3B-Instruct-2512-GGUF/resolve/0a9035302dea19872c96076896304552890a73c2/mistralai_Ministral-3-3B-Instruct-2512-Q4_K_M.gguf' \
    -o "$assets/model.gguf.part"
  mv "$assets/model.gguf.part" "$assets/model.gguf"
fi
printf '%s  %s\n' "$engine_sha" "$assets/engine.tar.gz" "$model_sha" "$assets/model.gguf" | sha256sum --check
tar -xzf "$assets/engine.tar.gz" -C "$assets"
if curl -fsS --max-time 1 http://127.0.0.1:8087/health >/dev/null 2>&1; then
  echo 'Port 8087 already has a healthy server. Stop it before this run.' >&2
  exit 1
fi
"$assets/llama-b12292/llama-server" -m "$assets/model.gguf" \
  --alias ministral-3b-2512 --host 127.0.0.1 --port 8087 -c 4096 \
  -t "${LAB5_THREADS:-8}" --parallel 1 --no-warmup > "$assets/server.log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for attempt in $(seq 1 60); do
  kill -0 "$server_pid"
  if curl -fsS --max-time 1 http://127.0.0.1:8087/health >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS --max-time 2 http://127.0.0.1:8087/health
"${PYTHON:-python}" -m "${AI_EXPERIMENT_MODULE:-ml.experiments.lab5}" --mode local --tag "$tag" \
  --engine-version 'llama.cpp b12292 af6b5243d' --weights-sha256 "$model_sha" --output "$output"
