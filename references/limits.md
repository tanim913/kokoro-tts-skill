# Limits: cell size, time and GPU quota

## Cell size (measured 2026-11-19)

Pasting is not the bottleneck. On a real Colab notebook (2026-11-19), cells of 60,000, 120,000 and 250,000 characters each pasted with one ctrl+v, and Monaco's model length matched exactly every time. Earlier production runs used cells of 11K to 32K characters (about 4 chapters of 2,500 words, both voices), narrating a 46-file novel.

The text is zlib-compressed and base64-encoded, so a cell holds about 3 characters of text per character of cell: a 30,000-character cell carries about 11,000 words, a 60,000-character cell about 22,000.

What actually limits a cell is how much you lose if the runtime goes away in the middle:

- **put and drive** deliver each file the moment it's done, so a big cell costs nothing extra on failure. Default limit 60,000 characters.
- **zip** delivers only when the whole cell ends; a lost runtime loses the cell's finished files too. Default limit 30,000 characters.

Override with `--max-cell-chars`. Up to 250,000 is known to paste; beyond that, untested. Both voices of a text stay in one cell; a text too big for one cell with all its voices gets one cell per voice, and a single text over the limit gets a cell of its own with a warning (it still pastes fine up to 250K).

## Time

- Runtime allocation: 1 to 2 minutes when cold. Colab often starts connecting when the notebook opens.
- First run on a fresh runtime: apt and pip installs plus Kokoro's weights (about 330 MB), 1 to 3 minutes. A warm runtime skips all of it.
- Narration on a T4: measured about 12 minutes of audio per GPU minute with a warm model (a 70-second file took 6 seconds, MP3 encoding included). Chapters of 2,500 words (about 17 minutes of audio) have taken "a few minutes" per voice in production. `build_cell.py` estimates with a conservative 8x, plus a minute.
- Speech rate: about 155 words per minute of audio at speed 1.0. MP3 at 48 kbps mono is 360 KB per minute (6 MB for a 17-minute chapter).

## Free GPU quota

Colab's free tier gives a T4 for a limited, unpublished amount of time per day, and it varies. When it runs out, a new runtime can't get a GPU: the cell prints `KOKORO_NO_GPU`, or Colab shows a "cannot connect to GPU backend / usage limits" dialog. It comes back after some hours. Nothing in the cell is lost: rerun later (drive and same-runtime reruns skip finished files; otherwise use `build_cell.py --resume`).

Idle runtimes are also recycled after a while (roughly 90 minutes without browser activity, up to about 12 hours at most). Keep the Colab tab open while a cell runs; close it after.

Ways to stretch the quota: narrate one voice first and the second later; keep zip cells small; don't leave a runtime connected when done (see colab.md, "Clearing the cell and closing").

## Storage

MP3 at 48 kbps mono is about 6 MB per 17-minute chapter. If the files go to a free storage plan, check its storage and monthly download limits: every play downloads the file again.
