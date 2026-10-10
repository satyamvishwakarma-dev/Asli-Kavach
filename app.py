import os
import re
import numpy as np
import cv2
import gradio as gr
from PIL import Image
from transformers import pipeline

try:
    from tinyfish import TinyFish
except ImportError:          # the detectors still work without it
    TinyFish = None

BASE = os.path.dirname(os.path.abspath(__file__))


def find_dir(*names):
    for n in names:
        d = os.path.abspath(os.path.join(BASE, n))
        if os.path.isfile(os.path.join(d, "config.json")) and os.path.isfile(os.path.join(d, "model.safetensors")):
            return d
    return None


# ---------------------------------------------------------------- models
IMG_DIR = find_dir("video model", "video_model", "image_model")      # ViT trained on CIFAKE (generic images)
FACE_DIR = find_dir("face_model", "face model", ".")                  # ViT trained on real/fake FACES ("." = loose files next to app.py)
VOICE_DIR = find_dir("voice_model")                                   # Wav2Vec2 voice classifier

if not IMG_DIR:
    raise SystemExit("Image model not found (expected a 'video model' folder with config.json + model.safetensors)")

img_clf = pipeline("image-classification", model=IMG_DIR)
face_clf = pipeline("image-classification", model=FACE_DIR) if FACE_DIR else None
voice_clf = pipeline("audio-classification", model=VOICE_DIR) if VOICE_DIR else None

FAKE_TOKENS = {"fake", "spoof", "spoofed", "ai", "synthetic", "deepfake", "generated", "artificial"}


def fake_labels(pipe):
    labels = list(pipe.model.config.id2label.values())
    fake = {l for l in labels if FAKE_TOKENS & set(re.split(r"[^a-z0-9]+", l.lower()))}
    if not fake:                      # labels like LABEL_0 / LABEL_1 -> assume last class = fake
        fake = {labels[-1]}
    print(f"[{type(pipe.model).__name__}] labels={labels}  treated as FAKE={sorted(fake)}")
    return fake


IMG_FAKE = fake_labels(img_clf)
FACE_FAKE = fake_labels(face_clf) if face_clf else set()
VOICE_FAKE = fake_labels(voice_clf) if voice_clf else set()


def fake_prob(preds, fake_set):
    return float(sum(p["score"] for p in preds if p["label"] in fake_set))


def pack(p, **extra):
    return {"fake_prob": p, "real_prob": 1.0 - p, **extra}


# ---------------------------------------------------------------- faces
_face = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))


def prep(img, shrink):
    img = img.convert("RGB")
    return img.resize((32, 32)) if shrink else img     # the CIFAKE model was trained on 32x32


def face_score(img, shrink=True):
    """Largest face in the picture -> (fake_prob, box, n_faces), or None when there is no face.
    Uses the face model at full resolution when it is loaded, else the CIFAKE model on a 32x32 crop."""
    rgb = np.array(img.convert("RGB"))
    H, W = rgb.shape[:2]
    if W > 1600:                                        # keep the face finder fast on big photos
        rgb = cv2.resize(rgb, (1600, int(H * 1600 / W)))
        H, W = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    m_size = max(40, W // 25)
    faces = _face.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(m_size, m_size))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    m = int(0.2 * max(w, h))
    x0, y0, x1, y1 = max(0, x - m), max(0, y - m), min(W, x + w + m), min(H, y + h + m)
    crop = Image.fromarray(rgb[y0:y1, x0:x1])
    if face_clf is not None:
        p = fake_prob(face_clf(crop, top_k=None), FACE_FAKE)
    else:
        p = fake_prob(img_clf(prep(crop, shrink), top_k=None), IMG_FAKE)
    box = [round(x0 / W, 3), round(y0 / H, 3), round((x1 - x0) / W, 3), round((y1 - y0) / H, 3)]
    return p, box, int(len(faces))


