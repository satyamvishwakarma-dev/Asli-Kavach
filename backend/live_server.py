"""Asli Kavach Unified Server Entry Point.
Runs the unified FastAPI server connecting ViT, Wav2Vec2, LightVoiceCNN, and the web frontend.

Run with:
    .venv/Scripts/python backend/live_server.py
"""
import os
import sys

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
CONN_DIR = os.path.join(CURR_DIR, "connections")
if CONN_DIR not in sys.path:
    sys.path.insert(0, CONN_DIR)

from server import app

if __name__ == "__main__":
    import uvicorn
    print("[Asli-Kavach] Launching unified backend on http://127.0.0.1:8000 ...", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8000)
