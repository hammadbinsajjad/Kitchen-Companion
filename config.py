# ALL backend config lives here. Swapping MODEL_BASE_URL must change nothing else.

# llama.cpp llama-server (OpenAI-compatible API)
MODEL_BASE_URL = "http://127.0.0.1:8080/v1"

# App
APP_HOST = "0.0.0.0"
APP_PORT = 8000

# Upload limits
MAX_IMAGES = 15
MAX_IMAGE_BYTES = 5 * 1024 * 1024   # ~5 MB each
MAX_AUDIO_BYTES = 4 * 1024 * 1024   # ~4 MB (60 s of opus is far below this)
MAX_AUDIO_SECONDS = 60

# Debug: save received audio clips here (empty string = don't save)
AUDIO_DEBUG_DIR = "temp/recordings"

# Image downscale: max px on the long edge before sending to the model
MAX_IMAGE_EDGE = 1280

# Generation
MAX_TOKENS = 32768  # output cap; ctx must exceed input + this (set in run_model.sh)

# Sampling override — only used if JSON output proves unreliable (see PLAN.md §3.3)
TEMPERATURE_OVERRIDE = None  # e.g. 0.2