# ---------------------------------------------------------------- photo
def detect_image(img, shrink=True):
    if img is None:
        raise gr.Error("No image received")
    if face_clf is not None:                            # photo of a person -> judge the face
        r = face_score(img, shrink)
        if r:
            p, box, n = r
            return pack(p, face_found=True, faces=n, box=box)
    p = fake_prob(img_clf(prep(img, shrink), top_k=None), IMG_FAKE)   # no face / no face model: whole picture
    return pack(p, face_found=False)


# ---------------------------------------------------------------- video file
def sample_frames(path, n):
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    if total > 0:
        for i in np.linspace(0, total - 1, num=min(n, total)).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, f = cap.read()
            if ok:
                frames.append(f)
    else:                                              # e.g. webm without a frame count
        allf = []
        while len(allf) < 600:
            ok, f = cap.read()
            if not ok:
                break
            allf.append(f)
        if allf:
            frames = [allf[i] for i in np.linspace(0, len(allf) - 1, num=min(n, len(allf))).astype(int)]
    cap.release()
    return frames


def detect_video(path, n_frames=16, shrink=True):
    if not path:
        raise gr.Error("No video received")
    frames = sample_frames(path, int(n_frames))
    if not frames:
        raise gr.Error("Could not read any frames from this video")
    if face_clf is not None:                           # face model: score the face crop of every sampled frame
        res = [face_score(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))) for f in frames]
        ps = [r[0] for r in res if r]
        if not ps:
            return {"face_found": False, "fake_prob": None}
        return pack(float(np.mean(ps)), face_found=True, frames_checked=len(ps),
                    frames_flagged=int(sum(p >= 0.5 for p in ps)), per_frame=[round(p, 3) for p in ps])
    imgs = [prep(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)), shrink) for f in frames]
    per_frame = [fake_prob(r, IMG_FAKE) for r in img_clf(imgs, top_k=None, batch_size=8)]
    return pack(float(np.mean(per_frame)), frames_checked=len(per_frame),
                frames_flagged=int(sum(p >= 0.5 for p in per_frame)),
                per_frame=[round(p, 3) for p in per_frame])


# ---------------------------------------------------------------- live camera / shared window
def detect_frame(img, shrink=True):
    """One live frame: score only the largest face. No face = no verdict (a whole screen is meaningless)."""
    if img is None:
        raise gr.Error("No frame received")
    r = face_score(img, shrink)
    if r is None:
        return {"face_found": False, "fake_prob": None}
    p, box, n = r
    return pack(p, face_found=True, faces=n, box=box)


# ---------------------------------------------------------------- voice (file or live microphone)
def detect_audio(path):
    if voice_clf is None:
        raise gr.Error("voice_model folder not found next to app.py")
    if not path:
        raise gr.Error("No audio received")
    import librosa
    y, _ = librosa.load(path, sr=16000, mono=True, duration=30)
    if len(y) < 1600:
        raise gr.Error("Audio is too short")
    win = 16000 * 5
    chunks = [y[i:i + win] for i in range(0, len(y), win) if len(y[i:i + win]) >= 16000] or [y]
    ps = [fake_prob(voice_clf({"raw": c.astype(np.float32), "sampling_rate": 16000}, top_k=None), VOICE_FAKE)
          for c in chunks]
    return pack(float(np.mean(ps)), frames_checked=len(ps), per_frame=[round(p, 3) for p in ps])


# ---------------------------------------------------------------- context (TinyFish web search)
# Set the key in the terminal before starting:   set TINYFISH_API_KEY=your_key
_tf = TinyFish() if (TinyFish and os.environ.get("TINYFISH_API_KEY")) else None


def context(query):
    """Search the web for the caption/claim that came with the media."""
    query = (query or "").strip()
    if not query:
        return {"results": [], "error": "No caption or claim given."}
    if TinyFish is None:
        return {"results": [], "error": "tinyfish is not installed (pip install tinyfish)."}
    if _tf is None:
        return {"results": [], "error": "TINYFISH_API_KEY is not set on the server."}
    try:
        resp = _tf.search.query(query=query)
        return {"results": [{
            "title": r.title or "",
            "url": r.url or "",
            "site": r.site_name or "",
            "snippet": r.snippet or "",
        } for r in resp.results[:6]]}
    except Exception as e:
        return {"results": [], "error": str(e)}


