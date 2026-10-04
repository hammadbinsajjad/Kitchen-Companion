# Kitchen Companion — Build Plan for a Coding Agent

You are building a small, time-boxed web app for the Hacktoberfest Weekend Challenge (theme: "Build for a Friend"). The goal is a working demo by end of day, not a production system. Follow the phase order strictly — do not touch later phases until earlier ones are done and manually tested. When in doubt, choose the simplest implementation that satisfies the acceptance criteria.

---

## 1. What we're building

**Kitchen Companion**: a friend photographs their fridge/cupboard, a locally-run open-weight vision model (Gemma 4 E4B) identifies the ingredients, the friend fixes any mistakes on screen (human-in-the-loop), and the companion suggests meals in **Roman Urdu**.

Core architectural decisions (already made — do not revisit):

- **All AI runs locally** via llama.cpp's `llama-server`. No cloud APIs, no external AI calls, ever.
- **Audio input goes straight to the model** (Gemma's native audio understanding) — no speech-to-text layer, no transcription step.
- **English system prompts** control the model; **user-facing conversation is Roman Urdu** (Urdu written in Latin letters, with common English food words allowed).
- **Model output is structured**: every turn returns `{reply, dishes, ingredients}` — dish suggestions are separate `dishes` objects the frontend renders as tappable cards, not loose text.
- **One AI endpoint, one grammar**: `POST /api/chat` handles every model interaction — images attached = vision turn, text = conversation turn; response is always `{reply, ingredients}`.
- **Ingredients are editable two ways**: manually via the chips UI, or conversationally — every conversation turn's reply includes an updated ingredient list that re-syncs the chips. Any ingredient the friend names (typed or spoken) must survive into the list.
- No profile endpoints or user data files — the app holds no personal data of any kind.
- **Human confirmation between passes**: detected ingredients are shown as editable/removable chips before meal suggestions are generated.
- Served over **LAN on plain HTTP** (phone visits `http://<laptop-ip>:8000`). No HTTPS, no service worker requirement.
- **No STT layer, no authentication, no database, no cloud deployment, no build tooling for the frontend.** Plain HTML/JS, no npm.

---

## 2. Architecture & file structure

Three processes on the developer's laptop:

1. `llama serve` (llama.cpp) on default port **8080** — runs Gemma 4 E4B QAT (auto-downloaded from Hugging Face via `-hf`, vision adapter included) with MTP speculative decoding for speed; exposes an OpenAI-compatible `/v1/chat/completions` endpoint.
2. FastAPI backend on port **8000** — talks to llama-server, serves the static frontend.
3. (Optional, Phase 4) TTS server — same FastAPI process, separate endpoints.

```
kitchen-companion/
├── server.py            # FastAPI app: static files + API endpoints
├── config.py            # ALL backend config: MODEL_BASE_URL, ports, limits, paths
├── prompts.py           # system prompts & few-shot examples (verbatim from this doc)
├── static
│   ├── index.html       # the whole frontend, single file
│   ├── style.css
│   ├── config.js        # ALL frontend config: API base path, UI constants
│   ├── app.js
│   └── manifest.json    # PWA manifest (installable only where HTTPS exists; harmless otherwise)
└── requirements.txt     # fastapi, uvicorn, pillow, python-multipart, openai — nothing else in Phases 1–3
```

**Config rule:** all backend configuration lives in `config.py` — `MODEL_BASE_URL` (default `http://127.0.0.1:8080/v1`, the OpenAI-compatible llama-server endpoint), ports, upload limits, file paths — and all frontend configuration lives in `static/config.js` (API base path, UI constants). No config values anywhere else; the model endpoint must be swappable by editing `config.py` alone. The backend talks to llama-server through the official `openai` client.

Model server startup (developer runs this; put it in a `run_model.sh`). Sampling defaults are set at launch — Gemma's recommended config — so requests generally don't need per-request sampling params:

```bash
llama serve \
  -hf unsloth/gemma-4-E4B-it-qat-GGUF:UD-Q4_K_XL \
  --temp 1.0 \
  --top-p 0.95 \
  --top-k 64 \
  --spec-type draft-mtp --spec-draft-n-max 2 \
  --jinja
```

---

## 3. Phase 1 — One AI endpoint: `POST /api/chat` (vision + conversation)

### 3.1 Endpoint

`POST /api/chat` — multipart/form. The app's only model-facing endpoint; the backend branches on the request shape:

- **Vision turn** (images attached): up to 15 `images` (JPEG/PNG, max ~5 MB each). If the user already tracks ingredients, the current list rides along and the output list is the **union** of it and the photo (merge, case-insensitive on the base name — backend also dedupes); otherwise the list is what's visible. `reply` stays empty unless text/audio rode along (see combined turn).
- **Conversation turn** (no images): `context` text and/or an `audio` clip + current `ingredients` + `messages` history. Works with an empty ingredient list too — the friend can just chat. The model reads spoken input natively — no transcription anywhere. Returns a Roman Urdu reply, up to 3 dish suggestions as structured cards, and an updated ingredient list.
- **Combined turn** (images + text and/or audio, e.g. new photo mid-chat with a note): treated as a vision turn, but the friend's text/clip is passed along with the images and the reply may acknowledge it in Roman Urdu. No intent classification anywhere — the request shape decides the turn type; text/spoken-only ingredient updates need no routing because the conversation prompt returns the full updated list every turn (see §3.2).

Response is always the same shape, constrained by one JSON grammar for both turns:

```json
{ "reply": "", "dishes": [], "ingredients": [ { "item": "eggs", "count": "about 3", "location": "middle shelf", "confidence": "high" } ] }
```

`dishes` carries the 2–3 meal suggestions as separate `{name, note}` objects on conversation turns (empty on vision turns); the frontend renders each as a tappable card — tapping one asks for its steps.

The frontend overwrites its chip list from `ingredients` on every response, so statements like "tamatar nahi hai" update the chips conversationally; chip ✕/"+ add item" remains for instant manual edits. When a turn is a pure question, the returned list is unchanged — the model echoes it back.

### 3.2 Prompts (embed verbatim in `prompts.py`)

The backend picks the system prompt by request shape (images present → vision prompt; else → companion prompt). The prompts stay separate — the vision prompt's anti-hallucination strictness and the companion's Roman Urdu persona pull in opposite directions; one merged prompt degrades both. The request shape already decides the case, so the model never has to guess roles.

**Vision turn system prompt:**

```
You are a kitchen vision assistant. You only report what is visually
verifiable in the images. You never guess from context or from what
fridges typically contain.

Rules:
- Only include items you are confident are visible right now.
- If you are not sure, leave it out. Missing an item is fine; inventing
  one is not.
- For each item, name the shelf or location where you see it.
- Do not mention items that are not clearly identifiable foods or drinks.
```

**Vision turn user message:** the image(s), followed by: `List every food or drink item visible in these images, following the system rules.`

**Companion turn system prompt:**

```
You are a warm, practical kitchen companion for a Pakistani friend.
You suggest meals from the ingredients provided and answer follow-up
questions about cooking.

LANGUAGE RULES (highest priority):
- You always reply in Roman Urdu only: Urdu written in Latin letters
  (e.g. "aaj hum kya banainge?").
- Never reply in English sentences. Never use Urdu/Arabic script.
- Common food words may stay in English (rice, egg, oven, garlic).

CONTENT RULES:
- Suggest dishes ONLY when the user asks for meal/recipe suggestions:
  then give 2–3 dishes in "dishes" that are actually possible with the
  listed ingredients. If something essential is missing for a dish, say
  so and suggest the smallest workaround. You may mention a missing item
  ("do you have anday?") but never invent that an ingredient exists.
- If the user asks for steps, details, or asks a question about a
  specific dish, answer just that — "dishes" stays []. Numbered steps
  go in "reply" when asked for.
- Greetings, thanks, small talk: reply warmly in one or two lines,
  "dishes" stays [].
- When the user names an ingredient anywhere in their message (typed or
  spoken, e.g. "chawal", "aloo"), it MUST appear in the ingredient list —
  never drop a named ingredient.
- Every turn ends with the full current ingredient list in the JSON:
  unchanged when the user only asks a question, corrected when they
  state a change ("tamatar nahi hai", "kheera bhi hai").
- Keep "reply" short; the dish hooks live in "dishes", not prose.

OUTPUT FORMAT (every turn, no exceptions):
- Reply with ONLY one JSON object, no text before or after it:
  {"reply": "...", "dishes": [...], "ingredients": [...]}.
- "reply": your Roman Urdu message (short; dish hooks are in "dishes",
  numbered steps go here when asked).
- "dishes": when you suggest meals, 2–3 items like
  {"name": "Aloo Pulao", "note": "ek pot, 30 minute"}; otherwise [].
- "ingredients": the full current list.

Example exchange:
User: I have: rice, eggs, tomatoes. Something quick please.
Assistant (as JSON):
{"reply": "Perfect combo! Aap 10 minute mein egg fried rice bana sakte ho — leftover rice ke liye best hai. Ya phir masala omelette with toast, agar chapati nahi hai. Steps chahiye to batao.", "dishes": [{"name": "Egg Fried Rice", "note": "10 minute, leftover rice ke liye best"}, {"name": "Masala Omelette", "note": "toast ke saath, jab chapati nahi"}], "ingredients": [{"item": "rice"}, {"item": "eggs"}, {"item": "tomatoes"}]}.
```

Conversation history from `messages` is passed through so follow-ups work; the current ingredient list rides along in every turn, and the corrected list the model returns feeds the next turn.

### 3.3 Generation settings

- Sampling: use the server defaults (`temperature: 1.0`, `top_p: 0.95`, `top_k: 64` — Gemma's recommended config, already set at launch). Do not override per request. Only if JSON output proves unreliable, lower `temperature` for this endpoint (e.g. 0.2) and keep the override in `config.py`.
- **Structured output**: pass a JSON schema or GBNF grammar to llama-server constraining the response to the `{reply, dishes, ingredients}` shape for both turns (llama-server supports `json_schema` / `grammar` in the request, or `--grammar-file` at launch). If grammar wiring proves unreliable, fall back to prompt-only JSON plus robust parsing (strip markdown fences, `json.loads`, validate fields, drop malformed entries) — but try the grammar first.
- `max_tokens: 32768` per request (effectively uncapped — real replies are a few hundred tokens; the cap only prevents runaway). Model-server context covers the input side: 15 images + audio + history need a large ctx, so `run_model.sh` launches with `--ctx-size 65536` (output tokens come out of that context). If replies drift, fix it in the prompt (language rules, few-shot example) first, not in the sampling params.

### 3.4 Image & audio handling

Pass images to llama-server as base64 data URLs in the multimodal message array. Audio clips go as base64 `input_audio` content parts (the browser's MediaRecorder produces webm/opus; cap clips at ~60 s in `config.py` limits — long audio blows the token budget). Downscale images client-side or server-side to max ~1280 px on the long edge before sending (keeps vision tokens and latency reasonable). When a message carries more than one modality, order content parts: **images, then audio, then text** (if any).

---

## 4. Phase 2 — Frontend: single page, confirm-then-cook

One-page **chat-first** layout, mobile-first, thumb-reachable, dark text on light background. The whole interface is a conversation with the AI — no Analyze/Suggest buttons; the backend's request-shape branching (PLAN.md §3.1) decides the turn type:

1. **Chat area** fills the screen; user bubbles show photo thumbnails or a 🎤 marker; assistant bubbles carry the reply with a "steps" expander showing numbered cooking steps.
2. **Ingredient chips row** sits above the composer once items exist: removable chips with ✕, plus an "+ add item" chip. The list re-syncs from every response. The row carries a collapse/expand arrow — collapsed it shrinks to a slim bar so a long list can never flood the screen.
3. **Composer pinned to the bottom**: small icon buttons — 📷 camera, 🖼 upload, 🎤 hold-to-record (`MediaRecorder`) — then the context textarea ("kya mood hai? guests? time pressure? — optional; or statement mode: 'tamatar nahi hai' to edit ingredients via chat") and a Send button. Selected photos/audio attach to the next send; everything goes to the same `POST /api/chat` (text + current ingredients + full `messages` history, kept in JS state; re-enable the input after each reply).

Style notes: **responsive and mobile-first** — this app is used on phones. Requirements: `<meta name="viewport" content="width=device-width, initial-scale=1">`, fluid grid/flex layouts, rem/% sizing, no horizontal scrolling at 360 px width, one-thumb-sized touch targets. Development testing happens in the browser's mobile responsive mode (DevTools device presets, ~360–430 px wide) — verify every screen in that mode before moving on. System font stack, CSS grid/flex only, no framework, no icon library (emoji are fine). Keep `app.js` as plain fetch calls + DOM updates — state can be a single JS object; no framework needed. Everything the friend sends goes to the same `POST /api/chat`; the backend branches on the request shape.

---

## 5. Phase 3 — End-to-end polish & test

Do these before declaring done:

- [ ] Cold start test: laptop reboot → run model server → run backend → phone on same Wi-Fi loads `http://<laptop-ip>:8000` and completes the full flow.
- [ ] Real photo test: use actual fridge/cupboard photos (messy, half-empty) — not stock images. Screenshot the flow: input photo → ingredient chips → meal suggestion. These screenshots go in the DEV post.
- [ ] Hallucination check: confirm the editable chips let you remove a false detection, and that both edit paths respect the result — a conversational turn after a manual ✕ doesn't resurrect the removed item, and a conversational correction ("tamatar nahi hai") removes it from the chips too.
- [ ] End-to-end list check: remove an item via ✕, ask for suggestions, confirm the reply's ingredient list reflects it; add one conversationally (typed and spoken), confirm again.
- [ ] Language check: replies stay Roman Urdu, don't drift to English after 4–5 turns; if drift occurs, raise the language-rule position or repeat it as a trailing system instruction.
- [ ] Latency: analysis should feel responsive (< ~20 s); if much slower, check image downscaling is applied.
- [ ] `README.md` with: what it is, run instructions (model server + backend commands), config explanation, and a note that all AI runs locally.

---

## 6. Phase 4 (OPTIONAL) — Local TTS, only if Phases 1–3 are complete

Only build this if explicitly requested after everything above works.

- `GET /api/tts?text=...&lang=en|ur` → returns `audio/wav`.
- English: Kokoro (82M) via the `kokoro` pip package. Urdu: Meta MMS-TTS variant `facebook/mms-tts-urd-script_latin` (Roman Urdu input) via `transformers`.
- Before synthesizing: strip emojis, markdown asterisks, bullets, and convert numbers like "10" to words.
- Take the output sample rate from the model's response per engine (Kokoro 24 kHz, MMS 16 kHz) — do not hardcode one rate.
- Frontend: "🔊 listen" button on each reply bubble; kitchen mode toggle that auto-plays replies and increases font size.
- If MMS Roman Urdu pronunciation is too poor to ship, keep Kokoro English only and note it — do not sink time into fixing TTS.

---

## 7. Explicitly out of scope (do not build)

- Microphone input is in scope (native audio); an STT/transcription layer of any kind is not — audio goes straight to the model
- HTTPS, service workers, PWA installability, cloudflared tunnels
- Cloud deployment, Docker, GPU rental
- User accounts, auth, database, profile endpoints, any user data fetching/persistence
- Streaming responses, vector stores, RAG, fine-tuning
- Any frontend framework, bundler, or package manager

---

## 8. Acceptance criteria

1. Mobile viewport (phone browser, or DevTools responsive mode at ~390×844): take fridge photo → see editable ingredient chips → fix list → get 2–3 Roman Urdu meal suggestions, both chip-edit paths work (manual ✕/+ add and conversational "tamatar nahi hai", typed or spoken), end to end under ~30 seconds of AI time, with no horizontal scroll or layout breakage down to 360 px.
2. Every byte of AI processing happens on the laptop (llama-server); zero external network calls at runtime.
3. One command starts the model, one command starts the app; the README proves a stranger could run it.
4. All config lives in `config.py` (backend) and `config.js` (frontend); swapping `MODEL_BASE_URL` in `config.py` changes nothing else.
5. Screenshots exist for: input photo, ingredient chips (with one human fix), and a meal suggestion in Roman Urdu.

---

## 9. Appendix — End-to-end flow of a single conversation

The sequence below is the reference lifecycle of one full session. Every phase in this plan maps to a segment of it; nothing outside this diagram should exist in the app.

```mermaid
sequenceDiagram
    autonumber
    participant F as Friend (phone)
    participant U as Frontend (app.js)
    participant B as Backend (FastAPI :8000)
    participant L as Gemma 4 E4B (llama serve :8080)

    Note over F,U: Session start
    F->>U: opens http://laptop-ip:8000 (page renders; no fetches — the app holds no user data)

    Note over F,L: Pass 1 - vision: photo to ingredients
    F->>U: snaps up to 15 fridge photos (or skips photos and just types/speaks)
    U->>B: POST /api/chat (vision turn: multipart images)
    B->>B: downscale to 1280px, base64
    B->>L: chat completion (vision system prompt + images + JSON grammar)
    L-->>B: ingredients array (item, count, location, confidence)
    B-->>U: parsed ingredients
    U->>F: editable ingredient chips
    Note over F,U: HUMAN CONFIRM: remove hallucinated item, add missed one

    Note over F,L: Pass 2 - conversation: ingredients to meals
    F->>U: types or speaks context (guests aa rahe, kuch quick banao)
    U->>B: POST /api/chat (conversation turn: edited ingredients + text/audio + messages)
    B->>B: build system prompt (Roman Urdu rules)
    B->>L: chat completion (server sampling defaults, max_tokens 700, reply+ingredients JSON schema)
    L-->>B: reply + updated ingredient list
    B-->>U: both
    U->>F: chat bubble with steps expander; chips re-synced (edited list feeds next turn)

    Note over F,L: Follow-up loop (same conversation)
    F->>U: follow-up, typed or spoken (steps chahiye / garlic skip kar sakte hain)
    U->>B: POST /api/chat (conversation turn: full message history)
    B->>L: system prompt + conversation history
    L-->>B: numbered steps in Roman Urdu
    B-->>U: reply
    U->>F: chat bubble

    opt Phase 4 (optional) - local TTS
        U->>B: GET /api/tts (reply text, lang=ur)
        B->>B: sanitize (emoji, markdown, numbers)
        B-->>U: audio/wav (MMS urd-script_latin, 16 kHz)
        U->>F: listen button / auto-play
    end

    Note over F,L: All AI runs on the laptop - zero external network calls
```

Notes for the implementer:

- The backend is stateless: conversation history lives in the frontend's `messages` array and is re-sent with every `/api/chat` call. No session storage server-side.
- The "HUMAN CONFIRM" step is not optional polish — the edited chip list, not the raw model output, is what feeds the meal-suggestion pass.
- The optional TTS block is Phase 4; do not implement it unless explicitly instructed after Phases 1–3 pass acceptance.