#!/usr/bin/env python3
"""Build self-contained Colab cells that narrate text with Kokoro.

Inputs: text or markdown files, folders of them, "-" for stdin, --inline TEXT,
or an adapter's --texts texts.json ({id: text}) with optional --jobs jobs.json.
Writes RUN_DIR/cells/cell-NN.py (paste one per Colab run), RUN_DIR/manifest.json
(no URLs) and RUN_DIR/payload.json (everything, for --resume). Prints a JSON summary.

Run with: python3 -I build_cell.py ...   (stdlib only)
"""
import argparse, base64, datetime, html, json, os, re, sys, zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "cell_template.py"
DEFAULT_VOICES = "af_heart,bm_george"
LANGS = set("abefhijpz")
SCENE = "* * *"
WORDS_PER_AUDIO_MIN = 155       # Kokoro at speed 1.0, measured on narrated chapters
GPU_SPEEDUP = 8                 # audio minutes per GPU minute on a T4, conservative (measured ~12; see references/limits.md)
TEXT_EXT = {".txt", ".md", ".markdown", ".text"}


# ---------- text cleaning ----------

SCENE_LINE = re.compile(r"^\s*([*\-_~=#•·§⁂◆◇]\s*)+$")


def split_front_matter(raw):
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n", raw, re.S)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if v.strip():
            meta[k.strip().lower()] = v.strip().strip("\"'")
    return meta, raw[m.end():]


def parse_heading(lines):
    """Pop the first heading (ATX '# x', numbered '# 4 | Title', or setext). Returns (n, title, rest)."""
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None, None, lines
    line = lines[i].strip()
    text = None
    if re.match(r"^#{1,6}\s+\S", line):
        text, rest = re.sub(r"^#{1,6}\s+|\s+#+\s*$", "", line), lines[i + 1:]
    elif i + 1 < len(lines) and re.match(r"^\s*(=+|-+)\s*$", lines[i + 1]) and line and not SCENE_LINE.match(line):
        text, rest = line, lines[i + 2:]
    if text is None:
        return None, None, lines
    m = re.match(r"^(\d+)\s*\|\s*(.*)$", text)
    if m:
        return int(m.group(1)), m.group(2).strip(), rest
    return None, text.strip(), rest


def inline_md(s):
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)                      # images
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)                   # links
    s = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", s)                  # reference links
    s = re.sub(r"\[\^[^\]]+\]", "", s)                                # footnote refs
    s = re.sub(r"<https?://[^>]+>", "", s)                            # autolinks
    s = re.sub(r"https?://\S+", "", s)                                # bare URLs read badly
    s = re.sub(r"<[^>]+>", "", s)                                     # html tags
    s = re.sub(r"`([^`]*)`", r"\1", s)                                # inline code
    s = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"\2", s)            # bold
    s = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"\1", s)  # *italic*
    s = re.sub(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", r"\1", s)    # _italic_
    s = re.sub(r"~~(.+?)~~", r"\1", s)
    s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!>|~])", r"\1", s)            # escapes
    return html.unescape(s)


def end_sentence(s):
    return s if re.search(r"[.!?:;…\"'”’)]$", s) else s + "."


