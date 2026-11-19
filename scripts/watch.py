#!/usr/bin/env python3
"""Watch for a run's audio on the local side and report progress. No screenshots needed.

    python3 -I watch.py RUN_DIR [--cells 1,2] [--downloads ~/Downloads]
                        [--check-cmd "CMD"] [--interval 20] [--stall-minutes 15] [--timeout-minutes N]

zip delivery:  waits for RUN-cellNN*.zip in ~/Downloads, or anywhere under home if Chrome asked where to save, waits until its size is steady,
               extracts the expected .mp3 files into RUN_DIR/audio, and leaves the zip where it was saved.
put delivery:  runs --check-cmd every interval; it must print the output names that have arrived
               (one per line, e.g. from an adapter that lists storage). Lines that are not names are ignored.
drive delivery: no local view. Poll the Drive folder with the Google Drive connector instead
               (see SKILL.md). --check-cmd works here too if you have a command that lists the folder.

Last line printed, and exit code:
    KOKORO_LOCAL_DONE n of m     0  every expected file arrived
    KOKORO_LOCAL_PARTIAL n of m  2  all zips arrived but some files are missing (failed in Colab)
    KOKORO_STALLED ...           3  nothing new for --stall-minutes (put/drive), or --timeout-minutes passed
"""
import argparse, json, os, shlex, shutil, subprocess, sys, time, zipfile
from pathlib import Path


def search_home(stem, depth=4):
    """Find stem*.zip anywhere under home (not hidden folders), at most `depth` levels down."""
    home = Path.home()
    hits = []
    for root, dirs, files in os.walk(home):
        level = len(Path(root).relative_to(home).parts)
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "snap", "kokoro-tts")] if level < depth else []
        hits += [Path(root) / f for f in files if f.startswith(stem) and f.endswith(".zip")]
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--manifest", help="manifest file (default RUN_DIR/manifest.json)")
    ap.add_argument("--cells", help="only these cell numbers (comma list)")
    ap.add_argument("--downloads", action="append", default=[str(Path.home() / "Downloads")],
                    help="folder to look in first (repeatable); home is searched too, to depth 4")
    ap.add_argument("--check-cmd")
    ap.add_argument("--interval", type=float, default=20)
    ap.add_argument("--stall-minutes", type=float, default=15)
    ap.add_argument("--timeout-minutes", type=float)
    a = ap.parse_args()

    run_dir = Path(a.run_dir).expanduser()
    m = json.loads(Path(a.manifest or run_dir / "manifest.json").read_text())
    cells = m["cells"]
    if a.cells:
        want = {int(x) for x in a.cells.split(",")}
        cells = [c for i, c in enumerate(cells, 1) if i in want]
    expected = [f for c in cells for f in c["files"]]
    audio = run_dir / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    mode = m["delivery"]["mode"]
    est = sum(c["est_gpu_min"] for c in cells)
    timeout = a.timeout_minutes or (est * 2 + 15 if mode == "zip" else None)
    print(f"watching {len(expected)} files ({mode}); estimated GPU time {est:.0f} min"
          + (f"; timeout {timeout:.0f} min" if timeout else ""), flush=True)

    start = last_change = time.time()
    have, sizes, zips_seen = set(), {}, set()
    polls = -1
    while True:
        polls += 1
        if mode == "zip":
            for c in cells:
                if c["zip_name"] in zips_seen:
                    continue
                stem = c["zip_name"][:-4]
                found = [p for d in a.downloads for p in Path(d).expanduser().glob(stem + "*.zip")]
                if not found and polls % 3 == 0:   # Chrome may ask where to save: look around home too
                    found = search_home(stem)
                found = sorted(found, key=lambda p: p.stat().st_mtime)
                if not found:
                    continue
                z = found[-1]
                size = z.stat().st_size
                if sizes.get(z) != size or Path(str(z) + ".crdownload").exists():
                    sizes[z] = size
                    continue
                dest = run_dir / "incoming" / z.stem
                dest.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(z) as zf:
                    for name in zf.namelist():
                        if name in c["files"]:
                            zf.extract(name, dest)
                            shutil.move(str(dest / name), audio / name)
                zips_seen.add(c["zip_name"])
                print(f"got {z} (left where it was saved)", flush=True)
        elif a.check_cmd:
            try:
                res = subprocess.run(a.check_cmd if isinstance(a.check_cmd, list) else shlex.split(a.check_cmd),
                                     capture_output=True, text=True, timeout=120)
                arrived = {Path(l.strip()).name for l in res.stdout.splitlines() if l.strip()}
                have |= arrived & set(expected)
            except Exception as e:
                print("check failed:", e, flush=True)
        if mode == "zip":
            now = {f for f in expected if (audio / f).exists()}
        else:
            now = have | {f for f in expected if (audio / f).exists()}
        if len(now) != len(have) or now != have:
            new = sorted(now - have)
            for i, f in enumerate(new, len(have) + 1):
                print(f"arrived {f} ({i}/{len(expected)})", flush=True)
            have = now
            last_change = time.time()
        if len(have) == len(expected):
            print(f"KOKORO_LOCAL_DONE {len(have)} of {len(expected)}", flush=True)
            return 0
        if mode == "zip" and len(zips_seen) == len(cells):
            missing = sorted(set(expected) - have)
            print("missing:", " ".join(missing), flush=True)
            print(f"KOKORO_LOCAL_PARTIAL {len(have)} of {len(expected)}", flush=True)
            return 2
        idle = (time.time() - last_change) / 60
        if mode != "zip" and idle > a.stall_minutes:
            print(f"KOKORO_STALLED nothing new for {idle:.0f} min ({len(have)} of {len(expected)}). Check the Colab tab.", flush=True)
            return 3
        if timeout and (time.time() - start) / 60 > timeout:
            print(f"KOKORO_STALLED timeout after {timeout:.0f} min ({len(have)} of {len(expected)}). Check the Colab tab.", flush=True)
            return 3
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
