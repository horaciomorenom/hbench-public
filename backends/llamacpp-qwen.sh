#!/bin/bash
# Example serve script for models.json ("serve": "backends/llamacpp-qwen.sh"). hbench runs it in the background and
# waits until http://127.0.0.1:8081/v1/models answers; it must stay in the foreground (exec the server).
# Edit LLAMA and MODEL for your machine. --jinja and --reasoning-format deepseek send thinking as reasoning_content.
LLAMA=${LLAMA:-$HOME/llama.cpp/build/bin/llama-server}
MODEL=${MODEL:-$HOME/models/Qwen3-8B-Q4_K_M.gguf}
exec "$LLAMA" -m "$MODEL" --host 127.0.0.1 --port 8081 --alias qwen3-8b \
  -c 32768 -ngl 99 --jinja --reasoning-format deepseek -fa on