def clean(raw, markdown=True):
    """Return (n, heading_title, body) where body is paragraphs split by blank lines and SCENE marks."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").replace("﻿", "")
    meta, raw = split_front_matter(raw) if markdown else ({}, raw)
    if markdown:
        raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
        raw = re.sub(r"^(```|~~~).*?^\1[^\n]*$", "", raw, flags=re.S | re.M)   # code blocks are not read
    lines = raw.split("\n")
    n, title, lines = parse_heading(lines)
    if meta.get("title") and not title:
        title = meta["title"]
    # Text with no blank lines but many line breaks: each line is a paragraph.
    if not any(not l.strip() for l in lines) and len([l for l in lines if l.strip()]) > 3:
        lines = [x for l in lines for x in (l, "")]
    out, para = [], []

    def flush():
        if para:
            out.append(" ".join(para))
            para.clear()

    for idx, line in enumerate(lines):
        s = line.strip()
        if not s:
            flush()
            continue
        if SCENE_LINE.match(s) and not (markdown and re.match(r"^[=-]+$", s) and para):
            flush()
            out.append(SCENE)
            continue
        if markdown:
            if re.match(r"^[=-]+$", s) and para:          # setext heading underline
                flush()
                out[-1] = end_sentence(out[-1])
                continue
            if re.match(r"^\[[^\]]+\]:\s*\S", s):          # link / footnote definitions
                continue
            if s.startswith("|"):
                if re.match(r"^\|?[\s:|-]+\|?$", s):
                    continue
                flush()
                out.append(end_sentence(", ".join(c.strip() for c in s.strip("|").split("|") if c.strip())))
                continue
            m = re.match(r"^#{1,6}\s+(.*?)\s*#*$", s)
            if m:
                flush()
                out.append(end_sentence(m.group(1)))
                continue
            s = re.sub(r"^(>\s*)+", "", s)
            m = re.match(r"^([-*+]|\d+[.)])\s+(\[[ xX]\]\s*)?(.*)$", s)
            if m:
                flush()
                para.append(end_sentence(m.group(3)))
                flush()
                continue
        para.append(s)
    flush()
    paras = []
    for p in out:
        if p != SCENE:
            p = re.sub(r"\s+", " ", inline_md(p) if markdown else p).strip()
            if not re.search(r"\w", p):
                continue
        if p == SCENE and (not paras or paras[-1] == SCENE):
            continue
        paras.append(p)
    while paras and paras[-1] == SCENE:
        paras.pop()
    if title and markdown:
        title = inline_md(title).strip()
    return n, title, "\n\n".join(paras)


def make_title(mode, n, heading, ident):
    if mode == "none":
        return None
    if mode == "auto":
        if not heading:
            return None
        return end_sentence(f"Chapter {n}. {heading}" if n is not None else heading)
    fallback = re.sub(r"[_-]+", " ", str(ident)).strip()
    return mode.format(n=n if n is not None else "", title=heading or fallback, id=ident).strip() or None


# ---------- secrets guard ----------

SECRET_PATTERNS = [
    (r"sb_secret_", "a Supabase secret key"),
    (r"\bsk-[A-Za-z0-9_-]{16,}", "an API secret key (sk-...)"),
    (r"\b[sr]k_live_[A-Za-z0-9]{8,}", "a Stripe live secret key"),
    (r"\b(ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}|github_pat_", "a GitHub token"),
    (r"\bxox[abprs]-", "a Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY", "a private key"),
    (r"(?i)(password|passwd|client_secret)\s*[=:]", "a password or client secret"),
]


def jwt_role(token):
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return claims.get("role")
    except Exception:
        return None


def check_secrets(values):
    problems = []
    for where, v in values:
        for pat, what in SECRET_PATTERNS:
            if re.search(pat, v):
                problems.append(f"{where} looks like it holds {what}")
        for tok in re.findall(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", v):
            role = jwt_role(tok)
            if role and role not in ("anon", "authenticated"):
                problems.append(f"{where} holds a JWT with role '{role}' (a service key)")
    return problems


# ---------- building ----------

def slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(s)).strip("-") or "text"


def collect_inputs(args):
    texts = {}  # id -> (raw, markdown?)
    md_default = None if args.format == "auto" else (args.format == "markdown")
    for item in args.inputs:
        if item == "-":
            texts[args.id or "text"] = (sys.stdin.read(), md_default if md_default is not None else True)
            continue
        p = Path(item).expanduser()
        files = sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in TEXT_EXT) if p.is_dir() else [p]
        if not files:
            sys.exit(f"no .txt or .md files in {p}")
        for f in files:
            if not f.exists():
                sys.exit(f"no such file: {f}")
            ident = args.id if (args.id and len(files) == 1 and len(args.inputs) == 1) else slug(f.stem)
            if ident in texts:
                ident = slug(f"{f.parent.name}-{f.stem}")
            md = md_default if md_default is not None else f.suffix.lower() != ".txt"
            texts[ident] = (f.read_text(encoding="utf-8", errors="replace"), md)
    for i, t in enumerate(args.inline or [], 1):
        ident = args.id if (args.id and len(args.inline) == 1) else f"text{i}" if len(args.inline) > 1 else "text"
        texts[ident] = (t, md_default if md_default is not None else True)
    if args.texts:
        data = json.loads(Path(args.texts).expanduser().read_text(encoding="utf-8"))
        for k, v in data.items():
            texts[str(k)] = (v, md_default if md_default is not None else True)
    return texts


def render(run, idx, total, settings, delivery, texts, jobs):
    payload = {"run": run, "cell": idx, "cells": total, "settings": settings, "delivery": delivery,
               "texts": texts, "jobs": jobs}
    blob = base64.b64encode(zlib.compress(json.dumps(payload, separators=(",", ":")).encode(), 9)).decode()
    voices = sorted({j["voice"] for j in jobs})
    words = sum(len(texts[j["id"]].split()) for j in jobs)
    header = (f"kokoro-tts run {run}, cell {idx} of {total}: {len(jobs)} files ({', '.join(voices)}), "
              f"{words} words to narrate, delivery {delivery['mode']}")
    cell = TEMPLATE.read_text().replace("__HEADER__", header).replace("__PAYLOAD__", blob)
    assert cell.isascii(), "cell must be ASCII so the pasted length matches"
    return cell, words


def pack(groups, run, settings, delivery, max_chars):
    """groups: list of (texts_subset, jobs_subset). Greedy pack into cells under max_chars."""
    cells, cur_t, cur_j, warnings = [], {}, [], []
    for t, j in groups:
        trial_t, trial_j = {**cur_t, **t}, cur_j + j
        size = len(render(run, 99, 99, settings, delivery, trial_t, trial_j)[0])
        if size <= max_chars or not cur_j:
            cur_t, cur_j = trial_t, trial_j
            if size > max_chars:
                warnings.append(f"text {list(t)[0]} alone makes a {size}-character cell, over the {max_chars} limit")
        else:
            cells.append((cur_t, cur_j))
            cur_t, cur_j = dict(t), list(j)
            single = len(render(run, 99, 99, settings, delivery, cur_t, cur_j)[0])
            if single > max_chars:
                warnings.append(f"text {list(t)[0]} alone makes a {single}-character cell, over the {max_chars} limit")
    if cur_j:
        cells.append((cur_t, cur_j))
    return cells, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="*", help="text/markdown files, folders, or - for stdin")
    ap.add_argument("--inline", action="append", help="text given directly (repeatable)")
    ap.add_argument("--id", help="id (output name stem) for a single input")
    ap.add_argument("--texts", help="adapter JSON {id: text}")
    ap.add_argument("--jobs", help="adapter JSON [{id, voice, url?, title?, out?, headers?}]; overrides --voices")
    ap.add_argument("--format", choices=["auto", "markdown", "plain"], default="auto",
                    help="auto: .txt is plain, everything else markdown")
    ap.add_argument("--voices", default=DEFAULT_VOICES, help=f"comma list (default {DEFAULT_VOICES})")
    ap.add_argument("--title", default="auto",
                    help="auto (from the first heading; '# 4 | Name' reads 'Chapter 4. Name.'), none, "
                         "or a template with {title} {n} {id}, e.g. 'Chapter {n}. {title}.'")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--pause-title", type=float, default=1.2)
    ap.add_argument("--pause-para", type=float, default=0.45)
    ap.add_argument("--pause-scene", type=float, default=1.6)
    ap.add_argument("--bitrate", default="48k")
    ap.add_argument("--delivery", choices=["zip", "drive", "put"], required=False)
    ap.add_argument("--drive-folder", help="folder under My Drive (default kokoro-tts/RUN)")
    ap.add_argument("--put-header", action="append", default=[], help="NAME=VALUE sent with every PUT (public values only)")
    ap.add_argument("--put-method", default="PUT")
    ap.add_argument("--max-cell-chars", type=int,
                    help="default 30000 for zip (a lost runtime loses the whole cell), 60000 for put and drive")
    ap.add_argument("--allow-cpu", action="store_true", help="narrate even without a GPU (slow)")
    ap.add_argument("--run-id")
    ap.add_argument("--out", help="run folder (default ~/kokoro-tts/RUN)")
    ap.add_argument("--resume", help="rebuild cells for an existing run folder, skipping finished files")
    ap.add_argument("--done", action="append", default=[], help="with --resume: finished output names (comma list, repeatable)")
    ap.add_argument("--done-file", help="with --resume: file listing finished output names, one per line")
    ap.add_argument("--dry-run", action="store_true", help="print the cleaned texts and jobs, write nothing")
    a = ap.parse_args()

    if a.resume:
        run_dir = Path(a.resume).expanduser()
        prev = json.loads((run_dir / "payload.json").read_text())
        run, settings, delivery, texts, jobs = prev["run"], prev["settings"], prev["delivery"], prev["texts"], prev["jobs"]
        finished = {p.name for p in (run_dir / "audio").glob("*.mp3")} if (run_dir / "audio").is_dir() else set()
        for d in a.done:
            finished |= {x.strip() for x in d.split(",") if x.strip()}
        if a.done_file:
            finished |= {x.strip() for x in Path(a.done_file).read_text().split() if x.strip()}
        if a.jobs:  # fresh signed URLs from the adapter
            fresh = {(str(j["id"]), j["voice"]): j for j in json.loads(Path(a.jobs).read_text())}
            for j in jobs:
                if (j["id"], j["voice"]) in fresh and "url" in fresh[(j["id"], j["voice"])]:
                    j["url"] = fresh[(j["id"], j["voice"])]["url"]
        jobs = [j for j in jobs if j["out"] not in finished]
        if not jobs:
            print(json.dumps({"run": run, "run_dir": str(run_dir), "cells": [], "note": "nothing left to narrate"}))
            return
        prefix = "resume-" + datetime.datetime.now().strftime("%H%M%S") + "-"
    else:
        if not a.delivery:
            sys.exit("choose --delivery zip, drive or put")
        raw = collect_inputs(a)
        if not raw:
            sys.exit("no input: give files, a folder, -, --inline or --texts")
        run = a.run_id or "kokoro-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = Path(a.out).expanduser() if a.out else Path.home() / "kokoro-tts" / run
        settings = {"speed": a.speed, "pause_title": a.pause_title, "pause_para": a.pause_para,
                    "pause_scene": a.pause_scene, "bitrate": a.bitrate, "allow_cpu": a.allow_cpu}
        delivery = {"mode": a.delivery}
        if a.delivery == "drive":
            delivery["folder"] = a.drive_folder or f"kokoro-tts/{run}"
        if a.delivery == "put":
            delivery["method"] = a.put_method
            delivery["headers"] = dict(h.split("=", 1) for h in a.put_header)
        texts, titles = {}, {}
        for ident, (body, md) in raw.items():
            n, heading, cleaned = clean(body, markdown=md)
            if not cleaned.strip():
                sys.exit(f"text {ident} is empty after cleaning")
            texts[ident] = cleaned
            titles[ident] = make_title(a.title, n, heading, ident)
        if a.jobs:
            jobs = []
            for j in json.loads(Path(a.jobs).expanduser().read_text()):
                j = {**j, "id": str(j["id"])}
                if j["id"] not in texts:
                    sys.exit(f"job for unknown text id {j['id']}")
                j.setdefault("title", titles[j["id"]])
                j.setdefault("out", f"{slug(j['id'])}-{j['voice']}.mp3")
                jobs.append(j)
        else:
            voices = [v.strip() for v in a.voices.split(",") if v.strip()]
            jobs = [{"id": i, "voice": v, "title": titles[i], "out": f"{slug(i)}-{v}.mp3"} for i in texts for v in voices]
        if a.delivery == "put" and any("url" not in j for j in jobs):
            sys.exit("--delivery put needs a url in every job (give --jobs from your adapter)")
        prefix = ""

    for j in jobs:
        if j["voice"][:1] not in LANGS:
            sys.exit(f"unknown voice {j['voice']}: the first letter must be one of {''.join(sorted(LANGS))}")
    outs = [j["out"] for j in jobs]
    if len(outs) != len(set(outs)):
        sys.exit("two jobs write the same output name")
    problems = check_secrets([("a PUT header", f"{k}={v}") for k, v in delivery.get("headers", {}).items()]
                             + [(f"the url of {j['out']}", j.get("url", "")) for j in jobs]
                             + [(f"headers of {j['out']}", json.dumps(j.get("headers", {}))) for j in jobs])
    if problems:
        sys.exit("refusing to build: " + "; ".join(sorted(set(problems))) +
                 ". Only publishable keys and signed URLs may go into a Colab cell.")

    if a.dry_run:
        print(json.dumps({"texts": texts, "jobs": [{k: v for k, v in j.items() if k != "url"} for j in jobs]},
                         indent=1, ensure_ascii=False))
        return

    if not a.max_cell_chars:
        a.max_cell_chars = 30000 if delivery["mode"] == "zip" else 60000
    order = list(dict.fromkeys(j["id"] for j in jobs))
    groups = [({i: texts[i]}, [j for j in jobs if j["id"] == i]) for i in order]
    packed, warnings = pack(groups, run, settings, delivery, a.max_cell_chars)
    # A text too big for one cell with all its voices: give each voice its own cell.
    if any(len(cj) > 1 and len(render(run, 99, 99, settings, delivery, ct, cj)[0]) > a.max_cell_chars for ct, cj in packed):
        groups = [({j["id"]: texts[j["id"]]}, [j]) for j in jobs]
        packed, warnings = pack(groups, run, settings, delivery, a.max_cell_chars)

    (run_dir / "cells").mkdir(parents=True, exist_ok=True)
    (run_dir / "audio").mkdir(exist_ok=True)
    total = len(packed)
    cells_info = []
    for idx, (ct, cj) in enumerate(packed, 1):
        cell, words = render(run, idx, total, settings, delivery, ct, cj)
        path = run_dir / "cells" / f"{prefix}cell-{idx:02d}.py"
        path.write_text(cell)
        audio_min = words / WORDS_PER_AUDIO_MIN / settings["speed"]
        cells_info.append({"file": str(path), "chars": len(cell), "files": [j["out"] for j in cj],
                           "words": words, "est_audio_min": round(audio_min, 1),
                           "est_gpu_min": round(audio_min / GPU_SPEEDUP + 1, 1),
                           "zip_name": f"{run}-cell{idx:02d}.zip" if delivery["mode"] == "zip" else None})
    manifest = {"run": run, "created": datetime.datetime.now().isoformat(timespec="seconds"),
                "delivery": {k: v for k, v in delivery.items() if k != "headers"},
                "settings": settings, "cells": cells_info,
                "jobs": [{k: v for k, v in j.items() if k not in ("url", "headers")} for j in jobs]}
    if not a.resume:
        (run_dir / "payload.json").write_text(json.dumps({"run": run, "settings": settings, "delivery": delivery,
                                                          "texts": texts, "jobs": jobs}))
    mname = "manifest.json" if not a.resume else f"manifest-{prefix.rstrip('-')}.json"
    (run_dir / mname).write_text(json.dumps(manifest, indent=1))
    print(json.dumps({"run": run, "run_dir": str(run_dir), "manifest": str(run_dir / mname),
                      "delivery": delivery["mode"], "files": len(jobs), "warnings": warnings,
                      "cells": [{k: c[k] for k in ("file", "chars", "words", "est_audio_min", "est_gpu_min", "zip_name")}
                                for c in cells_info]}, indent=1))


if __name__ == "__main__":
    main()
