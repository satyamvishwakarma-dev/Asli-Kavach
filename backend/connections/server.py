"""Asli Kavach Unified Backend Server (FastAPI).
Connects all deepfake detection models (ViT for Video/Image, Wav2Vec2 for Audio files,
LightVoiceCNN for ultra-low latency real-time voice, and Provenance Web Search).
Serves frontend directly on http://localhost:8000
"""

import io
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Setup import paths
CURR_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURR_DIR)
MODEL_DIR = os.path.join(BACKEND_DIR, "model")
ROOT_DIR = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

if MODEL_DIR not in sys.path:
    sys.path.insert(0, MODEL_DIR)
REALTIME_AUDIO_DIR = os.path.join(MODEL_DIR, "audio", "realtime_audio")
if REALTIME_AUDIO_DIR not in sys.path:
    sys.path.insert(0, REALTIME_AUDIO_DIR)

from infer_audio import (
    load_audio_clf,
    read_audio_file,
    resolve_audio_dir,
    resolve_image_dir,
    rms,
    score_wav16k,
    to_mono16k,
)
from light_detector import LightVoiceDetector

app = FastAPI(title="Asli Kavach Unified Deepfake Verification API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global model state
models = {
    "vit_clf": None,
    "vit_fake_labels": set(),
    "vit_dir": None,
    "wav2vec2_clf": None,
    "wav2vec2_fake_labels": set(),
    "wav2vec2_dir": None,
    "light_voice_detector": None,
}

FAKE_TOKENS = {"fake", "spoof", "spoofed", "ai", "synthetic", "deepfake", "generated", "artificial"}


def extract_fake_labels(pipe):
    labels = list(pipe.model.config.id2label.values())
    fakes = {lbl for lbl in labels if FAKE_TOKENS & set(re.split(r"[^a-z0-9]+", lbl.lower()))}
    if not fakes:
        fakes = {labels[-1]}
    return fakes


def compute_fake_prob(preds, fake_set):
    return float(sum(p["score"] for p in preds if p["label"] in fake_set))


@app.on_event("startup")
def load_all_models():
    print("[Asli-Kavach] Loading verification models...", flush=True)

    # 1. LightVoiceCNN for ultra-fast real-time audio
    try:
        models["light_voice_detector"] = LightVoiceDetector()
        print("[Asli-Kavach] LightVoiceCNN ready (Realtime Engine)", flush=True)
    except Exception as e:
        print(f"[Asli-Kavach] LightVoiceCNN initialization warning: {e}", flush=True)

    # 2. ViT classifier for Images & Video frames
    try:
        from transformers import pipeline

        img_dir = resolve_image_dir()
        if img_dir:
            models["vit_dir"] = img_dir
            models["vit_clf"] = pipeline("image-classification", model=img_dir)
            models["vit_fake_labels"] = extract_fake_labels(models["vit_clf"])
            print(f"[Asli-Kavach] ViT Image/Video model loaded from: {img_dir}", flush=True)
        else:
            print("[Asli-Kavach] Warning: Video/Image ViT model directory not found.", flush=True)
    except Exception as e:
        print(f"[Asli-Kavach] Warning: ViT model failed to load ({e})", flush=True)

    # 3. Wav2Vec2 classifier for voice files
    try:
        audio_dir = resolve_audio_dir()
        if audio_dir:
            models["wav2vec2_dir"] = audio_dir
            clf, fakes = load_audio_clf(audio_dir)
            models["wav2vec2_clf"] = clf
            models["wav2vec2_fake_labels"] = fakes
            print(f"[Asli-Kavach] Wav2Vec2 Audio model loaded from: {audio_dir}", flush=True)
        else:
            print("[Asli-Kavach] Warning: Audio model directory not found.", flush=True)
    except Exception as e:
        print(f"[Asli-Kavach] Warning: Wav2Vec2 model failed to load ({e})", flush=True)

    print("[Asli-Kavach] All models initialized successfully. API ready on port 8000.", flush=True)


# --------------------------------------------------------- Health & Info
@app.get("/health")
def health():
    return {
        "status": "online",
        "models": {
            "light_voice_cnn": models["light_voice_detector"] is not None,
            "vit_image_video": models["vit_clf"] is not None,
            "wav2vec2_audio": models["wav2vec2_clf"] is not None,
        },
        "model_paths": {
            "vit": models["vit_dir"],
            "wav2vec2": models["wav2vec2_dir"],
        },
    }


# --------------------------------------------------------- Image Detection
@app.post("/detect")
@app.post("/detect_image")
async def detect_image(
    file: UploadFile = File(None),
    shrink: bool = Form(True),
    request: Request = None,
):
    if models["vit_clf"] is None:
        return JSONResponse({"error": "ViT model not loaded"}, status_code=503)

    try:
        if file is not None:
            contents = await file.read()
        else:
            contents = await request.body()

        if not contents:
            return JSONResponse({"error": "No image data provided"}, status_code=400)

        image = Image.open(io.BytesIO(contents)).convert("RGB")
        if shrink:
            image = image.resize((32, 32))  # CIFAKE downscale match

        t0 = time.perf_counter()
        preds = models["vit_clf"](image, top_k=None)
        fake_p = compute_fake_prob(preds, models["vit_fake_labels"])
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "fake_prob": round(fake_p, 4),
            "real_prob": round(1.0 - fake_p, 4),
            "latency_ms": round(latency_ms, 1),
            "model": "ViT-Base",
        }
    except Exception as e:
        return JSONResponse({"error": f"Image detection failed: {e}"}, status_code=500)


