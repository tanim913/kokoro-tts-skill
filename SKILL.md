---
name: kokoro-tts
description: Turn text into natural spoken audio (MP3) with Kokoro, an open-source text-to-speech model, on a free Google Colab T4 GPU, so the user's own computer does no work. Builds one self-contained Python cell, opens Google Colab in the user's Chrome (Claude in Chrome), pastes and runs the cell, watches for the files and brings them back. Use this whenever the user wants to make audio from text, narrate a chapter, story, article, book, blog post or notes, turn text to speech (TTS), read something aloud, make an audiobook or a podcast-style reading, or add voice narration to an app or project, even if they don't name Kokoro or Colab.
---

# Kokoro TTS on Colab

Text goes in (files, a folder, or text in the chat); MP3s come out, narrated by Kokoro on a free Colab GPU in the user's own Google account. You do the whole thing: build the cell locally, drive Colab in Chrome, watch for the files from the local side, and tidy up. The user only steps in to sign in to Google, choose voices, approve consents (a download, a Drive mount), and listen.

Everything is in this folder (`~/.claude/skills/kokoro-tts`):

- `scripts/build_cell.py`: inputs to cleaned text to one or more pasteable cells, plus a manifest.
- `scripts/clip.py`: holds a cell on the system clipboard so Chrome can paste it.
- `scripts/watch.py`: waits for the files locally (a downloaded zip, or an adapter's check command).
- `scripts/config.py`: reads and writes the user's local settings (their notebook link and account).
- `scripts/cell_template.py`: the code that runs in Colab. `scripts/selftest.py` tests all of it offline.
- `references/colab.md`: the browser steps, the JavaScript checks, first-time notebook setup, and Colab's error texts. Read it before the first browser step.
- `references/voices.md`: every Kokoro voice, and how to ask the user to choose.
- `references/adapters.md`: how a project plugs in its own export and record steps; `references/example-supabase.md` is a worked example.
- `references/limits.md`: cell size, GPU quota, timing.
- `references/local/` (optional, never published): the user's own project adapters. If it exists, read the file that matches the user's project.

Run the scripts with `python3 -I ~/.claude/skills/kokoro-tts/scripts/<name>.py`. They use only the Python standard library (clip.py needs Tk, which ships with most Pythons; on Debian and Ubuntu it's the `python3-tk` package).

## Defaults

- Voices: af_heart and bm_george (two files per text). Speed 1.0.
- Title line, then 1.2 s of silence; 0.45 s between paragraphs; a scene break ("* * *", "***", "---" and the like) adds 1.6 s; 24 kHz audio; MP3 mono 48 kbps, so duration in seconds = bytes × 8 / 48000.
- Local run folder: `~/kokoro-tts/<run-id>/` with `cells/`, `audio/`, `manifest.json` and `payload.json`. Pass `--out` to put it inside a project instead.
- Notebook and Google account: whatever the user set up, kept in `~/.config/kokoro-tts/config.json` (step 0). Nothing about the user's account lives in this skill.

## Rules that protect the user

- **No secrets in the cell or any web page.** The cell is pasted into Colab, which saves it to Google Drive with its revision history. Only publishable keys and pre-signed URLs go in. `build_cell.py` refuses Supabase secret keys, service-role JWTs, `sk-` keys, GitHub and Slack tokens, private keys and passwords; if it refuses, fix the adapter, never bypass the check. Secret keys stay in local adapter scripts that run on this machine.
- **Never sign in for the user.** Don't type passwords or one-time codes. If Colab shows a sign-in page, ask the user to sign in themselves, then continue.
- **Ask first** before any file download (zip delivery downloads through Chrome), before mounting Drive in Colab (it grants the notebook access to the user's Drive), before creating the notebook or changing its runtime type on first setup, before changing any other Colab or Google setting, and before using a different Google account than the one in the config. One yes covers that action for the current run only.
- **Tell the user, after each run, whether the notebook held private text.** The payload holds the full text, and Drive keeps notebook revisions even after you clear the cell. Say plainly what text went into the notebook.

## Workflow

### 0. Setup: Chrome, Google sign-in, and the notebook

1. Claude in Chrome must be connected. If its tools are missing or don't respond, tell the user to open Chrome with the Claude in Chrome extension connected, and stop.
2. Read the config: `python3 -I scripts/config.py show`. It holds `notebook_url` and `google_account` once set up.
3. **No config yet (first run):** tell the user, before opening anything: "Please make sure you're signed in to Google in Chrome with the account you want to use for Colab. I'll create a notebook called kokoro-tts in that account's Drive and set it to a free T4 GPU. OK?" On a yes, follow "First-time setup" in `references/colab.md`: open `https://colab.research.google.com/#create=true`, read the signed-in account, rename the notebook, set the runtime to T4 GPU, then save both with `config.py set notebook_url <url>` and `config.py set google_account <email>`.
4. **Config present:** open `notebook_url` in a new tab and check the signed-in account matches `google_account`. If Colab shows a sign-in page, ask the user to sign in and say when they're done. If a different account is signed in, ask before going on with it (and update the config if they want to switch).

The notebook can be any notebook in the user's account. If the user already has one they want to use, save its link instead of creating one.

### 1. Settle the inputs and choices

From the request, work out:

- **What to narrate.** Paths to `.txt`/`.md` files, a folder (read recursively, in sorted order), `-` for stdin, `--inline "text"`, or an adapter's `--texts texts.json`. Each text's id (file stem by default, `--id` for a single input) names its files: `<id>-<voice>.mp3`.
- **Voices.** If the caller named them, use them. Otherwise ask the user with AskUserQuestion, following "Asking the user" in `references/voices.md` (default af_heart + bm_george, any Kokoro voice typed in, or an audition first). Don't ask when a project adapter fixes the voices.
- **Title line.** `--title auto` (default) reads the first heading: `# 4 | Name` becomes "Chapter 4. Name.", `# Name` becomes "Name.", no heading means no title. `--title none`, or a template such as `--title "Chapter {n}. {title}."` (fields `{n}`, `{title}`, `{id}`; `{title}` falls back to the file name).
- **Speed and pauses** only if asked: `--speed`, `--pause-title`, `--pause-para`, `--pause-scene`, `--bitrate`.
- **Delivery**, one per run:
  - `zip`: one zip per cell, downloaded through Chrome when the cell ends; `watch.py` unpacks it into the run folder. Needs the user's OK for the download.
  - `drive`: files land in `My Drive/kokoro-tts/<run>/` as each one finishes, and survive a lost runtime. Needs the user's OK to mount Drive (Colab shows a Google consent dialog each new runtime).
  - `put`: a project gives pre-signed upload URLs through an adapter (`--jobs`). Each file uploads the moment it is done. Best for apps; see `references/adapters.md`.

  If the caller didn't choose and no adapter applies, ask the user, putting the consent each one needs in the option text. For files the user wants on this machine, zip is the shortest path; for long jobs on a shaky quota, drive loses least.

Markdown is cleaned for speech: headings become sentences, emphasis and inline code marks go, links keep their text, images, code blocks, bare URLs, HTML and footnotes are dropped, list items and table rows become short sentences, and horizontal rules become scene breaks. `.txt` files are read as plain text (headings and scene breaks still work). `--format markdown|plain` overrides. Check what will be read with `--dry-run` when the input is unusual.

### 2. Build the cells

```bash
python3 -I ~/.claude/skills/kokoro-tts/scripts/build_cell.py <inputs> --delivery zip|drive|put [options]
```

It prints a JSON summary: the run folder, each cell file with its character count, word count, estimated audio minutes and GPU minutes, and any warnings. Cells are packed up to 30,000 characters for zip delivery and 60,000 for put and drive (`--max-cell-chars`); both voices of a text stay in the same cell. Pastes of 250,000 characters are known to work; the limit is about what a lost runtime costs. See `references/limits.md`.

Tell the user, in one or two lines, what's about to happen: how many files, which voices, which delivery, roughly how long. Get the consent the delivery needs now, before opening the browser.

### 3. Run each cell in Colab through Chrome

Follow `references/colab.md`: it has the exact JavaScript for each step. Per cell:

1. Open the session's own **new tab** on the notebook (never the user's tabs), and check the account as in step 0.
2. Start `clip.py <cell> 120` with Bash in the background. It prints the character count N.
3. Focus the code cell's editor **through Monaco's API** (not a click: the page may have scrolled so that a click hits the old output), select all, press ctrl+v (cmd+v on a Mac).
4. Verify the paste: the cell editor's model length must equal N exactly. If not, paste again; never run a partial cell.
5. Press ctrl+Return (cmd+Return on a Mac). Allocating a T4 takes 1 to 2 minutes when cold; a toast about a "past version" of the notebook is normal. A fresh runtime first installs packages and downloads Kokoro (about 330 MB); a warm one starts at once.
6. Drive delivery only: Colab shows "Permit this notebook to access your Google Drive files?" and a Google account window. The user agreed in step 1, so pick the account from the config and allow. If it asks for anything beyond Drive access, stop and ask.
7. Zip delivery only: if Chrome is set to ask where to save downloads, it shows a Save dialog that the extension can't answer. Tell the user before you run: "Chrome may ask where to save `<run>-cellNN.zip`; any folder is fine." `watch.py` finds it wherever they save it under their home folder.

Run cells one after another in the same runtime; paste the next only after the previous one has delivered.

### 4. Watch from the local side

Don't watch with screenshots. Watch where the files land, using Bash in the background (or the Monitor tool) so you're woken when it ends:

- zip: `python3 -I scripts/watch.py <run_dir>` (add `--cells N` to wait for one cell).
- put: `python3 -I scripts/watch.py <run_dir> --check-cmd "<adapter check command>"`.
- drive: every few minutes, list the folder with a Google Drive connector if one is available (find the folder by `title contains '<run>'`, then list its children) and count the `.mp3` files against the manifest. Without a connector, check the Colab output once in a while as below.

The cell prints, in order: `GPU: Tesla T4`, `KOKORO_START ...`, one `[k/m] <file>: x min audio, y MB, took z s` line per file, and last `KOKORO_BATCH_DONE n of m`. Colab draws output in a cross-origin iframe that page text and JavaScript can't read, so don't poll the page. Only when the local side stalls, or the watch times out, look once: scroll the output into view and take one scaled screenshot (`references/colab.md`), then act on what it says.

### 5. When something goes wrong

- **`KOKORO_NO_GPU`**, or Colab says it can't connect to a GPU / usage limits: the free GPU quota is used up for now (it comes back after some hours; Google doesn't publish the schedule). Nothing is lost. Tell the user, close the tab, and offer to resume later. Don't switch the runtime to CPU or change runtime settings without asking.
- **Disconnected / runtime recycled** mid-run (a "Runtime disconnected" banner, or the watch stalls): files already delivered are safe (put and drive deliver each file as it finishes; zip delivers only at the end of a cell, so an unfinished zip cell is lost). Resume:
  - Same runtime still alive: rerun the same cell. The skip list in the runtime (`done_<run>.txt`, or `.kokoro_done.txt` in the Drive folder) skips what's finished.
  - New runtime: drive delivery still skips finished files (its skip list lives in Drive), so rerun the same cell. For zip and put, rebuild with only what's missing: `build_cell.py --resume <run_dir> [--done a.mp3,b.mp3 | --done-file list.txt] [--jobs fresh_jobs.json]` (files already in `<run_dir>/audio` count as done; for put, pass fresh signed URLs if the old ones may have expired, and the adapter's check output as the done list).
