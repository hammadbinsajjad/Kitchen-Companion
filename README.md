# Kitchen Companion

Photograph your fridge, fix the detected ingredient list on screen, and get meal
suggestions in Roman Urdu from a kitchen companion chatbot that answers typed
**and spoken** follow-ups.

All AI runs **locally** on your laptop via llama.cpp — zero cloud calls at runtime.

## Run it

1. Start the model server (first run downloads the model from Hugging Face):

   ```bash
   ./run_model.sh
   ```

2. Start the app (separate terminal):

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
   ```

3. On your phone (same Wi-Fi): open `http://<laptop-ip>:8000`.

## How it works

One AI endpoint, `POST /api/chat`:

- **images attached** → vision turn: returns the detected ingredient list
- **text / audio clip** → conversation turn: Roman Urdu reply + the full current
  ingredient list (so spoken or typed corrections like *"tamatar nahi hai"* update
  the chips; manual chip ✕ / + add work too)
- **images + text/audio** → vision turn that also acknowledges your note

The frontend keeps the conversation history and re-sends it each turn; the backend
is stateless.

## Config

- `config.py` — backend: `MODEL_BASE_URL`, ports, upload limits, image downscale size,
  token cap. Swapping `MODEL_BASE_URL` changes nothing else.
- `static/config.js` — frontend: API base path, record length, image cap.

The friend's model server is started with `run_model.sh`; sampling defaults
(temperature 1.0, top-p 0.95, top-k 64) are set there, per Gemma's recommended config.

## Notes

- Plain HTTP over LAN — use it on a trusted network.
- **Mic permission on the LAN IP:** browsers only grant `getUserMedia` on secure origins
  (HTTPS or localhost). Over plain HTTP:
  - **Firefox**: `about:config` → set `media.devices.insecure.enabled` and
    `media.getusermedia.insecure.enabled` to `true` (also available in Firefox Android).
  - **Chrome**: `chrome://flags/#unsafely-treat-insecure-origin-as-secure` → add
    `http://<laptop-ip>:8000` → relaunch.
  Or serve HTTPS with a self-signed cert (`uvicorn --ssl-certfile/--ssl-keyfile`).
  The app shows a browser-specific hint when you tap 🎤 on an insecure origin.
- Audio input goes straight to the model (Gemma's native audio understanding);
  there is no speech-to-text layer.
- Optional local TTS (read-aloud replies) is planned as Phase 4 but not implemented.