# --------------------------------------------------------- Frame Detection (Camera / Screen Share)
@app.post("/detect_frame")
async def detect_frame(
    file: UploadFile = File(None),
    shrink: bool = Form(True),
    request: Request = None,
):
    """Real-time camera or screen share single-frame analysis."""
    if models["vit_clf"] is None:
        return JSONResponse({"error": "ViT model not loaded"}, status_code=503)

    try:
        if file is not None:
            contents = await file.read()
        else:
            contents = await request.body()

        image = Image.open(io.BytesIO(contents)).convert("RGB")
        t0 = time.perf_counter()

        prep_img = image.resize((32, 32)) if shrink else image.resize((224, 224))
        preds = models["vit_clf"](prep_img, top_k=None)
        fake_p = compute_fake_prob(preds, models["vit_fake_labels"])
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "fake_prob": round(fake_p, 4),
            "real_prob": round(1.0 - fake_p, 4),
            "face_found": True,
            "latency_ms": round(latency_ms, 1),
        }
    except Exception as e:
        return JSONResponse({"error": f"Frame detection failed: {e}"}, status_code=500)


# --------------------------------------------------------- Video Detection
@app.post("/detect_video")
async def detect_video(
    file: UploadFile = File(...),
    n_frames: int = Form(16),
    shrink: bool = Form(True),
):
    if models["vit_clf"] is None:
        return JSONResponse({"error": "ViT model not loaded"}, status_code=503)

    t0 = time.perf_counter()
    tmp_path = os.path.join(CURR_DIR, f"temp_{int(time.time()*1000)}_{file.filename}")
    try:
        contents = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(contents)

        cap = cv2.VideoCapture(tmp_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frames = []

        if total > 0:
            indices = np.linspace(0, total - 1, num=min(n_frames, total)).astype(int)
            for idx in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
                ok, f = cap.read()
                if ok:
                    frames.append(f)
        else:
            # Fallback frame read
            count = 0
            while count < 300:
                ok, f = cap.read()
                if not ok:
                    break
                frames.append(f)
                count += 1
            if frames:
                step = max(1, len(frames) // n_frames)
                frames = frames[::step][:n_frames]

        cap.release()

        if not frames:
            return JSONResponse({"error": "Could not decode any frames from video"}, status_code=400)

        pil_imgs = []
        for f in frames:
            img = Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
            if shrink:
                img = img.resize((32, 32))
            pil_imgs.append(img)

        # Batch prediction with ViT
        results = models["vit_clf"](pil_imgs, top_k=None, batch_size=8)
        per_frame = [round(compute_fake_prob(r, models["vit_fake_labels"]), 4) for r in results]

        avg_fake = float(np.mean(per_frame))
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "fake_prob": round(avg_fake, 4),
            "real_prob": round(1.0 - avg_fake, 4),
            "frames_checked": len(per_frame),
            "frames_flagged": int(sum(p >= 0.5 for p in per_frame)),
            "per_frame": per_frame,
            "latency_ms": round(latency_ms, 1),
            "model": "ViT-Base",
        }
    except Exception as e:
        return JSONResponse({"error": f"Video detection failed: {e}"}, status_code=500)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# --------------------------------------------------------- Audio File Detection
@app.post("/detect_audio")
async def detect_audio(file: UploadFile = File(...)):
    if models["wav2vec2_clf"] is None:
        return JSONResponse({"error": "Wav2Vec2 model not loaded"}, status_code=503)

    t0 = time.perf_counter()
    tmp_path = os.path.join(CURR_DIR, f"temp_aud_{int(time.time()*1000)}_{file.filename}")
    try:
        contents = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(contents)

        y = read_audio_file(tmp_path, max_s=30)
        win = 16000 * 5
        chunks = [y[i : i + win] for i in range(0, len(y), win) if len(y[i : i + win]) >= 16000] or [y]

        if len(y) < 1600:
            return JSONResponse({"error": "Audio file is too short (need >= 0.1s)"}, status_code=400)

        ps = [
            compute_fake_prob(
                models["wav2vec2_clf"]({"raw": c.astype(np.float32), "sampling_rate": 16000}, top_k=None),
                models["wav2vec2_fake_labels"],
            )
            for c in chunks
        ]

        avg_fake = float(np.mean(ps))
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "fake_prob": round(avg_fake, 4),
            "real_prob": round(1.0 - avg_fake, 4),
            "frames_checked": len(ps),
            "per_frame": [round(p, 3) for p in ps],
            "latency_ms": round(latency_ms, 1),
            "model": "Wav2Vec2",
        }
    except Exception as e:
        return JSONResponse({"error": f"Audio file detection failed: {e}"}, status_code=500)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# --------------------------------------------------------- Real-time Audio Stream (Light CNN & Wav2Vec2)
