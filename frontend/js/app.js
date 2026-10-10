const pages = ['home', 'upload', 'team', 'contact'];
const MODE_HASH = { audio: '#check-audio', video: '#check-video', image: '#check-image' };
function syncHash(page, m) {
    let h = page === 'upload' ? (MODE_HASH[m || mode] || '#check') : page === 'home' ? '#home' : '#' + page;
    if (location.hash !== h) history.replaceState(null, '', h);
}
function goto(p, push = true) {
    pages.forEach(id => document.getElementById('page-' + id).classList.toggle('active', id === p));
    [...document.getElementById('navtabs').children].forEach(b => b.classList.toggle('active', b.dataset.page === p));
    const bar = document.querySelector('.topbar');
    bar.classList.toggle('is-check', p === 'upload');
    bar.classList.remove('is-hidden');
    if (push) syncHash(p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* Floating bar: hide on scroll down, show on scroll up */
(function initTopbarScroll() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const bar = document.querySelector('.topbar');
    let lastY = window.scrollY, ticking = false;
    window.addEventListener('scroll', () => {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(() => {
            const y = window.scrollY;
            bar.classList.toggle('scrolled', y > 24);
            if (y > 140 && y > lastY + 6) bar.classList.add('is-hidden');
            else if (y < lastY - 6 || y < 140) bar.classList.remove('is-hidden');
            lastY = y;
            ticking = false;
        });
    }, { passive: true });
})();
document.getElementById('navtabs').addEventListener('click', e => {
    const b = e.target.closest('button'); if (b) goto(b.dataset.page);
});
document.querySelectorAll('[data-goto]').forEach(el => el.addEventListener('click', () => goto(el.dataset.goto)));

const members = ["Aaradhya Veer Singh", "Satyam Vishwakarma", "Simran Swain", "Manjesh Kumar", "Harsh Agarwal"];
const grid = document.getElementById('flashgrid');
members.forEach(name => {
    const initials = name.split(' ').map(w => w[0]).slice(0, 2).join('');
    const el = document.createElement('div');
    el.className = 'flashcard';
    el.innerHTML = `<div class="flashcard-inner">
    <div class="flashface flashfront"><div class="monogram">${initials}</div><b>${name}</b></div>
    <div class="flashface flashback"><div class="tag">Shadow Apex</div><p>Asli Kavach<br>KCC Institut of Technology and Management</p></div>
  </div>`;
    el.addEventListener('click', () => { if (!window.matchMedia('(hover: hover)').matches) el.classList.toggle('flip'); });
    grid.appendChild(el);
});

document.getElementById('contactForm').addEventListener('submit', e => {
    e.preventDefault();
    document.getElementById('sentMsg').classList.add('active');
});

let mode = 'audio', live = false, hasSpeech = false, audioCtx, analyser, micStream, rafId, liveTimer, liveWins, frames = 0, sp = 50, target = 10, blobs = [], curFile = null;
const $ = id => document.getElementById(id);
const wave = $('wave'), wctx = wave.getContext('2d'), heat = $('heat'), hctx = heat.getContext('2d');
const TXT = {
    audio: { r: ['LIKELY REAL VOICE', 'Natural harmonics and breath patterns detected'], f: ['LIKELY AI-GENERATED VOICE', 'Vocoder artifacts and flat spectral texture detected'] },
    video: { r: ['LIKELY REAL VIDEO', 'Sampled frames show no synthetic-image patterns'], f: ['LIKELY AI-GENERATED VIDEO', 'Synthetic-image patterns detected across sampled frames'] }
};
TXT.audio = { r: ['LIKELY REAL VOICE', 'No synthetic-speech patterns detected by the model'], f: ['LIKELY AI-GENERATED VOICE', 'Synthetic-speech patterns detected by the model'] };
TXT.image = { r: ['LIKELY REAL IMAGE', 'No synthetic-image patterns detected by the model'], f: ['LIKELY AI-GENERATED IMAGE', 'Synthetic-image patterns detected by the model'] };

function setState(t, on) { $('stateTxt').textContent = t; $('statePill').classList.toggle('on', !!on); }
function setIdle(title, sub) { $('vt').textContent = title; $('vt').className = 'vt'; $('vs').textContent = sub; $('spPct').textContent = '—'; $('spBar').style.width = '0'; drawHeat(0); }
function setVerdict(v) {
    const fake = v >= 50, t = TXT[mode][fake ? 'f' : 'r'];
    $('vt').textContent = t[0]; $('vt').className = 'vt ' + (fake ? 'fake' : 'real'); $('vs').textContent = t[1]; $('spPct').textContent = v.toFixed(1) + '%';
    $('spBar').style.width = v + '\%'; $('spBar').style.background = fake ? '#FF5F5F' : '#33D89C';
    drawHeat(v);
}
function drawHeat(v) {
    hctx.clearRect(0, 0, heat.width, heat.height);
    if (!blobs.length) blobs = Array.from({ length: 6 }, () => ({ x: Math.random(), y: Math.random(), r: 35 + Math.random() * 55 }));
    const fake = v >= 50, k = v / 100;
    blobs.forEach(b => {
        const g = hctx.createRadialGradient(b.x * heat.width, b.y * heat.height, 0, b.x * heat.width, b.y * heat.height, b.r);
        const c = fake ? '255,95,95' : '51,216,156';
        g.addColorStop(0, 'rgba(' + c + ',' + (0.15 + k * 0.6) + ')'); g.addColorStop(1, 'rgba(' + c + ',0)');
        hctx.fillStyle = g; hctx.fillRect(0, 0, heat.width, heat.height);
    });
}
function resetAll() {
    stopLive(); curFile = null; frames = 0; blobs = [];
    $('runBtn').style.display = 'none'; $('fname').textContent = ''; $('sFrames').textContent = '0'; $('sLat').textContent = '—'; $('sStatus').textContent = 'IDLE';
    $('ph').style.display = 'flex'; $('ph').textContent = 'No input yet';
    $('vid').style.display = 'none'; $('vid').removeAttribute('src'); $('imgPrev').style.display = 'none'; $('imgPrev').removeAttribute('src'); wave.style.display = 'block'; wctx.clearRect(0, 0, wave.width, wave.height);
    setState('IDLE', false);
    setIdle('AWAITING INPUT', mode === 'audio' ? 'Start listening or inject a file to begin.' : mode === 'image' ? 'Inject an image file to begin.' : 'Inject a video file to begin.');
}
function setMode(m, push = true) {
    mode = m;
    [...$('modeSwitch').children].forEach(b => {
        const on = b.dataset.mode === m;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    const a = m === 'audio';
    $('fileInput').accept = { audio: 'audio/*', video: 'video/*', image: 'image/*' }[m]; $('leftTitle').textContent = a ? 'Audio telemetry stream' : m === 'image' ? 'Image injection stream' : 'Video injection stream';
    $('liveBtn').style.display = a ? '' : 'none'; $('sStatusLbl').textContent = a ? 'VAD status' : 'Input status';
    $('meta').innerHTML = a ? 'RATE: 16 kHz<br>WINDOW: 3s' : m === 'image' ? 'MODEL: ViT-Base (fine-tuned)<br>INPUT: IMAGE FILE' : 'FRAMES: 16 evenly spaced<br>MODEL: ViT (frame-level)'; $('heatTitle').textContent = a ? 'Spectral anomaly heatmap' : m === 'image' ? 'Anomaly heatmap' : 'Frame anomaly heatmap';
    $('heatNote').textContent = m === 'video' ? 'Fake probability per sampled frame' : m === 'image' ? 'Illustrative only' : 'Demo visualization'; $('note').textContent = a ? 'Live mic hears room + mic noise, which masks AI voice evidence — replayed clips read REAL even when fake. Reliable live path: digital routing (AUX cable / Stereo Mix / VB-Cable) or Inject test file. Sidecars: live ' + LIVE_URL + ', files :7860.' : m === 'image' ? 'Live model: image verdicts come from the trained detector. The heatmap is decorative.' : 'Live model: the video is sampled into frames and each frame is scored by the image detector.';
    resetAll();
    if (push && $('page-upload').classList.contains('active')) syncHash('upload', m);
}
$('modeSwitch').addEventListener('click', e => { const b = e.target.closest('button'); if (b && b.dataset.mode !== mode) setMode(b.dataset.mode); });

/* Live audio: real 3s windows scored by the FastAPI sidecar (Wav2Vec2) */
let procNode = null, micSource = null, pcmBuf = [], pcmLen = 0, liveBusy = false, liveEma = null, liveFails = 0, liveSkips = 0, liveLastBlobUrl = null;
$('liveBtn').addEventListener('click', () => { live ? stopLive(true) : startLive(); });
async function liveHealth() {
    try {
        const r = await fetch(LIVE_URL + '/health');
        return r.ok;
    } catch (e) { return false; }
}
function encodeWav16k(samples) {
    const n = samples.length, buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
    const ws = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    ws(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); ws(8, 'WAVE'); ws(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, 16000, true); v.setUint32(28, 32000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    ws(36, 'data'); v.setUint32(40, n * 2, true);
    for (let i = 0; i < n; i++) { const s = Math.max(-1, Math.min(1, samples[i])); v.setInt16(44 + i * 2, s * 32767, true); }
    return new Blob([buf], { type: 'audio/wav' });
}
function downsample16k(chunks, inRate) {
    let flat = new Float32Array(pcmLen), o = 0;
    for (const c of chunks) { flat.set(c, o); o += c.length; }
    if (inRate === 16000) return flat.slice(-16000 * 3);
    const ratio = inRate / 16000, len = Math.floor(flat.length / ratio);
    const out = new Float32Array(Math.min(len, 16000 * 3));
    const start = Math.max(0, len - out.length);
    for (let i = 0; i < out.length; i++) out[i] = flat[Math.floor((start + i) * ratio)] || 0;
    return out;
}
async function sendLiveWindow() {
    if (!live || liveBusy || mode !== 'audio') return;
    if (!pcmLen) return;
    const sr = audioCtx.sampleRate;
    const win = downsample16k(pcmBuf, sr);
    pcmBuf = []; pcmLen = 0;
    let e = 0; for (let i = 0; i < win.length; i++) e += win[i] * win[i];
    const rms = Math.sqrt(e / Math.max(1, win.length));
    if (rms < 0.012 || win.length < 16000 * 0.5) {
        // too quiet (e.g. speaker far from mic): skip, but say so
        liveSkips++;
        $('sStatus').textContent = 'SILENT';
        if (liveSkips >= 3 && !hasSpeech) $('vs').textContent = 'Mic level very low (' + rms.toFixed(3) + ') — move the sound source closer to the mic or raise the volume. Windows are skipped until level rises.';
        return;
    }
    liveSkips = 0;
    liveBusy = true;
    const t0 = performance.now();
    try {
        const wavBlob = encodeWav16k(win);
        // keep exact bytes sent, so a window can be file-checked for comparison
        if (liveLastBlobUrl) URL.revokeObjectURL(liveLastBlobUrl);
        liveLastBlobUrl = URL.createObjectURL(wavBlob);
        const r = await fetch(LIVE_URL + '/live_audio', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wavBlob });
        const j = await r.json();
        if (!live) return;
        if (j.voiced === false) { $('sStatus').textContent = 'SILENT'; return; }
        if (j.fake_prob == null) throw new Error(j.error || 'bad response');
        liveFails = 0;
        const v = Math.max(0, Math.min(100, j.fake_prob * 100));
        liveEma = liveEma == null ? v : liveEma * 0.55 + v * 0.45; // smooth flicker
        frames += 1; $('sFrames').textContent = frames;
        const net = Math.round(performance.now() - t0);
        $('sLat').textContent = (j.latency_ms != null ? Math.round(j.latency_ms) + '+' + Math.max(0, net - Math.round(j.latency_ms)) : net) + ' ms';
        hasSpeech = true;
        setVerdict(liveEma);
        $('fname').textContent = 'Live win #' + frames + ': raw ' + v.toFixed(1) + '% → smooth ' + liveEma.toFixed(1) + '% (lvl ' + rms.toFixed(3) + ')';
        console.log('[live] win#' + frames, 'rms=' + rms.toFixed(4), 'raw=' + v.toFixed(1) + '%', 'ema=' + liveEma.toFixed(1) + '%');
        $('sStatus').textContent = 'VOICE'; setState('LIVE', true);
    } catch (err) {
        console.error(err);
        liveFails++;
        $('sStatus').textContent = 'ERROR'; setState('ERROR', false);
        $('vs').textContent = 'Live sidecar unreachable at ' + LIVE_URL + ' (' + liveFails + 'x). Start backend/live_server.py. ' + (err && err.message || '');
    }
    liveBusy = false;
}
async function startLive() {
    // Raw mic: browser AEC / noise-suppression / AGC scrub the subtle
    // vocoder artifacts the fake-detector looks for, biasing live to "real".
    try { micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1, sampleRate: 16000 } }); }
    catch (err) { $('ph').textContent = 'Microphone access denied'; return; }
    resetAll();
    audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    analyser = audioCtx.createAnalyser(); analyser.fftSize = 2048;
    micSource = audioCtx.createMediaStreamSource(micStream);
    micSource.connect(analyser);
    // raw PCM tap (no ffmpeg needed: we encode 16k WAV client-side)
    procNode = audioCtx.createScriptProcessor(4096, 1, 1);
    pcmBuf = []; pcmLen = 0;
    procNode.onaudioprocess = ev => {
        if (!live) return;
        const ch = ev.inputBuffer.getChannelData(0).slice();
        pcmBuf.push(ch); pcmLen += ch.length;
        while (pcmLen > audioCtx.sampleRate * 10) { const old = pcmBuf.shift(); pcmLen -= old.length; }
    };
    const mute = audioCtx.createGain(); mute.gain.value = 0;
    micSource.connect(procNode); procNode.connect(mute); mute.connect(audioCtx.destination);
    live = true; hasSpeech = false; liveEma = null; liveFails = 0; frames = 0;
    $('liveBtn').textContent = 'Halt listening'; $('liveBtn').classList.add('red');
    $('ph').style.display = 'none'; $('sStatus').textContent = 'LISTENING';
    const ok = await liveHealth();
    if (!ok) {
        setIdle('SIDECAR OFFLINE', 'Mic is live but the model sidecar is unreachable at ' + LIVE_URL + '. Run backend/live_server.py, then speak — windows will auto-score once it is up.');
        setState('LIVE (NO MODEL)', true);
    } else {
        setState('LIVE', true); setIdle('LISTENING…', 'Speak — every 3s window is scored by the Wav2Vec2 model.');
    }
    drawWave(); liveTimer = setInterval(tick, 700); liveWins = setInterval(sendLiveWindow, 3000);
}
function stopLive(reset) {
    if (!live) return;
    live = false; clearInterval(liveTimer); clearInterval(liveWins); cancelAnimationFrame(rafId);
    try { if (procNode) procNode.disconnect(); } catch (e) {}
    try { if (micSource) micSource.disconnect(); } catch (e) {}
    procNode = null; micSource = null; pcmBuf = []; pcmLen = 0; liveBusy = false; liveSkips = 0;
    if (micStream) micStream.getTracks().forEach(t => t.stop());
    if (audioCtx) audioCtx.close(); audioCtx = null;
    $('liveBtn').textContent = 'Start listening'; $('liveBtn').classList.remove('red');
    wctx.clearRect(0, 0, wave.width, wave.height);
    $('sStatus').textContent = 'STOPPED'; setState('IDLE', false);
    if (reset) $('ph').style.display = 'none';
}
function tick() {
    if (!analyser || !live) return;
    const d = new Uint8Array(analyser.fftSize); analyser.getByteTimeDomainData(d);
    let s = 0; for (const x of d) { const v = (x - 128) / 128; s += v * v; }
    const voice = Math.sqrt(s / d.length) > 0.02;
    if (!hasSpeech) $('sStatus').textContent = voice ? 'VOICE' : 'SILENT';
}
// Download the exact bytes the last live window sent — file-check them via
// "Inject test file" to compare live vs file verdict on identical audio.
window.asliSaveLiveWindow = function () {
    if (!liveLastBlobUrl) { console.warn('[live] no window scored yet'); return; }
    const a = document.createElement('a');
    a.href = liveLastBlobUrl; a.download = 'live-window.wav'; a.click();
};
function drawWave() {
    rafId = requestAnimationFrame(drawWave);
    const d = new Uint8Array(analyser.fftSize); analyser.getByteTimeDomainData(d);
    wctx.clearRect(0, 0, wave.width, wave.height);
    wctx.lineWidth = 2; wctx.strokeStyle = '#33D89C'; wctx.shadowColor = '#33D89C'; wctx.shadowBlur = 8; wctx.beginPath();
    const sl = wave.width / d.length; let x = 0;
    for (let i = 0; i < d.length; i++) { const y = d[i] / 128 * wave.height / 2; i ? wctx.lineTo(x, y) : wctx.moveTo(x, y); x += sl; }
    wctx.stroke();
}

