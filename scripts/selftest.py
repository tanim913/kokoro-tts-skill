#!/usr/bin/env python3
"""Offline self-test: builds cells from sample text and runs them locally with stand-ins for
kokoro, torch and soundfile (a tone per word instead of speech). Needs numpy and ffmpeg.
Checks: markdown cleaning, titles, pauses, scene breaks, zip delivery, skip list on rerun,
PUT delivery with retries, the no-GPU stop, cell splitting and the secrets guard.

    python3 -I selftest.py            # prints PASS/FAIL lines, exit 1 on any failure
"""
import http.server, json, os, subprocess, sys, tempfile, threading, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = [sys.executable, "-I", str(HERE / "build_cell.py")]
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""), flush=True)
    fails += not ok


STUBS = {
    "kokoro/__init__.py": '''
import numpy as np
CALLS = []
class KPipeline:
    def __init__(self, lang_code, repo_id=None):
        self.lang = lang_code
    def __call__(self, text, voice, speed=1.0):
        CALLS.append((self.lang, voice, text))
        n = int(24000 * 0.05 * max(1, len(text.split())) / speed)
        yield None, None, (0.1 * np.sin(np.arange(n) / 10)).astype(np.float32)
''',
    "torch/__init__.py": '''
import os
class cuda:
    @staticmethod
    def is_available(): return os.environ.get("FAKE_GPU", "1") == "1"
    @staticmethod
    def get_device_name(i): return "Fake T4"
''',
    "soundfile/__init__.py": '''
import wave, numpy as np
def write(path, audio, sr):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
''',
}

SAMPLE_MD = """---
title: Front Matter Title
---
# The Lantern Room

It was **late** when the [ferry](https://example.com) came in, and *nobody* waited at the dock.

- First item
- Second item with `code`

```python
print("never read aloud")
```

* * *

> A quoted line.

| Name | Role |
|------|------|
| Ana  | Keeper |

Visit https://example.com for more.[^1]

[^1]: A footnote.
"""

SAMPLE_TXT = "# 7 | The Crossing\n\nFirst paragraph here.\n\n* * *\n\nSecond paragraph after the break.\n"