# ---------------------------------------------------------------- UI / API
with gr.Blocks(title="Asli Kavach - AI media detector") as demo:
    gr.Markdown("# Asli Kavach\nBackend for the web page. Endpoints: `/detect`, `/detect_video`, "
                "`/detect_audio`, `/detect_frame`, `/context`.")
    with gr.Tab("Image"):
        i_in = gr.Image(type="pil", label="Image")
        i_shr = gr.Checkbox(value=True, label="Downscale to 32x32 first (only used by the CIFAKE model)")
        i_out = gr.JSON(label="Result")
        gr.Button("Detect").click(detect_image, [i_in, i_shr], i_out, api_name="detect")
    with gr.Tab("Video"):
        v_in = gr.File(label="Video", type="filepath")
        v_out = gr.JSON(label="Result")
        gr.Button("Detect").click(detect_video, [v_in], v_out, api_name="detect_video")
        f_in = gr.Image(type="pil", label="Single frame (face-aware, used by live mode)")
        f_out = gr.JSON(label="Result")
        gr.Button("Detect face").click(detect_frame, [f_in, i_shr], f_out, api_name="detect_frame")
    with gr.Tab("Voice"):
        a_in = gr.File(label="Audio", type="filepath")
        a_out = gr.JSON(label="Result")
        gr.Button("Detect").click(detect_audio, [a_in], a_out, api_name="detect_audio")
    with gr.Tab("Context"):
        c_in = gr.Textbox(label="Caption or claim")
        c_out = gr.JSON(label="Web results")
        gr.Button("Search").click(context, [c_in], c_out, api_name="context")


# ---------------------------------------------------------------- startup check + warm-up
def startup_report():
    def line(ok, text):
        print(("  [ OK ] " if ok else "  [ !! ] ") + text)
    try:
        import librosa  # noqa: F401
        has_librosa = True
    except ImportError:
        has_librosa = False
    print("\n=== Asli Kavach - startup check ===")
    line(True, f"Photo/generic model : {IMG_DIR}")
    if face_clf is not None:
        line(True, f"Face model          : {FACE_DIR}")
        if FACE_DIR == BASE:
            print("         tip: move config.json, model.safetensors and preprocessor_config.json into a folder called face_model")
    else:
        line(False, "Face model          : NOT FOUND - live video and photos fall back to the weak CIFAKE model")
    line(voice_clf is not None, "Voice model         : " + (VOICE_DIR or "NOT FOUND (voice_model folder)"))
    line(has_librosa, "librosa (audio files/mic) : " + ("installed" if has_librosa else "MISSING - run: pip install librosa soundfile"))
    line(hasattr(cv2, "CascadeClassifier"), "OpenCV face finder   : " + cv2.__version__)
    line(_tf is not None, "TinyFish web search  : " + ("key found" if _tf else "no key (the web-pages panel will say unavailable)"))


def warm_up():
    """Run each model once so the first request on stage is not slow."""
    try:
        blank = Image.new("RGB", (224, 224), (127, 127, 127))
        img_clf(blank.resize((32, 32)), top_k=None)
        if face_clf is not None:
            face_clf(blank, top_k=None)
        if voice_clf is not None:
            voice_clf({"raw": np.zeros(16000 * 3, dtype=np.float32), "sampling_rate": 16000}, top_k=None)
        print("Warm-up done.")
    except Exception as e:
        print("Warm-up skipped:", e)


startup_report()
warm_up()
print("\nBackend ready on http://127.0.0.1:7860\n")
demo.launch(server_name="127.0.0.1", server_port=7860, show_error=True)
