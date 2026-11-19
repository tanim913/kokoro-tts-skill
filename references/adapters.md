# Input and output adapters

The core skill knows nothing about any project. A project that keeps its text in a database and its audio in cloud storage plugs in with two small local scripts, an **export** and a **record**, plus optionally a **check**. They run on this machine, so they may use the project's secret key; the cell never sees it.

```
export  (local, may use secrets)  ->  texts.json + jobs.json (signed URLs, no secrets)
build_cell.py --texts --jobs --delivery put --put-header apikey=<publishable key>
Colab cell  ->  PUT each MP3 to its signed URL the moment it is done
check   (local)  ->  prints the output names that have arrived   (watch.py --check-cmd)
record  (local, may use secrets)  ->  writes rows that tell the app the audio exists
```

## texts.json (input adapter output)

```json
{"20": "# 20 | The Weighbridge\n\nFirst paragraph...\n\n* * *\n\nNext scene...", "21": "..."}
```

- Keys are text ids (strings). Values are the text: plain paragraphs separated by blank lines, `* * *` for scene breaks. Markdown is fine too; it is cleaned unless `--format plain`.
- A first line `# <n> | <title>` gives the title line "Chapter n. Title." with `--title auto`, or feeds `{n}` and `{title}` to a `--title` template.

## jobs.json (input adapter output)

```json
[{"id": "20", "voice": "bm_george", "url": "https://.../object/upload/sign/audio/<path>?token=...",
  "out": "20-bm_george.mp3", "title": "optional override", "headers": {"optional": "per-job header"}}]
```

- `id` must match a key in texts.json. `voice` is any Kokoro voice. `url` is a pre-signed upload URL (required for `--delivery put`).
- `out` is the file's name in the run (and in the done list); default `<id>-<voice>.mp3`. Keep extra fields you need for recording (chapter ids, storage paths) in a separate local file; anything in jobs.json goes into the cell except `url`-less local bookkeeping you strip yourself.
- Headers common to all uploads go on the command line: `--put-header apikey=<publishable> --put-header x-upsert=true`. Content type `audio/mpeg` is sent by default. `--put-method POST` if the storage wants POST.

Signed URLs usually expire (Supabase upload URLs after 2 hours). For long runs, sign per cell, and on resume pass fresh `--jobs` with `--resume`.

## check (optional, for watching)

A command that prints the `out` names (or paths ending in them) that have arrived, one per line. `watch.py --check-cmd "<command>"` runs it every 20 seconds and reports progress, then `KOKORO_LOCAL_DONE`, or `KOKORO_STALLED` after 15 quiet minutes.

## record (output adapter)

After the watch ends, the record step tells the app what exists: for example, list the storage folder, read each file's size, and upsert a row per file with its duration (`bytes * 8 / 48000` for 48 kbps CBR). Run it even after a partial run; it should record only what arrived and print what's missing.

## Without storage

For zip and drive delivery no adapter is needed: pass files or `--inline` text. An adapter can still produce `texts.json` (for example, exporting chapters from a database) and let the files come back as a zip.

See `example-supabase.md` for a complete worked example. Keep the user's own adapters in `references/local/` (not published): one file per project, saying where its export, check and record scripts live and how to run them.
