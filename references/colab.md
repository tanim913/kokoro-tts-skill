# Driving Colab through Claude in Chrome

Everything in the Steps section was checked on a real Colab notebook on 2026-11-19. Typing a long cell with key presses takes far too long, so the cell goes through the X clipboard and one ctrl+v.

## Steps

1. **Tools.** One ToolSearch call: `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__find,mcp__claude-in-chrome__browser_batch,mcp__claude-in-chrome__tabs_close_mcp`.
2. **Tab.** `tabs_context_mcp` (with `createIfEmpty: true`). Use the empty tab it creates for this session, or `tabs_create_mcp`; never the user's own tabs. `navigate` to `notebook_url` from the config (`scripts/config.py get notebook_url`). No config yet: do "First-time setup" below first.
3. **Load, account, runtime.** One JavaScript call, after the page has had a few seconds:
   ```js
   await new Promise(r => setTimeout(r, 6000));
   ({monaco: !!window.monaco,
     account: document.querySelector('a[aria-label*="Google Account"]')?.getAttribute('aria-label'),
     cells: document.querySelectorAll('.cell.code').length,
     runtime: document.querySelector('colab-connect-button')?.shadowRoot?.textContent?.replace(/\s+/g, ' ').trim()})
   ```
   `account` must contain the config's `google_account`. If `account` is empty and the page shows "Sign in", ask the user to sign in to Google in Chrome themselves, then reload. Another account: ask before going on. `runtime` reads "Connect T4", "Connecting", or shows RAM/Disk once connected. Colab often starts connecting by itself when the page opens.
4. **Clipboard.** Bash, in the background: `python3 -I ~/.claude/skills/kokoro-tts/scripts/clip.py <cell file> 120`. It prints `on clipboard: N chars`. A newer clip.py simply takes over the clipboard from an older one, so there's no need to kill old ones (and don't `pkill -f clip.py` from a Bash command line that itself contains "clip.py": it kills its own shell).
5. **Focus, select, paste, verify,** in one `browser_batch`. Focus the editor through Monaco's API rather than by clicking: the page may have scrolled so that a click lands on the old output instead of the code.
   ```js
   const e = window.monaco.editor.getEditors().find(x => x.getDomNode()?.closest('.cell.code'));
   e.getDomNode().scrollIntoView({block: 'center'}); e.focus();
   e.setSelection(e.getModel().getFullModelRange()); e.hasTextFocus()   // must be true
   ```
   then `computer` key `ctrl+v`, then
   ```js
   await new Promise(r => setTimeout(r, 2000));
   window.monaco.editor.getEditors().map(e => e.getModel().getValueLength())
   ```
   The cell's editor must report exactly N. (`monaco.editor.getModels()` also lists hidden models, such as an older version of the cell, so prefer `getEditors()`.) The cell is pure ASCII, so the counts match one to one. If they differ, focus and paste again; never run a partial cell. If the notebook has no code cell, click "+ Code" first.
6. **Run.** Focus the editor again with the JavaScript above (without changing the selection is fine), then `computer` key `ctrl+Return`.
7. **Wait** on the local side (SKILL.md step 4).
8. **Clear and close** (below).

## Reading the cell's output

The output is drawn inside a cross-origin iframe. `get_page_text`, `find`, `read_page` and page JavaScript cannot read it (`get_page_text` returns the whole cell source instead, which is large and useless). So:

- Watch completion from the local side, never by polling the page.
- When the local side stalls or something looks wrong, look once: scroll the output into view and take one scaled screenshot.
  ```js
  document.querySelector('.cell.code .output')?.scrollIntoView({block: 'end'}); 1
  ```
  then `computer` `screenshot` with `scale: 0.6`. The lines to look for are below.

If the notebook is set to "private outputs" (Edit, Notebook settings), outputs are not saved into the notebook file at all. That's a good setting for this use, but don't change it without asking.

