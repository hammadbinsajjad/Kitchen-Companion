// Kitchen Companion frontend — chat-first, plain fetch + DOM updates, single state object.
"use strict";

const state = { ingredients: [], messages: [], audio: null, pendingImages: [], chipsOpen: true };

const $ = (id) => document.getElementById(id);
const toast = (msg) => {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  setTimeout(() => { t.hidden = true; }, 4000);
};

async function apiChat(form) {
  const res = await fetch(`${CONFIG.API_BASE}/api/chat`, { method: "POST", body: form });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

/* ---------- attachments (camera / gallery / mic) ---------- */

$("camera-btn").onclick = () => $("camera-input").click();
$("gallery-btn").onclick = () => $("gallery-input").click();

for (const id of ["camera-input", "gallery-input"]) {
  $(id).onchange = () => {
    state.pendingImages.push(...[...$(id).files].slice(0, Math.max(0, CONFIG.MAX_IMAGES - state.pendingImages.length)));
    $(id).value = "";
    renderAttachments();
  };
}

function renderAttachments() {
  const box = $("attachments");
  const kids = state.pendingImages.map((f, i) => {
    const wrap = document.createElement("span");
    const img = document.createElement("img");
    img.src = URL.createObjectURL(f);
    const x = document.createElement("button");
    x.className = "x"; x.textContent = "✕";
    x.onclick = () => { state.pendingImages.splice(i, 1); renderAttachments(); };
    wrap.append(img, x);
    return wrap;
  });
  if (state.audio) {
    const clip = document.createElement("span");
    clip.className = "clip";
    clip.textContent = "🎤 clip";
    const x = document.createElement("button");
    x.className = "x"; x.textContent = "✕";
    x.onclick = () => { state.audio = null; renderAttachments(); };
    clip.append(x);
    kids.push(clip);
  }
  box.replaceChildren(...kids);
  box.hidden = !kids.length;
}

/* ---------- ingredient chips ---------- */

function renderChips() {
  const bar = $("chips-bar");
  bar.hidden = !state.ingredients.length;
  const chips = $("chips");
  chips.classList.toggle("collapsed", !state.chipsOpen);
  $("chips-toggle").classList.toggle("open", state.chipsOpen);
  $("chips-hint").hidden = state.chipsOpen;
  chips.replaceChildren(...state.ingredients.map((item, i) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.append(item);
    const x = document.createElement("button");
    x.className = "x";
    x.textContent = "✕";
    x.setAttribute("aria-label", `Remove ${item}`);
    x.onclick = () => { state.ingredients.splice(i, 1); renderChips(); };
    chip.append(x);
    return chip;
  }));
  if (state.ingredients.length) {
    const add = document.createElement("span");
    add.className = "chip";
    add.innerHTML = `<span class="add-form"><input id="add-input" placeholder="+ add item"><button class="x" id="add-btn">+</button></span>`;
    add.querySelector("#add-btn").onclick = () => {
      const val = add.querySelector("#add-input").value.trim();
      if (val) { state.ingredients.push(val); renderChips(); }
    };
    add.querySelector("#add-input").onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); add.querySelector("#add-btn").click(); }
    };
    chips.append(add);
  }
}

$("chips-toggle").onclick = () => {
  state.chipsOpen = !state.chipsOpen;
  renderChips();
};

/* ---------- chat ---------- */

function addBubble(role, text, images = [], dishes = []) {
  $("empty")?.remove();
  const div = document.createElement("div");
  div.className = `bubble ${role}`;
  if (images.length) {
    const thumbs = document.createElement("div");
    thumbs.className = "thumbs";
    thumbs.replaceChildren(...images.map((f) => {
      const img = document.createElement("img");
      img.src = URL.createObjectURL(f);
      return img;
    }));
    div.append(thumbs);
  }
  if (text) {
    const { main, steps } = splitSteps(text);
    div.append(main);
    if (steps.length) {
      const details = document.createElement("details");
      details.innerHTML = `<summary>👨‍🍳 steps</summary><ol>${steps.map(s => `<li>${s}</li>`).join("")}</ol>`;
      div.append(details);
    }
  }
  if (dishes.length) {
    const list = document.createElement("div");
    list.className = "dishes";
    for (const d of dishes) {
      const card = document.createElement("button");
      card.className = "dish-card";
      card.innerHTML = `<strong>${d.name}</strong>${d.note ? `<span>${d.note}</span>` : ""}`;
      card.onclick = () => { $("context").value = `${d.name} ke steps chahiye`; send(); };
      list.append(card);
    }
    div.append(list);
  }
  $("chat").append(div);
  $("chat").scrollTop = $("chat").scrollHeight;
  return div;
}

