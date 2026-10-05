*This is a submission for the [Hacktoberfest Weekend Challenge: Build for a Friend](https://dev.to/challenges/hacktoberfest-weekend-2026-10-01)*

## What I Built

**Kitchen Companion** — a kitchen assistant for my mother, who kept asking me the same question over WhatsApp: *"Mere paas aloo, tamatar aur thora chawal bacha hai — kya banaun?"*

Her fridge is a moving target: leftovers, half-used things, whatever she bought that week. So I built her an app where she photographs her fridge, **fixes the detected ingredient list on screen** (the vision model sometimes "sees" things that aren't there — she removes those with one tap), and then chats with a warm kitchen companion that suggests meals in **Roman Urdu** — Urdu written in Latin letters, the way Pakistanis actually text. She can follow up by typing *or speaking* ("steps chahiye", "tamatar nahi hai", "guests aa rahe hain"), and the ingredient list and suggestions stay in sync as the conversation evolves.

It solves the actual problem: "what can I cook with THIS, right now" — not a generic recipe search engine.

## Demo

Video Recording: https://drive.google.com/file/d/1CaxfYjIUAkL_-7jGiiiQ0QuF2bavQP8z/view?usp=drive_link


## Code

{% github hammadbinsajjad/Kitchen-Companion %}

Zero build tooling: plain HTML/JS frontend served by a small FastAPI backend that talks to llama.cpp. One command starts the model, one starts the app.

## How I Built It

- **Model**: Gemma 4 E4B (QAT GGUF) running via **llama.cpp's `llama serve`** on my laptop — chosen because it's natively **multimodal**: the same model handles vision (fridge photos) *and* audio (spoken follow-ups). No speech-to-text layer anywhere — her voice goes straight into the model as `input_audio`, and the browser records/re-encodes it to WAV with vanilla JS.
- **One endpoint**: the whole app is a single `POST /api/chat`. The request shape decides the turn — images attached = vision turn, text/audio = conversation turn, both = a vision turn that also acknowledges the note. No intent classifier, no agent framework — routing that can be read off the request metadata should never be inferred.
- **Structured output**: every response is schema-constrained JSON `{reply, dishes, ingredients}`. Dish suggestions are separate objects rendered as tappable cards (tap = "steps chahiye"), and the ingredient list rides along in every turn so conversational corrections ("chawal nahi hai") update the chips. Plus defensive parsing for the real world: brace-residue stripping, truncation salvage, case-insensitive dedupe.
- **Human-in-the-loop by design**: the edited chip list — not the raw model output — feeds the suggestion pass. The model proposes; my mother disposes.
- **Stateless backend**: conversation history lives in the frontend and is re-sent every turn. Config lives in exactly two files (`config.py` / `config.js`).
- Tested mobile-first in DevTools responsive mode for Pixel 8/9 (412 x 915); my mother's phone is the real target.

## Why Does Open Innovation Matter?

Because the model is open and runs locally, every photo she takes — her kitchen, her cupboards, the inside of her fridge — **never leaves her home network**. No cloud, no uploads, no server somewhere holding her family's life in a data center. What's in her fridge is nobody's business but her own, and open weights are the only way that's possible.

And it just keeps working. No internet? No problem — the laptop on her Wi-Fi is the entire system. The app doesn't care if the connection drops, if a service is down for maintenance, or if a provider changes its pricing overnight. For a tool that lives in the busiest room of a house and gets used daily by my mother, that reliability isn't a nice-to-have; it's the whole point.

A closed API would have meant mailing her kitchen photos to someone else's server on every single use — and a companion that dies the moment the connection does. Open innovation made this *private* and *hers* — which was the entire point of building for a friend.

## Prize Categories

- Best Use of Gemma