What the cell prints, in order: `GPU: Tesla T4`, `KOKORO_START run <run> cell i of n: k files, t to do, delivery <mode>`, some harmless torch warnings (`dropout option adds dropout`, `weight_norm is deprecated`), one `[k/m] <file>: x min audio, y MB, took z s` line per file, then `KOKORO_BATCH_DONE n of m`. On a fresh runtime there are also pip and download progress bars first (Kokoro's weights, about 330 MB).

## Zip delivery: Chrome's save dialog

Chrome either saves downloads straight to ~/Downloads, or, if "Ask where to save each file" is on in its settings, shows a Save dialog that the extension cannot answer; then the user picks a folder and clicks Save. Before running a zip cell, tell the user they may see it ("Chrome may ask where to save `<run>-cellNN.zip`; any folder is fine"). Once you know how their Chrome behaves, record it with `config.py set chrome_asks_where_to_save yes|no` so later runs can say it plainly. `watch.py` looks in ~/Downloads and, every third poll, anywhere under home (4 levels deep, hidden folders skipped) for the zip's unique name, and leaves the zip where the user saved it. Don't change Chrome's download setting.

## Texts that mean trouble

| Seen | Meaning | Do |
|---|---|---|
| `KOKORO_NO_GPU` | runtime has no GPU | quota is out or the runtime type changed; report, stop, resume later |
| "Cannot connect to GPU backend" / "usage limits in Colab" dialog | free GPU quota used up | same; the dialog offers "Connect without GPU": don't, unless the user says so |
| "Runtime disconnected" | runtime gone (idle, quota, or recycled) | resume per SKILL.md step 5 |
| "Warning: This notebook was not authored by Google" | first run of a notebook not created in this account | the notebook is the user's own; if it appears anyway, ask before "Run anyway" |
| "Permit this notebook to access your Google Drive files?" | drive delivery mounting Drive | only with the user's OK for this run; pick the config's `google_account` |
| "...past version of this notebook..." toast | Colab noticed an older saved version | normal; ignore |
| `upload retry` lines | PUT failed, retrying | fine unless `KOKORO_JOB_FAILED` follows |

## Clearing the cell and closing

1. Empty the cell through Monaco (this edits the notebook's contents, not any setting):
   ```js
   const e = window.monaco.editor.getEditors().find(x => x.getDomNode()?.closest('.cell.code'));
   e.executeEdits('kokoro', [{range: e.getModel().getFullModelRange(), text: ''}]); e.getModel().getValueLength()  // 0
   ```
2. Clear the output: `find` "Edit menu", click it, `find` "Clear all outputs", click it.
3. Wait about 10 seconds for Colab to save to Drive, then `tabs_close_mcp`. If it refuses because the page asks to confirm leaving, wait 10 seconds more and try once again; if it still refuses, tell the user the tab is left open with unsaved changes.

Closing the tab does not stop the runtime at once; Colab releases it after a while. When the user is done for the day and quota matters, offer to use Runtime, then "Disconnect and delete runtime" before closing (ask first; it ends the session's installed packages and files).

## First-time setup (no config yet)

Do this only after the user said yes in SKILL.md step 0. It makes one notebook in the signed-in account's Drive (`Colab Notebooks/kokoro-tts.ipynb`) and sets it to a T4 GPU. Tested end to end on 2026-11-19.

1. New tab, `navigate` to `https://colab.research.google.com/#create=true`. With several Google accounts in Chrome, Colab uses the default one; if the user named another, use `https://colab.research.google.com/?authuser=N#create=true` (N is the account's position in Google's account menu, starting at 0).
2. After about 9 seconds, `location.href` contains `/drive/<id>` and the title is "UntitledN.ipynb". Read the account with the JavaScript in Steps, point 3. No account: ask the user to sign in, then start again. The connect button reads "Connect" (no GPU yet).
3. Rename: `find` "Notebook name" (a textbox), triple-click it, ctrl+a, type `kokoro-tts.ipynb`, press Enter. `document.title` becomes "kokoro-tts.ipynb - Colab".
4. GPU: `find` "Runtime menu button", click it; `find` "Change runtime type" and click it. The dialog lists Hardware accelerator radio buttons (CPU, T4 GPU, and paid ones greyed out); take one scaled screenshot to locate "T4 GPU", click it, zoom to confirm it's selected, then click "Save" at the dialog's bottom right. The connect button now reads "Connect T4".
5. Save the settings:
   ```bash
   python3 -I ~/.claude/skills/kokoro-tts/scripts/config.py set notebook_url "<location.href without the #fragment>"
   python3 -I ~/.claude/skills/kokoro-tts/scripts/config.py set google_account "<the account's email>"
   ```
6. Wait about 8 seconds for the save, close the tab, and tell the user what was made: the notebook's name, that it's in their Drive's Colab Notebooks folder, and that it's set to T4 GPU.

If the user already has a notebook they'd like to use, skip all this: save its link and their account with `config.py set`, and check its runtime type shows T4 (Runtime, Change runtime type); ask before changing it.
