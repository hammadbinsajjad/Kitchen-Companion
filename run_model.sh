#!/usr/bin/env bash
# Start the model server (Gemma 4 E4B QAT, vision + audio, MTP speculative decoding).
# Downloaded from Hugging Face on first run (~several GB).
llama serve \
  -hf unsloth/gemma-4-E4B-it-qat-GGUF:UD-Q4_K_XL \
  --temp 1.0 \
  --top-p 0.95 \
  --top-k 64 \
  --ctx-size 65536 \
  --spec-type draft-mtp --spec-draft-n-max 2 \
  --jinja
