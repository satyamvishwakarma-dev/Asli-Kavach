"""Applies the small demo fixes to asli_kavach.html (a backup is saved as asli_kavach.html.bak).
Run once from the project folder:   python patch_page.py
Safe to run again: fixes that are already in the page are skipped."""
import os
import shutil
import sys

PAGE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "asli_kavach.html")

FIXES = [
    ("Use the local Gradio client (works without internet), CDN as backup",
     "const CDN='https://cdn.jsdelivr.net/npm/@gradio/client/dist/index.min.js';",
     "const CDN='./gradio-client.js';   // local copy, works offline\n"
     "const CDN2='https://cdn.jsdelivr.net/npm/@gradio/client/dist/index.min.js';   // backup if the local file is missing", 1),
    ("Fall back to the CDN if the local file cannot load",
     "cl??=await (await import(CDN)).Client.connect(API);",
     "cl??=await (await import(CDN).catch(()=>import(CDN2))).Client.connect(API);", 1),
    ("Video with no face: show 'No face detected' instead of an error",
     "if(typeof r.fake_prob!=='number') throw new Error('no score');",
     "if(r.face_found===false){ setSt('noface'); $('sSt').textContent='Done'; return; }\n"
     "    if(typeof r.fake_prob!=='number') throw new Error('no score');", 1),
    ("Web-pages panel: honest message when web search is unavailable",
     "ls.textContent=S.err;",
     "ls.textContent='Web search is unavailable right now.';", 1),
    ("Mic/camera permission denied or cancelled: friendly message (not 'could not reach the model')",
     "catch(e){ return fail(); }",
     "catch(e){ console.warn(e); $('ph').style.display='flex'; $('ph').innerHTML=svg('ban')+'<span>Permission denied or cancelled</span>'; return; }", 2),
    ("Make sure the microphone audio context is running",
     "an.fftSize=2048; src.connect(an);",
     "ac.resume(); an.fftSize=2048; src.connect(an);", 1),
]

if not os.path.isfile(PAGE):
    sys.exit(f"Cannot find {PAGE}")
text = open(PAGE, encoding="utf-8", newline="").read()
crlf = "\r\n" in text
changed = False
for name, old, new, count in FIXES:
    if new.split("\n")[0] in text:
        print(f"  [ -- ] {name}: already applied")
    elif old in text:
        if text.count(old) != count:
            print(f"  [ !! ] {name}: expected {count} match(es) but found {text.count(old)} - skipped")
            continue
        new_txt = new.replace("\n", "\r\n") if crlf else new
        text = text.replace(old, new_txt)
        changed = True
        print(f"  [ OK ] {name}")
    else:
        print(f"  [ !! ] {name}: the line was not found in your page - skipped")
if changed:
    shutil.copyfile(PAGE, PAGE + ".bak")
    open(PAGE, "w", encoding="utf-8", newline="").write(text)
    print(f"\nSaved. Backup of your original: {PAGE}.bak")
else:
    print("\nNothing to change.")