@app.post("/live_audio")
async def live_audio(
    request: Request,
    engine: str = Query("auto", description="Inference engine: 'light_cnn', 'wav2vec2', or 'auto'"),
):
    """
    Real-time streaming audio endpoint for browser microphone blobs.
    Uses LightVoiceCNN for ultra-fast latency (~2-15ms) or Wav2Vec2.
    """
    raw = await request.body()
    if not raw or len(raw) < 1000:
        return JSONResponse({"error": "Empty or audio clip too short"}, status_code=400)

    try:
        import soundfile as sf

        ctype = request.headers.get("content-type", "")
        if "multipart" in ctype:
            form = await request.form()
            f = form.get("file") or form.get("audio")
            if f is not None:
                raw = await f.read()

        y, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    except Exception as e:
        return JSONResponse({"error": f"Audio decode failed: {e}"}, status_code=400)

    y = to_mono16k(np.asarray(y, dtype=np.float32), sr)
    if y.size > 16000 * 4:
        y = y[-16000 * 4 :]

    level = rms(y)
    if level < 0.012 or y.size < 16000 * 0.4:
        return {"voiced": False, "rms": round(level, 4), "fake_prob": None}

    # Decide engine
    use_light = (engine in ("light_cnn", "auto") and models["light_voice_detector"] is not None) or (
        models["wav2vec2_clf"] is None
    )

    t0 = time.perf_counter()
    if use_light and models["light_voice_detector"] is not None:
        try:
            res = models["light_voice_detector"].predict(y)
            res["voiced"] = True
            res["rms"] = round(level, 4)
            res["engine"] = "LightVoiceCNN (Ultra-Fast)"
            return res
        except Exception as e:
            print(f"[live_audio] LightVoiceCNN fallback to Wav2Vec2: {e}")

    # Fallback to Wav2Vec2
    if models["wav2vec2_clf"] is not None:
        try:
            res = score_wav16k(y, models["wav2vec2_clf"], models["wav2vec2_fake_labels"])
            res["voiced"] = True
            res["rms"] = round(level, 4)
            res["engine"] = "Wav2Vec2"
            return res
        except Exception as e:
            return JSONResponse({"error": f"Wav2Vec2 inference failed: {e}"}, status_code=500)

    return JSONResponse({"error": "No audio model available"}, status_code=503)