/* File injection */
$('injectBtn').addEventListener('click', () => { stopLive(); $('fileInput').click(); }); $('fileInput').addEventListener('change', () => {
    const f = $('fileInput').files[0]; if (!f) return;
    resetAll(); curFile = f;
    $('fname').textContent = 'Injected: ' + f.name;
    $('runBtn').style.display = ''; $('runBtn').disabled = false;
    $('sStatus').textContent = 'READY'; setState('READY', true);
    setIdle('FILE LOADED', 'Press Run verification to analyze this file.');
    if (mode === 'video') { $('vid').src = URL.createObjectURL(f); $('vid').style.display = 'block'; wave.style.display = 'none'; $('ph').style.display = 'none'; }
    else if (mode === 'image') { $('imgPrev').src = URL.createObjectURL(f); $('imgPrev').style.display = 'block'; wave.style.display = 'none'; $('ph').style.display = 'none'; }
    else { $('ph').textContent = 'Audio file loaded'; } $('fileInput').value = '';
});

const API_URL = 'http://127.0.0.1:7860';
const LIVE_URL = localStorage.getItem('asli_live_url') || 'http://127.0.0.1:8000';
const ENDPOINT = { image: '/detect', video: '/detect_video', audio: '/detect_audio' };
let gradioClient = null;
async function getClient() {
    if (!gradioClient) {
        const { Client } = await import('https://cdn.jsdelivr.net/npm/@gradio/client/dist/index.min.js');
        gradioClient = await Client.connect(API_URL);
    }
    return gradioClient;
}
function drawFrames(arr) {
    hctx.clearRect(0, 0, heat.width, heat.height);
    const w = heat.width / arr.length;
    arr.forEach((p, i) => {
        const c = p >= 0.5 ? '255,95,95' : '51,216,156';
        hctx.fillStyle = 'rgba(' + c + ',' + (0.25 + 0.7 * Math.abs(p - 0.5) * 2) + ')';
        hctx.fillRect(i * w, 0, Math.max(w - 2, 1), heat.height);
    });
}
async function runModel() {
    const m = mode, f = curFile;
    $('runBtn').disabled = true; $('sStatus').textContent = 'ANALYZING'; setState('ANALYZING', true);
    setIdle('ANALYZING…', m === 'video' ? 'Sampling frames and scoring each one (first run can be slow)' : 'Sending file to the model');
    const t0 = performance.now();
    try {
        const c = await getClient();
        const r = await c.predict(ENDPOINT[m], m === 'image' ? [f, true] : [f]);
        if (m !== mode) return;
        const res = r.data[0];
        const v = Math.max(0, Math.min(100, res.fake_prob * 100));
        frames = res.frames_checked || 1; $('sFrames').textContent = frames;
        $('sLat').textContent = Math.round(performance.now() - t0) + ' ms';
        setVerdict(v);
        if (m === 'video' && res.per_frame) {
            drawFrames(res.per_frame);
            $('vs').textContent += ' (' + res.frames_flagged + ' of ' + res.frames_checked + ' frames flagged)';
        }
        $('sStatus').textContent = 'DONE'; setState('COMPLETE', true);
    } catch (err) {
        console.error(err);
        setIdle('MODEL UNREACHABLE', 'Could not get a result from ' + API_URL + ': ' + ((err && err.message) || JSON.stringify(err)));
        $('sStatus').textContent = 'ERROR'; setState('ERROR', false);
    }
    $('runBtn').disabled = false;
}
$('runBtn').addEventListener('click', () => { if (curFile) runModel(); });
document.getElementById('navtabs').addEventListener('click', () => { if (!$('page-upload').classList.contains('active')) stopLive(); });
function routeFromHash() {
    const h = (location.hash || '').toLowerCase();
    if (h.startsWith('#check')) {
        const m = h.includes('video') ? 'video' : h.includes('image') ? 'image' : h.includes('audio') ? 'audio' : mode;
        goto('upload', false);
        if (m !== mode) setMode(m, false);
        else syncHash('upload', mode);
    } else if (h === '#team' || h === '#contact' || h === '#home') {
        goto(h.slice(1) === 'home' ? 'home' : h.slice(1), false);
    } else {
        goto('home', false);
    }
}
window.addEventListener('hashchange', routeFromHash);
setMode('audio', false);
routeFromHash();