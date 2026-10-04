"""Kitchen Companion backend — static files + one AI endpoint (POST /api/chat)."""
import base64
import json
import re
from io import BytesIO

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from openai import APIError, OpenAI
from PIL import Image, ImageOps

import config
import prompts

app = FastAPI(title="Kitchen Companion")

_client: OpenAI | None = None


def client() -> OpenAI:
    """llama-server's OpenAI-compatible endpoint; model name is ignored by the server."""
    global _client
    if _client is None:
        _client = OpenAI(base_url=config.MODEL_BASE_URL, api_key="not-needed", timeout=180)
    return _client

# JSON grammar shared by both turns (PLAN.md §3.1)
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        # ingredients/dishes first: if max_tokens truncates the JSON mid-reply,
        # the structured data survives and only the reply needs salvaging
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "count": {"type": "string"},
                    "location": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["item"],
            },
        },
        "dishes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "reply": {"type": "string"},
    },
    "required": ["ingredients", "dishes", "reply"],
}


def downscale_image(data: bytes) -> str:
    """Return a base64 JPEG data URL, downscaled to MAX_IMAGE_EDGE on the long edge."""
    img = Image.open(BytesIO(data))
    img = ImageOps.exif_transpose(img)
    w, h = img.size
    if max(w, h) > config.MAX_IMAGE_EDGE:
        scale = config.MAX_IMAGE_EDGE / max(w, h)
        img = img.resize((round(w * scale), round(h * scale)))
    buf = BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def build_user_content(images: list[bytes], audio: bytes | None, text: str) -> list[dict]:
    # Content part order pinned by plan: images, then audio, then text (if any)
    parts = [{"type": "image_url", "image_url": {"url": downscale_image(d)}} for d in images]
    if audio:
        parts.append({
            "type": "input_audio",
            "input_audio": {"data": base64.b64encode(audio).decode(), "format": "wav"},
        })
    if text:
        parts.append({"type": "text", "text": text})
    return parts


def call_model(messages: list[dict], current_ingredients: list | None = None) -> dict:
    kwargs = {
        "model": "gemma",  # llama-server serves one model; name is ignored
        "messages": messages,
        "max_tokens": config.MAX_TOKENS,
        "response_format": {"type": "json_schema", "json_schema": {"name": "chat_response", "strict": True, "schema": RESPONSE_SCHEMA}},
    }
    if config.TEMPERATURE_OVERRIDE is not None:
        kwargs["temperature"] = config.TEMPERATURE_OVERRIDE
    try:
        completion = client().chat.completions.create(**kwargs)
        content = completion.choices[0].message.content
    except APIError as e:
        raise HTTPException(502, f"model server error: {e}") from e
    except (AttributeError, IndexError) as e:
        raise HTTPException(502, "unexpected model response shape") from e
    if not content:
        raise HTTPException(502, "model returned empty content")
    return parse_model_json(content, current_ingredients)


def salvage_truncated(text: str, current_ingredients: list) -> dict:
    """max_tokens cut the JSON mid-write. The schema puts ingredients/dishes first,
    so they are usually complete; salvage the (possibly half-written) reply and echo
    the current list instead of failing the turn."""
    m = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)', text)
    if not m:
        raise HTTPException(502, f"model did not return JSON: {text[:300]}")
    reply = clean_text(re.sub(r'\\(["\\/bfnrt])',
                              lambda x: {'"': '"', "\\": "\\", "/": "/", "n": "\n",
                                         "t": "\t", "b": "\b", "f": "\f"}[x.group(1)],
                              m.group(1)))
    return {"reply": reply, "ingredients": current_ingredients, "dishes": []}


def clean_text(s: str) -> str:
    """Strip chat-template control tokens (<|channel|> etc.) and stray JSON residue."""
    s = re.sub(r"<\|[^|>]*\|>", "", s).strip()
    if "{" in s or "}" in s:
        # Brace junk means the grammar didn't constrain this reply; keep the longest
        # brace-free stretch (the actual prose) and drop the JSON fragments.
        s = max(re.split(r"[{}]", s), key=len).strip()
    return s.strip()