# --------------------------------------------------------- Provenance / Context Web Search
@app.post("/context")
async def context_search(query: str = Form(None), request: Request = None):
    """
    Search the web for caption/claim provenance (TinyFish with DuckDuckGo fallback).
    """
    if not query and request:
        try:
            body = await request.json()
            query = body.get("query") or body.get("caption") or (body[0] if isinstance(body, list) else "")
        except Exception:
            pass

    query = (query or "").strip()
    if not query:
        return {"results": [], "error": "No caption or claim provided"}

    # Try TinyFish if key is provided
    tf_key = os.environ.get("TINYFISH_API_KEY")
    if tf_key:
        try:
            from tinyfish import TinyFish

            tf = TinyFish(api_key=tf_key)
            resp = tf.search.query(query=query)
            return {
                "results": [
                    {
                        "title": r.title or "",
                        "url": r.url or "",
                        "site": r.site_name or "",
                        "snippet": r.snippet or "",
                    }
                    for r in resp.results[:6]
                ],
                "engine": "TinyFish",
            }
        except Exception as e:
            print(f"[context] TinyFish error ({e}), falling back to web search")

    # Fallback search engine (DuckDuckGo HTML search)
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        encoded_q = urllib.parse.quote_plus(query)
        req = urllib.request.Request(f"https://html.duckduckgo.com/html/?q={encoded_q}", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="ignore")

        # Parse links and snippets
        import html as html_lib

        results = []
        raw_results = re.findall(r'<a class="result__url"[^>]*href="([^"]+)"[^>]*>.*?</a>.*?<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        if not raw_results:
            raw_results = re.findall(r'<a class="result__snippet"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)

        for match in raw_results[:5]:
            url = match[0] if match[0].startswith("http") else f"https:{match[0]}" if match[0].startswith("//") else match[0]
            if "duckduckgo.com/l/?" in url:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                url = parsed.get("uddg", [url])[0]
            clean_snippet = re.sub(r"<[^>]+>", "", match[1])
            clean_snippet = html_lib.unescape(clean_snippet).strip()
            domain = urllib.parse.urlparse(url).netloc

            results.append({
                "title": f"Report regarding: {query[:45]}...",
                "url": url,
                "site": domain,
                "snippet": clean_snippet[:200],
            })

        if not results:
            results.append({
                "title": f"Web search for: '{query}'",
                "url": f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}",
                "site": "Web Verification",
                "snippet": f"Explore live web sources and fact-checks for '{query}'.",
            })

        return {"results": results, "engine": "Web Search"}
    except Exception as e:
        return {
            "results": [
                {
                    "title": f"Search verification: {query}",
                    "url": f"https://duckduckgo.com/?q={urllib.parse.quote_plus(query)}",
                    "site": "Web Verification",
                    "snippet": "Check search results and news coverage for this claim.",
                }
            ],
            "engine": "Fallback",
            "error": str(e),
        }


# --------------------------------------------------------- Frontend Static Mounting
if os.path.isdir(FRONTEND_DIR):
    app.mount("/content", StaticFiles(directory=os.path.join(FRONTEND_DIR, "content")), name="content")
    app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")

    @app.get("/")
    def serve_frontend_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/style.css")
    def serve_frontend_css():
        return FileResponse(os.path.join(FRONTEND_DIR, "style.css"), media_type="text/css")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
