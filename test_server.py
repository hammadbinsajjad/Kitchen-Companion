"""Minimal self-check for the backend: .venv/bin/python test_server.py (or pytest)."""
import base64
import json
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

import server

tc = TestClient(server.app)


def make_jpeg(w=2000, h=1000):
    img = Image.new("RGB", (w, h), (120, 30, 30))
    buf = BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


class FakeCompletion:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


def fake_model(**kwargs):
    """Stands in for client().chat.completions.create — captures kwargs, returns fixed JSON."""
    fake_model.captured = kwargs
    return FakeCompletion(json.dumps({
        "reply": "Biryani try karo!",
        "ingredients": [
            {"item": "eggs", "count": "3", "location": "shelf", "confidence": "high"},
            {"garbage": True},
        ],
        "dishes": [{"name": "Aloo Pulao", "note": "ek pot, 30 minute"}],
    }))


def use_fake_model(fn=fake_model):
    """Monkeypatch the OpenAI client for the duration of a test."""
    comp = type("Comp", (), {"create": staticmethod(fn)})()
    stub = type("Stub", (), {})()
    stub.chat = type("Chat", (), {"completions": comp})()
    server._client = stub


def test_parse_fallbacks():
    assert server.parse_model_json('{"reply":"hi","ingredients":[]}')["reply"] == "hi"
    assert server.parse_model_json('```json\n{"reply":"hi","ingredients":[]}\n```')["reply"] == "hi"
    # salvage: JSON embedded in chatter
    assert server.parse_model_json('sure! {"reply":"hi","ingredients":[]} done')["reply"] == "hi"
    # malformed entries dropped, valid kept
    out = server.parse_model_json('{"reply":"","ingredients":[{"item":"eggs"},{"bad":1}]}')
    assert out["ingredients"] == [{"item": "eggs", "count": "", "location": "", "confidence": ""}]