def parse_model_json(content: str, current_ingredients: list | None = None) -> dict:
    """Parse the model's JSON reply. Grammar makes this a formality; fall back to
    fence-stripping and slicing in case grammar wiring is off (PLAN.md §3.3)."""
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise HTTPException(502, f"model did not return JSON: {text[:300]}")
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return salvage_truncated(text, current_ingredients or [])
    reply = clean_text(data.get("reply") or "")
    ingredients = []
    for entry in data.get("ingredients") or []:
        if isinstance(entry, dict) and isinstance(entry.get("item"), str) and entry["item"].strip():
            item = re.sub(r"<\|[^|>]*\|>", "", entry["item"]).strip()
            # Model residue (unconstrained output) shows up as brace/quote-laden junk strings
            if not item or any(c in item for c in "{}\"\\") or len(item) > 60 or "\n" in item:
                continue
            ingredients.append({
                "item": item,
                "count": clean_text(entry.get("count") or ""),
                "location": clean_text(entry.get("location") or ""),
                "confidence": entry.get("confidence") or "",
            })
    dishes = []
    for entry in data.get("dishes") or []:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"].strip():
            name = clean_text(entry["name"])
            if name and len(name) <= 80 and not any(c in name for c in "{}\"\\"):
                dishes.append({"name": name, "note": clean_text(entry.get("note") or "")})
    return {"reply": reply, "ingredients": ingredients, "dishes": dishes}


def dedupe_ingredients(ing: list[dict]) -> list[dict]:
    """Case-insensitive dedupe on the base name ("Rice (2)" vs "rice" collide)."""
    seen, out = set(), []
    for e in ing:
        base = e["item"].split(" (")[0].strip().lower()
        if base in seen:
            continue
        seen.add(base)
        out.append(e)
    return out


@app.post("/api/chat")
async def chat(
    images: list[UploadFile] = File(default=[]),
    audio: UploadFile = File(default=None),
    context: str = Form(""),
    ingredients: str = Form("[]"),
    messages: str = Form("[]"),
):
    # Validate ingredients/messages payloads at the trust boundary
    try:
        ing = [{"item": str(i)} for i in json.loads(ingredients)]  # normalize: always dict-shaped
        history = [
            {"role": m["role"], "content": str(m["content"])}
            for m in json.loads(messages)
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
    except (json.JSONDecodeError, TypeError, AttributeError, KeyError):
        raise HTTPException(400, "ingredients/messages must be valid JSON")

    imgs: list[bytes] = []
    for f in images or []:
        if len(imgs) >= config.MAX_IMAGES:
            raise HTTPException(400, f"max {config.MAX_IMAGES} images")
        data = await f.read()
        if len(data) > config.MAX_IMAGE_BYTES:
            raise HTTPException(413, f"image {f.filename} exceeds ~5 MB")
        try:
            Image.open(BytesIO(data)).verify()
        except Exception:
            raise HTTPException(400, f"{f.filename} is not a valid image")
        imgs.append(data)

    audio_data = None
    if audio is not None and audio.filename:
        audio_data = await audio.read()
        if len(audio_data) > config.MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio clip too large (cap ~60 s)")
        if config.AUDIO_DEBUG_DIR:
            import time, os
            os.makedirs(config.AUDIO_DEBUG_DIR, exist_ok=True)
            path = os.path.join(config.AUDIO_DEBUG_DIR, f"{time.strftime('%H%M%S')}.wav")
            with open(path, "wb") as f:
                f.write(audio_data)

    has_extras = bool(context.strip() or audio_data)
    if imgs:
        note = prompts.MERGE_NOTE if ing else (prompts.COMBINED_NOTE if has_extras else "")
        system = prompts.VISION_SYSTEM_PROMPT + note
        user_text = context.strip() or prompts.VISION_USER_MESSAGE
        if ing:
            # Mid-conversation photos must merge with what we already track, not replace it
            user_text = f"I have: {', '.join(i['item'] for i in ing)}\n" + user_text
    else:
        if not context.strip() and not audio_data:
            raise HTTPException(400, "empty turn: send images, text or audio")
        system = prompts.COMPANION_SYSTEM_PROMPT + (prompts.AUDIO_NOTE if audio_data else "")
        # Current list rides along in every turn so corrections work (PLAN.md §3.2)
        user_text = "I have: " + ", ".join(i["item"] for i in ing) if ing else ""
        if context.strip():
            user_text = (user_text + "\n" if user_text else "") + context.strip()

    msgs = [{"role": "system", "content": system}, *history,
            {"role": "user", "content": build_user_content(imgs, audio_data, user_text)}]
    result = call_model(msgs, ing)
    result["ingredients"] = dedupe_ingredients(result["ingredients"])
    return result


app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    # config.py owns the bind address — no CLI flags to forget (PLAN.md §9, "one command")
    import uvicorn
    uvicorn.run(app, host=config.APP_HOST, port=config.APP_PORT)