def main():
    tmp = Path(tempfile.mkdtemp(prefix="kokoro-selftest-"))
    stubs = tmp / "stubs"
    for rel, code in STUBS.items():
        (stubs / rel).parent.mkdir(parents=True, exist_ok=True)
        (stubs / rel).write_text(code)
    fakebin = tmp / "bin"
    fakebin.mkdir()
    (fakebin / "espeak-ng").write_text("#!/bin/sh\nexit 0\n")
    (fakebin / "espeak-ng").chmod(0o755)
    env = {**os.environ, "PYTHONPATH": str(stubs), "PATH": f"{fakebin}:{os.environ['PATH']}"}
    (tmp / "in").mkdir()
    (tmp / "in" / "story.md").write_text(SAMPLE_MD)
    (tmp / "in" / "ch07.txt").write_text(SAMPLE_TXT)

    # 1. cleaning
    dry = json.loads(subprocess.run(BUILD + [str(tmp / "in"), "--delivery", "zip", "--dry-run"],
                                    capture_output=True, text=True, check=True).stdout)
    story, ch = dry["texts"]["story"], dry["texts"]["ch07"]
    check("markdown: emphasis, links, code, urls, footnotes removed",
          all(x not in story for x in ("**", "](", "`", "never read aloud", "http", "[^1]", "footnote")), story)
    check("markdown: list items become paragraphs", "First item.\n\nSecond item with code" in story or
          "First item\n\nSecond item with code" in story, story)
    check("markdown: table row read as a list", "Ana, Keeper." in story, story)
    check("scene break kept", "\n\n* * *\n\n" in story and "\n\n* * *\n\n" in ch)
    titles = {j["id"]: j["title"] for j in dry["jobs"]}
    check("title from heading", titles["story"] == "The Lantern Room.", titles)
    check("numbered heading '# 7 | Title'", titles["ch07"] == "Chapter 7. The Crossing.", titles)
    check("two default voices per text", len(dry["jobs"]) == 4)

    # 2. zip run, then rerun skips
    out = json.loads(subprocess.run(BUILD + [str(tmp / "in"), "--delivery", "zip", "--run-id", "t1",
                                             "--out", str(tmp / "run1")], capture_output=True, text=True, check=True).stdout)
    cell = out["cells"][0]["file"]
    work = tmp / "colab"
    work.mkdir()
    r = subprocess.run([sys.executable, cell], cwd=work, env=env, capture_output=True, text=True)
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-500:]
    check("zip run ends with KOKORO_BATCH_DONE 4 of 4", last == "KOKORO_BATCH_DONE 4 of 4", last + r.stderr[-300:])
    z = work / "t1-cell01.zip"
    check("zip holds the four mp3s", z.exists() and len(zipfile.ZipFile(z).namelist()) == 4)
    r2 = subprocess.run([sys.executable, cell], cwd=work, env=env, capture_output=True, text=True)
    check("rerun skips finished files", "4 files, 0 to do" in r2.stdout, r2.stdout[-300:])

    # 3. watch.py picks up the zip
    dl = tmp / "Downloads"
    dl.mkdir()
    (dl / z.name).write_bytes(z.read_bytes())
    w = subprocess.run([sys.executable, "-I", str(HERE / "watch.py"), str(tmp / "run1"), "--downloads", str(dl),
                        "--interval", "0.2"], capture_output=True, text=True, timeout=60)
    check("watch.py extracts the zip", w.returncode == 0 and len(list((tmp / "run1" / "audio").glob("*.mp3"))) == 4,
          w.stdout[-300:])

    # 4. duration: title + pauses + scene break
    mp3 = tmp / "run1" / "audio" / "ch07-af_heart.mp3"
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
                               capture_output=True, text=True).stdout or 0)
    # words: title 4, para 3, para 5 -> 12 * 0.05 = 0.6 s speech; pauses 1.2 + 0.45 + 1.6 + 0.45 = 3.7
    check("pauses: title 1.2, paragraph 0.45, scene 1.6", abs(dur - 4.3) < 0.15, f"{dur:.2f} s")

    # 5. PUT delivery with one failure then success
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_PUT(self):
            n = int(self.headers["content-length"])
            self.rfile.read(n)
            hits.append((self.path, self.headers.get("apikey"), n))
            code = 500 if len(hits) == 1 else 200
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    (tmp / "texts.json").write_text(json.dumps({"7": SAMPLE_TXT}))
    (tmp / "jobs.json").write_text(json.dumps([{"id": 7, "voice": "bm_george", "url": f"{base}/up/7-george?token=x"}]))
    out = json.loads(subprocess.run(BUILD + ["--texts", str(tmp / "texts.json"), "--jobs", str(tmp / "jobs.json"),
                                             "--delivery", "put", "--put-header", "apikey=sb_publishable_abc",
                                             "--run-id", "t2", "--out", str(tmp / "run2")],
                                    capture_output=True, text=True, check=True).stdout)
    work2 = tmp / "colab2"
    work2.mkdir()
    r = subprocess.run([sys.executable, out["cells"][0]["file"]], cwd=work2, env=env, capture_output=True, text=True, timeout=120)
    check("PUT retries after a 500 and delivers", r.stdout.strip().endswith("KOKORO_BATCH_DONE 1 of 1") and len(hits) == 2
          and hits[-1][1] == "sb_publishable_abc", r.stdout[-400:] + r.stderr[-300:])
    srv.shutdown()

    # 6. no GPU
    r = subprocess.run([sys.executable, cell], cwd=tmp, env={**env, "FAKE_GPU": "0"}, capture_output=True, text=True)
    check("no GPU stops with KOKORO_NO_GPU", "KOKORO_NO_GPU" in r.stdout and "BATCH_DONE" not in r.stdout, r.stdout[-300:])

    # 7. secrets guard
    for bad in ("apikey=sb_secret_abcdef123", "authorization=Bearer sk-abcdefghijklmnop1234"):
        r = subprocess.run(BUILD + ["--texts", str(tmp / "texts.json"), "--jobs", str(tmp / "jobs.json"), "--delivery", "put",
                                    "--put-header", bad, "--out", str(tmp / "run3")], capture_output=True, text=True)
        check(f"refuses secret header {bad.split('=')[0]}", r.returncode != 0 and "refusing" in r.stderr, r.stderr[-200:])

    # 8. splitting
    big = tmp / "big"
    big.mkdir()
    import random
    rnd = random.Random(1)
    words = [f"w{rnd.randrange(10**6)}" for _ in range(30000)]
    for i in range(4):
        (big / f"part{i}.txt").write_text(" ".join(words[i * 7000:(i + 1) * 7000]))
    out = json.loads(subprocess.run(BUILD + [str(big), "--delivery", "zip", "--max-cell-chars", "60000", "--out",
                                             str(tmp / "run4")], capture_output=True, text=True, check=True).stdout)
    sizes = [c["chars"] for c in out["cells"]]
    check("splits into several cells under the limit", len(sizes) > 1 and max(sizes) <= 60000, sizes)

    # 9. resume
    (tmp / "run4" / "audio" / "part0-af_heart.mp3").write_bytes(b"x")
    out = json.loads(subprocess.run(BUILD + ["--resume", str(tmp / "run4"), "--done", "part0-bm_george.mp3"],
                                    capture_output=True, text=True, check=True).stdout)
    left = sum(len(json.loads(Path(out["manifest"]).read_text())["cells"][i]["files"]) for i in range(len(out["cells"])))
    check("resume skips finished files", left == 6, left)

    print("ALL PASS" if not fails else f"{fails} FAILED", "| workdir", tmp)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