def test_vision_turn():
    use_fake_model()
    r = tc.post("/api/chat", files=[("images", ("a.jpg", make_jpeg(), "image/jpeg"))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "Biryani try karo!"
    assert body["ingredients"][0]["item"] == "eggs"
    assert body["dishes"][0]["name"] == "Aloo Pulao"
    kwargs = fake_model.captured
    msgs = kwargs["messages"]
    assert msgs[0]["role"] == "system"
    assert "vision assistant" in msgs[0]["content"]
    user = msgs[-1]["content"]
    assert user[0]["type"] == "image_url"          # images first
    assert user[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert kwargs["response_format"]["json_schema"]["name"] == "chat_response"


def test_vision_turn_downscale_and_combined_note():
    use_fake_model()
    r = tc.post("/api/chat", files=[("images", ("a.jpg", make_jpeg(), "image/jpeg"))],
                data={"context": "ye nayi cheezein hain"})
    assert r.status_code == 200
    user = fake_model.captured["messages"][-1]["content"]
    assert user[0]["type"] == "image_url"
    assert user[-1] == {"type": "text", "text": "ye nayi cheezein hain"}  # text last
    assert "acknowledging" in fake_model.captured["messages"][0]["content"]  # combined note
    # downscale: image data in URL must decode to a 1280-px-long-edge JPEG
    b64 = user[0]["image_url"]["url"].split(",", 1)[1]
    img = Image.open(BytesIO(base64.b64decode(b64)))
    assert max(img.size) == 1280


def test_conversation_turn():
    use_fake_model()
    r = tc.post("/api/chat", data={
        "ingredients": json.dumps(["eggs", "tomatoes (2)"]),
        "context": "kuch quick banao",
        "messages": json.dumps([{"role": "assistant", "content": "Biryani try karo!"}]),
    })
    assert r.status_code == 200
    msgs = fake_model.captured["messages"]
    assert "kitchen companion" in msgs[0]["content"]
    assert msgs[1]["content"] == "Biryani try karo!"
    assert msgs[2]["content"][0]["type"] == "text"
    assert "I have: eggs, tomatoes (2)" in msgs[2]["content"][0]["text"]
    assert "kuch quick banao" in msgs[2]["content"][0]["text"]
    assert not any(p["type"] in ("image_url", "input_audio") for p in msgs[2]["content"])


def test_audio_part_order():
    use_fake_model()
    wav = make_jpeg()[:100]  # bytes content doesn't matter, only ordering
    r = tc.post("/api/chat", files=[("images", ("a.jpg", make_jpeg(100, 100), "image/jpeg")),
                                    ("audio", ("a.wav", wav, "audio/wav"))],
                data={"context": "aur ye bhi hai"})
    assert r.status_code == 200, r.text
    parts = fake_model.captured["messages"][-1]["content"]
    assert [p["type"] for p in parts] == ["image_url", "input_audio", "text"]
    assert parts[1]["input_audio"]["format"] == "wav"


def test_validation():
    r = tc.post("/api/chat", data={})  # empty turn
    assert r.status_code == 400
    r = tc.post("/api/chat", data={"context": "x", "ingredients": "not json"})
    assert r.status_code == 400
    r = tc.post("/api/chat", files=[("images", ("a.png", b"not an image", "image/png"))])
    assert r.status_code == 400


def test_polluted_output_cleaned():
    # Model residue: control tokens + brace-laden junk items (seen in the wild)
    def polluted(**kwargs):
        return FakeCompletion(json.dumps({
            "reply": "Aloo {}, 2, 0}, 0, 0}<|channel|>Aap do cheezein bana sakte hain<|message|>",
            "ingredients": [
                {"item": "Aloo {}, 2, 0}, 2, 0}, 0, 0}"},
                {"item": "Aloo"},
                {"item": "Tamatar"},
            ],
        }))
    use_fake_model(polluted)
    r = tc.post("/api/chat", data={"context": "kuch quick banao"})
    assert r.status_code == 200
    body = r.json()
    assert "<|" not in body["reply"] and "{}" not in body["reply"]
    assert [i["item"] for i in body["ingredients"]] == ["Aloo", "Tamatar"]


def test_truncated_json_salvaged():
    # exactly the failure seen in the wild: max_tokens cut the JSON mid-reply
    truncated = ('{\n "ingredients": [{"item": "Aloo"}, {"item": "Tamater"}],\n '
                 '"dishes": [{"name": "Beef Aloo curry", "note": ""}],\n '
                 '"reply": "Bahut hi behtareen ingredients hain! Aap Beef aur Aloo se ek '
                 'mazedar curry bana sakte hain, jo aapke pre-cooked chawal ke saath"')
    def truncated_model(**kwargs):
        return FakeCompletion(truncated)
    use_fake_model(truncated_model)
    r = tc.post("/api/chat", data={"context": "mere pas aloo beef chawal hain",
                                   "ingredients": json.dumps(["Aloo", "Beef", "Chawal"])})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "mazedar curry" in body["reply"]
    # truncated turn echoes the current list instead of wiping it
    assert [i["item"] for i in body["ingredients"]] == ["Aloo", "Beef", "Chawal"]
    assert body["dishes"] == []


def test_vision_merge_with_existing_list():
    use_fake_model()
    r = tc.post("/api/chat", files=[("images", ("a.jpg", make_jpeg(), "image/jpeg"))],
                data={"context": "ye nayi cheezein hain",
                      "ingredients": json.dumps(["Aloo", "Chawal (2)"])})
    assert r.status_code == 200
    msgs = fake_model.captured["messages"]
    assert "UNION" in msgs[0]["content"]                 # merge instruction present
    user = msgs[-1]["content"]
    assert user[0]["type"] == "image_url"
    text = user[-1]["text"]
    assert text.startswith("I have: Aloo, Chawal (2)")   # current list rides along
    assert "ye nayi cheezein hain" in text


def test_dedupe_ingredients():
    out = server.dedupe_ingredients([
        {"item": "Rice (2)"}, {"item": "rice"}, {"item": "Chawal"}, {"item": "Aloo"},
    ])
    assert [i["item"] for i in out] == ["Rice (2)", "Chawal", "Aloo"]  # rice==Rice deduped, chawal kept


def test_audio_note_on_spoken_turns():
    use_fake_model()
    r = tc.post("/api/chat", files=[("audio", ("a.wav", b"RIFF....", "audio/wav"))])
    assert r.status_code == 200
    assert "spoken audio clip" in fake_model.captured["messages"][0]["content"]


def test_audio_saved_for_debug(tmp_path=None):
    use_fake_model()
    server.config.AUDIO_DEBUG_DIR = "temp/recordings"
    r = tc.post("/api/chat", files=[("audio", ("a.wav", b"RIFF-debug-bytes", "audio/wav"))])
    assert r.status_code == 200
    import os
    saved = os.listdir(server.config.AUDIO_DEBUG_DIR)
    assert saved, "no clip saved"
    assert open(os.path.join(server.config.AUDIO_DEBUG_DIR, saved[-1]), "rb").read() == b"RIFF-debug-bytes"


def test_model_down():
    from openai import APIConnectionError
    def down(**kwargs):
        raise APIConnectionError(message="down", request=type("R", (), {})())
    use_fake_model(down)
    r = tc.post("/api/chat", data={"context": "hello"})
    assert r.status_code == 502


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("all checks passed")
