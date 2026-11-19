# __HEADER__
# Made by the kokoro-tts skill. Rerunning this cell skips files it already delivered.
import base64, json, os, re, shutil, subprocess, sys, time, zlib, importlib.util, urllib.request

P = json.loads(zlib.decompress(base64.b64decode("__PAYLOAD__")))
RUN, CELL, S, D = P["run"], P["cell"], P["settings"], P["delivery"]
WORK = "/content" if os.path.isdir("/content") else os.getcwd()


def _install():
    if not (shutil.which("espeak-ng") and shutil.which("ffmpeg")):
        subprocess.run("apt-get -qq -y install espeak-ng ffmpeg > /dev/null", shell=True, check=True)
    pkgs = [p for mod, p in (("kokoro", "kokoro>=0.9.4"), ("soundfile", "soundfile")) if importlib.util.find_spec(mod) is None]
    langs = {j["voice"][0] for j in P["jobs"]}
    if "j" in langs and importlib.util.find_spec("fugashi") is None:
        pkgs.append("misaki[ja]")
    if "z" in langs and importlib.util.find_spec("pypinyin") is None:
        pkgs.append("misaki[zh]")
    if pkgs:
        subprocess.run([sys.executable, "-m", "pip", "-q", "install", *pkgs], check=True)


def _main():
    _install()
    import numpy as np, soundfile as sf, torch
    from kokoro import KPipeline

    gpu = torch.cuda.is_available()
    print("GPU:", torch.cuda.get_device_name(0) if gpu else "none", flush=True)
    if not gpu and not S.get("allow_cpu"):
        print("KOKORO_NO_GPU this runtime has no GPU (free quota used up, or the runtime type is not T4). Nothing was narrated.", flush=True)
        return None

    mode = D["mode"]
    if mode == "drive":
        from google.colab import drive
        if not os.path.ismount("/content/drive"):
            drive.mount("/content/drive")
        outdir = os.path.join("/content/drive/MyDrive", D["folder"])
        donefile = os.path.join(outdir, ".kokoro_done.txt")
    else:
        outdir = os.path.join(WORK, "kokoro_out", RUN)
        donefile = os.path.join(WORK, "kokoro_out", f"done_{RUN}.txt")
    os.makedirs(outdir, exist_ok=True)
    done = set(open(donefile).read().split()) if os.path.exists(donefile) else set()

    SR = 24000
    silence = lambda sec: np.zeros(int(SR * float(sec)), dtype=np.float32)
    pipes = {}

    def speak(pipe, voice, text):
        parts = []
        for _, _, a in pipe(text, voice=voice, speed=float(S["speed"])):
            if a is not None:
                parts.append(a.cpu().numpy() if hasattr(a, "cpu") else np.asarray(a, dtype=np.float32))
        return np.concatenate(parts) if parts else silence(0.1)

    def deliver(job, path):
        if mode == "drive":
            shutil.copyfile(path, os.path.join(outdir, job["out"]))
        elif mode == "zip":
            shutil.move(path, os.path.join(outdir, job["out"]))
        else:
            data = open(path, "rb").read()
            headers = {"content-type": "audio/mpeg", **D.get("headers", {}), **job.get("headers", {})}
            for attempt in range(3):
                try:
                    req = urllib.request.Request(job["url"], data=data, method=D.get("method", "PUT"), headers=headers)
                    urllib.request.urlopen(req, timeout=180).read()
                    break
                except Exception as e:
                    body = e.read()[:200] if hasattr(e, "read") else b""
                    print(f"upload retry {attempt + 1} for {job['out']}: {e} {body!r}", flush=True)
                    time.sleep(5 * (attempt + 1))
            else:
                raise RuntimeError("upload failed 3 times")
            os.remove(path)

    jobs = P["jobs"]
    todo = [j for j in jobs if j["out"] not in done]
    print(f"KOKORO_START run {RUN} cell {CELL} of {P['cells']}: {len(jobs)} files, {len(todo)} to do, delivery {mode}", flush=True)
    failed = []
    for k, job in enumerate(jobs, 1):
        if job["out"] in done:
            continue
        t0 = time.time()
        try:
            lang = job["voice"][0]
            if lang not in pipes:
                pipes[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
            pipe, voice = pipes[lang], job["voice"]
            pieces = []
            if job.get("title"):
                pieces += [speak(pipe, voice, job["title"]), silence(S["pause_title"])]
            for para in [p.strip() for p in re.split(r"\n\s*\n", P["texts"][job["id"]]) if p.strip()]:
                if para == "* * *":
                    pieces.append(silence(S["pause_scene"]))  # added after the paragraph pause, as in the original pipeline
                    continue
                pieces += [speak(pipe, voice, para), silence(S["pause_para"])]
            audio = np.concatenate(pieces)
            wav, mp3 = os.path.join(WORK, "kokoro_tmp.wav"), os.path.join(WORK, "kokoro_tmp.mp3")
            sf.write(wav, audio, SR)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-ac", "1", "-b:a", S["bitrate"], mp3], check=True)
            size = os.path.getsize(mp3)
            deliver(job, mp3)
        except Exception as e:
            failed.append(job["out"])
            print(f"KOKORO_JOB_FAILED {job['out']}: {type(e).__name__}: {e}", flush=True)
            continue
        done.add(job["out"])
        with open(donefile, "w") as f:
            f.write("\n".join(sorted(done)))
        print(f"[{k}/{len(jobs)}] {job['out']}: {len(audio) / SR / 60:.1f} min audio, {size / 1e6:.2f} MB, took {time.time() - t0:.0f} s", flush=True)

    mine = [j["out"] for j in jobs if j["out"] in done]
    if mode == "zip" and mine:
        import zipfile
        zpath = os.path.join(WORK, f"{RUN}-cell{CELL:02d}.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
            for name in mine:
                z.write(os.path.join(outdir, name), name)
        try:
            from google.colab import files
            files.download(zpath)
        except ImportError:
            print("zip ready (not in Colab, so no download):", zpath, flush=True)
    if failed:
        print("KOKORO_FAILED", " ".join(failed), flush=True)
    return len(mine)


_n = _main()
if _n is not None:
    print("KOKORO_BATCH_DONE", _n, "of", len(P["jobs"]), flush=True)