// Move a trailing numbered/bulleted block out of the reply text into the steps expander.
function splitSteps(text) {
  const lines = text.split("\n");
  let i = lines.length;
  while (i > 0 && /^(?:\d+[.)]\s|\s*[-•]\s)/.test(lines[i - 1])) i--;
  const stepLines = lines.slice(i).map((l) => l.replace(/^\s*\d+[.)]\s|\s*[-•]\s/, "").trim());
  return { main: document.createTextNode(lines.slice(0, i).join("\n").trim()), steps: stepLines };
}

$("send-btn").onclick = send;
$("context").addEventListener("input", () => {
  const t = $("context");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 112) + "px";
});
$("context").onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
};

async function send() {
  const context = $("context").value.trim();
  if (!context && !state.audio && !state.pendingImages.length) return;
  $("send-btn").disabled = true;
  const form = new FormData();
  state.pendingImages.forEach((f) => form.append("images", f));
  form.append("ingredients", JSON.stringify(state.ingredients));
  form.append("context", context);
  form.append("messages", JSON.stringify(state.messages));
  if (state.audio) form.append("audio", state.audio, "audio.wav");
  const sentImages = state.pendingImages;

  addBubble("user", context || (state.audio ? "🎤" : ""), sentImages);
  try {
    const data = await apiChat(form);
    state.messages.push(
      { role: "user", content: context || (sentImages.length ? "[photos]" : "[audio message]") },
      { role: "assistant", content: data.reply });
    if (data.reply || data.dishes.length) addBubble("assistant", data.reply, [], data.dishes);
    else if (sentImages.length && data.ingredients.length)
      addBubble("system", `🧺 ${data.ingredients.length} cheezein detect hui — neeche fix kar lo`);
    // Model's list is authoritative each turn (PLAN.md §3.1)
    state.ingredients = data.ingredients.map((i) =>
      i.count ? `${i.item} (${i.count})` : i.item);
    renderChips();
  } catch (e) {
    toast("😅 kuch masla aa gaya — dobara try karein" +
      (String(e.message).includes("502") ? " (model server chal raha hai?)" : ""));
  }
  state.audio = null;
  state.pendingImages = [];
  $("context").value = "";
  renderAttachments();
  $("send-btn").disabled = false;
}

/* ---------- hold-to-record mic (native audio, no STT) ---------- */

const recorder = { media: null, chunks: [], timer: null };

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    const hint = /firefox/i.test(navigator.userAgent)
      ? "Firefox: about:config → media.devices.insecure.enabled + media.getusermedia.insecure.enabled = true"
      : "Chrome: chrome://flags → 'unsafely-treat-insecure-origin-as-secure' mein is URL add karo";
    toast(`mic sirf HTTPS/localhost pe chalta hai — ${hint}`);
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
      ? "audio/webm;codecs=opus" : "";
    recorder.media = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    recorder.chunks = [];
    recorder.media.ondataavailable = (e) => recorder.chunks.push(e.data);
    recorder.media.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      clearTimeout(recorder.timer);
      $("mic-btn").classList.remove("recording");
      const raw = new Blob(recorder.chunks, { type: recorder.media.mimeType || "audio/webm" });
      try {
        state.audio = await toWav(raw);
        renderAttachments();
        toast("🎤 clip attached — ab Send dabao");
      } catch { toast("😅 clip sahi se record nahi hui — dobara koshish karein"); }
    };
    recorder.media.start();
    $("mic-btn").classList.add("recording");
    recorder.timer = setTimeout(stopRecording, CONFIG.MAX_RECORD_SECONDS * 1000);
  } catch { toast("🎤 mic permission nahi mili — browser ki settings se allow karein"); }
}

function stopRecording() {
  if (recorder.media && recorder.media.state === "recording") recorder.media.stop();
}

$("mic-btn").onclick = () =>
  (recorder.media && recorder.media.state === "recording") ? stopRecording() : startRecording();

// Decode recorded blob and re-encode as 16 kHz mono WAV (llama.cpp input_audio needs wav).
async function toWav(blob) {
  const ctx = new AudioContext({ sampleRate: 16000 });
  const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
  const n = buf.length;
  const mono = new Float32Array(n);
  for (let c = 0; c < buf.numberOfChannels; c++) {
    const ch = buf.getChannelData(c);
    for (let i = 0; i < n; i++) mono[i] += ch[i] / buf.numberOfChannels;
  }
  const pcm = new Int16Array(n);
  for (let i = 0; i < n; i++) pcm[i] = Math.max(-32768, Math.min(32767, mono[i] * 32767));
  const out = new ArrayBuffer(44 + n * 2);
  const v = new DataView(out);
  const ws = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  ws(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); ws(8, "WAVEfmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, buf.sampleRate, true); v.setUint32(28, buf.sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  ws(36, "data"); v.setUint32(40, n * 2, true);
  new Int16Array(out, 44).set(pcm);
  ctx.close();
  return new Blob([out], { type: "audio/wav" });
}
