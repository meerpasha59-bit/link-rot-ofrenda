#!/usr/bin/env sh
# Start Gemma 3 1B on CPU with llama.cpp's server (OpenAI-compatible API on :8080).
# Needs llama-server on your PATH (from https://github.com/ggml-org/llama.cpp/releases).
set -e
MODEL_DIR="${MODEL_DIR:-models}"
MODEL="$MODEL_DIR/gemma-3-1b-it-Q4_K_M.gguf"
if [ ! -f "$MODEL" ]; then
  mkdir -p "$MODEL_DIR"
  echo "Downloading Gemma 3 1B instruct (Q4_K_M, ~800 MB) from ggml-org on Hugging Face..."
  curl -L -o "$MODEL" \
    https://huggingface.co/ggml-org/gemma-3-1b-it-GGUF/resolve/main/gemma-3-1b-it-Q4_K_M.gguf
fi
exec llama-server -m "$MODEL" -c 4096 -t "${THREADS:-4}" --host 127.0.0.1 --port 8080
