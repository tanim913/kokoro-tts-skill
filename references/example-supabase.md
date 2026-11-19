# Example adapter: an app on Supabase Storage

A worked example of the adapter contract in `adapters.md`, for a reading app whose chapters live in a Supabase table and whose audio goes to a private Storage bucket. The same pattern narrated a 46-file novel in two voices. Adapt the table and bucket names to your app.

Assumed schema (yours will differ):

- table `chapters (id uuid, book_id uuid, number int, title text, body text)`, where `body` is plain paragraphs separated by blank lines, with `* * *` for scene breaks;
- private bucket `audio`, files at `<book id>/<chapter id>-<voice>.mp3`;
- table `chapter_audio (chapter_id, voice, path, bytes, duration_s)`, unique on `(chapter_id, voice)`.

The scripts run on your machine with Node 22+ (`node --experimental-strip-types file.mts`), with `SUPABASE_URL`, `SUPABASE_SECRET_KEY` and `SUPABASE_PUBLISHABLE_KEY` in the environment. **The secret key stays in these local scripts.** The cell gets only the publishable key and per-file signed upload URLs; `build_cell.py` refuses to build if a secret key slips in.

## export.mts (input adapter)

Writes `texts.json`, `jobs.json` (with signed URLs, for the cell) and `jobs-local.json` (no URLs, plus chapter ids and storage paths, for recording).

```ts
// usage: export.mts <book id> <chapter numbers, comma list> <out dir>
import { writeFileSync } from "node:fs";
const U = process.env.SUPABASE_URL!, K = process.env.SUPABASE_SECRET_KEY!;
const h = { apikey: K, Authorization: `Bearer ${K}` };
const [BOOK, list, OUT] = process.argv.slice(2);
const want = list.split(",").map(Number);
const chs = (await (await fetch(
  `${U}/rest/v1/chapters?book_id=eq.${BOOK}&select=id,number,title,body&order=number`, { headers: h })).json())
  .filter((c: any) => want.includes(c.number));
const texts: Record<string, string> = {};
for (const c of chs) texts[c.number] = `# ${c.number} | ${c.title}\n\n${c.body}\n`;
const jobs: any[] = [], local: any[] = [];
for (const voice of ["af_heart", "bm_george"]) for (const c of chs) {
  const path = `${BOOK}/${c.id}-${voice}.mp3`;
  const r = await fetch(`${U}/storage/v1/object/upload/sign/audio/${path}`,
    { method: "POST", headers: { ...h, "x-upsert": "true" } });
  const j = await r.json();
  if (!j.url) throw new Error(JSON.stringify(j));
  const out = `${c.number}-${voice}.mp3`;
  jobs.push({ id: String(c.number), voice, out, url: `${U}/storage/v1${j.url}` });
  local.push({ id: String(c.number), voice, out, chapter: c.id, path });
}
writeFileSync(`${OUT}/texts.json`, JSON.stringify(texts));
writeFileSync(`${OUT}/jobs.json`, JSON.stringify(jobs));
writeFileSync(`${OUT}/jobs-local.json`, JSON.stringify(local));
console.log(chs.length, "chapters,", jobs.length, "jobs");
```

## Build

```bash
python3 -I ~/.claude/skills/kokoro-tts/scripts/build_cell.py \
  --texts OUT/texts.json --jobs OUT/jobs.json --delivery put \
  --put-header apikey=$SUPABASE_PUBLISHABLE_KEY \
  --put-header x-upsert=true --put-header cache-control=max-age=3600 \
  --out OUT/run
```

The publishable key is public by design (it ships in the web app). `--title auto` turns `# 20 | The Weighbridge` into "Chapter 20. The Weighbridge."

Supabase signed upload URLs last 2 hours, so for big batches export per cell (about 8 chapters of 2,500 words, both voices, fit one 60,000-character cell).

## check.mts (for watch.py)

```ts
// usage: check.mts <book id> <out dir>   prints the out names whose files exist in storage
import { readFileSync } from "node:fs";
const U = process.env.SUPABASE_URL!, K = process.env.SUPABASE_SECRET_KEY!;
const [BOOK, OUT] = process.argv.slice(2);
const local = JSON.parse(readFileSync(`${OUT}/jobs-local.json`, "utf8"));
const files = await (await fetch(`${U}/storage/v1/object/list/audio`, { method: "POST",
  headers: { apikey: K, Authorization: `Bearer ${K}`, "Content-Type": "application/json" },
  body: JSON.stringify({ prefix: `${BOOK}/`, limit: 1000 }) })).json();
const have = new Set(files.filter((f: any) => Number(f.metadata?.size ?? 0) > 0).map((f: any) => `${BOOK}/${f.name}`));
for (const j of local) if (have.has(j.path)) console.log(j.out);
```

```bash
python3 -I ~/.claude/skills/kokoro-tts/scripts/watch.py OUT/run --check-cmd "node --experimental-strip-types check.mts <book id> OUT"
```

An earlier run's file at the same path counts as present (uploads overwrite with `x-upsert`). When re-narrating, compare each file's `updated_at` with the run's start time instead.

## record.mts (output adapter)

```ts
// usage: record.mts <book id> <out dir>   upserts chapter_audio rows for the files that arrived
import { readFileSync } from "node:fs";
const U = process.env.SUPABASE_URL!, K = process.env.SUPABASE_SECRET_KEY!;
const h = { apikey: K, Authorization: `Bearer ${K}`, "Content-Type": "application/json" };
const [BOOK, OUT] = process.argv.slice(2);
const local = JSON.parse(readFileSync(`${OUT}/jobs-local.json`, "utf8"));
const files = await (await fetch(`${U}/storage/v1/object/list/audio`, { method: "POST", headers: h,
  body: JSON.stringify({ prefix: `${BOOK}/`, limit: 1000 }) })).json();
const size = new Map(files.map((f: any) => [`${BOOK}/${f.name}`, Number(f.metadata?.size ?? 0)]));
const rows = local.filter((j: any) => (size.get(j.path) ?? 0) > 0).map((j: any) => {
  const bytes = size.get(j.path)!;
  return { chapter_id: j.chapter, voice: j.voice, path: j.path, bytes, duration_s: Math.round((bytes * 8) / 48000) };
});
const missing = local.filter((j: any) => !(size.get(j.path) ?? 0)).map((j: any) => j.out);
const r = await fetch(`${U}/rest/v1/chapter_audio?on_conflict=chapter_id,voice`, {
  method: "POST", headers: { ...h, Prefer: "resolution=merge-duplicates,return=minimal" }, body: JSON.stringify(rows) });
console.log("recorded", rows.length, "status", r.status, "| missing:", missing.join(" ") || "none");
```