- **`KOKORO_JOB_FAILED <file>`** or a `KOKORO_FAILED` list: one file failed (for put, three upload attempts failed). Read the error line, fix the cause, and resume as above.
- **After 3 failed attempts at the same cell**, stop and bring the user the error lines.

### 6. Finish

1. Check every expected file is there and plays: `ffprobe` each MP3 for its duration if ffprobe is installed, or bytes × 8 / 48000.
2. Clear the cell in Colab so the text doesn't sit in the notebook: empty it through Monaco, then Edit, "Clear all outputs" (`references/colab.md`). This edits the notebook's contents, not settings.
3. Wait about 10 seconds for Colab to save, then close the tab you opened. If Chrome refuses because the page wants to confirm leaving, wait and try once more, then tell the user.
4. Report to the user: the files (paths, or Drive folder), durations, any failures; whether the notebook held private text (it held the full text of whatever was narrated; the cell is now cleared, but Drive's revision history of the notebook still has it); and, for drive delivery, offer to download them locally (a download, so ask), or let them play them in Drive.
5. Don't publish or upload the audio anywhere else unless the caller's task says so.

## Calling it from another project or task

Another session only needs to say what to narrate and, optionally, voices and delivery, for example: "Use the kokoro-tts skill to narrate drafts/ch05.md in bm_george, zip delivery." A project with its own storage writes an adapter (export texts and signed URLs, then record what arrived) and passes `--texts`, `--jobs` and `--delivery put`; see `references/adapters.md`.
