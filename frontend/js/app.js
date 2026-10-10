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

let mode = 'audio', live = false, hasSpeech = false, audioCtx, analyser, micStream, rafId, liveTimer, frames = 0, sp = 50, target = 10, blobs = [], curFile = null;
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
    $('heatNote').textContent = m === 'video' ? 'Fake probability per sampled frame' : m === 'image' ? 'Illustrative only' : 'Demo visualization'; $('note').textContent = a ? 'Uploaded audio files use the trained voice model. Live microphone mode is still a demo.' : m === 'image' ? 'Live model: image verdicts come from the trained detector. The heatmap is decorative.' : 'Live model: the video is sampled into frames and each frame is scored by the image detector.';
    resetAll();
    if (push && $('page-upload').classList.contains('active')) syncHash('upload', m);
}
$('modeSwitch').addEventListener('click', e => { const b = e.target.closest('button'); if (b && b.dataset.mode !== mode) setMode(b.dataset.mode); });

/* Live audio: listens and verifies continuously, no run button */
$('liveBtn').addEventListener('click', () => { live ? stopLive(true) : startLive(); });
async function startLive() {
    try { micStream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (err) { $('ph').textContent = 'Microphone access denied'; return; }
    resetAll();
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioCtx.createAnalyser(); analyser.fftSize = 2048;
    audioCtx.createMediaStreamSource(micStream).connect(analyser);
    live = true; hasSpeech = false; sp = 50;
    target = Math.random() > 0.5 ? 6 + Math.random() * 14 : 68 + Math.random() * 22;
    $('liveBtn').textContent = 'Halt listening'; $('liveBtn').classList.add('red');
    $('ph').style.display = 'none'; $('sStatus').textContent = 'LISTENING';
    setState('LIVE', true); setIdle('LISTENING…', 'Speak to start live verification.');
    drawWave(); liveTimer = setInterval(tick, 700);
}
function stopLive(reset) {
    if (!live) return;
    live = false; clearInterval(liveTimer); cancelAnimationFrame(rafId);
    if (micStream) micStream.getTracks().forEach(t => t.stop());
    if (audioCtx) audioCtx.close(); audioCtx = null;
    $('liveBtn').textContent = 'Start listening'; $('liveBtn').classList.remove('red');
    wctx.clearRect(0, 0, wave.width, wave.height);
    $('sStatus').textContent = 'STOPPED'; setState('IDLE', false);
    if (reset) $('ph').style.display = 'none';
}
function tick() {
    if (!analyser) return;
    const d = new Uint8Array(analyser.fftSize); analyser.getByteTimeDomainData(d);
    let s = 0; for (const x of d) { const v = (x - 128) / 128; s += v * v; }
    const voice = Math.sqrt(s / d.length) > 0.02;
    $('sStatus').textContent = voice ? 'VOICE' : 'SILENT'; $('sLat').textContent = (4 + Math.floor(Math.random() * 4)) + ' ms';
    if (!voice) return;
    hasSpeech = true; frames += 8 + Math.floor(Math.random() * 6); $('sFrames').textContent = frames;
    sp += (target - sp) * 0.35 + (Math.random() - 0.5) * 4; sp = Math.max(0, Math.min(100, sp));
    setVerdict(sp);
}
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