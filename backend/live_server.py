"""Asli Kavach live-audio sidecar (FastAPI, port 8000).

Run alongside the Gradio file server (port 7860):
    .venv/Scripts/python backend/live_server.py
Frontend posts 3s 16kHz mono WAV blobs from the mic -> real Wav2Vec2 verdict.
"""
import io
import os
import sys

import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "model"))
from infer_audio import load_audio_clf, resolve_audio_dir, rms, score_wav16k, to_mono16k

app = FastAPI(title="Asli Kavach live audio")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # hackathon LAN/file:// friendly
    allow_methods=["*"],
    allow_headers=["*"],
)

_clf = None
_fakes = set()
_model_dir = None


@app.on_event("startup")
def _load():
    global _clf, _fakes, _model_dir
    _model_dir = resolve_audio_dir()
    _clf, _fakes = load_audio_clf(_model_dir)
    print(f"[live] ready on 8000, model={_model_dir}", flush=True)


@app.get("/")
def root():
    return {
        "service": "asli-kavach-live",
        "status": "up" if _clf is not None else "loading",
        "model_dir": _model_dir,
        "endpoints": ["/health", "/live_audio", "/docs"],
    }


@app.get("/health")
def health():
    return {"ok": _clf is not None, "model_dir": _model_dir, "fake_labels": sorted(_fakes)}


@app.post("/live_audio")
async def live_audio(request: Request):
    if _clf is None:
        return JSONResponse({"error": "model not loaded"}, status_code=503)
    raw = await request.body()
    if not raw or len(raw) < 2000:
        return JSONResponse({"error": "empty/too-short clip"}, status_code=400)
    ctype = request.headers.get("content-type", "")
    try:
        import soundfile as sf

        if "multipart" in ctype:
            form = await request.form()
            f = form.get("file") or form.get("audio")
            if f is None:
                return JSONResponse({"error": "no file field"}, status_code=400)
            raw = await f.read()
        y, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    except Exception as e:
        return JSONResponse({"error": f"decode failed: {e}"}, status_code=400)
    y = to_mono16k(np.asarray(y, dtype=np.float32), sr)
    # keep most recent ~4s (frontend sends 3s windows)
    if y.size > 16000 * 4:
        y = y[-16000 * 4 :]
    level = rms(y)
    if level < 0.012 or y.size < 16000 * 0.5:
        return {"voiced": False, "rms": round(level, 4), "fake_prob": None}
    try:
        res = score_wav16k(y, _clf, _fakes)
    except Exception as e:
        return JSONResponse({"error": f"inference failed: {e}"}, status_code=500)
    res["voiced"] = True
    res["rms"] = round(level, 4)
    return res


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
