#!/usr/bin/env python3
"""The user's local kokoro-tts settings, kept outside the skill so the skill holds nothing personal.

    python3 -I config.py show              # prints the config as JSON ({} before first setup)
    python3 -I config.py get KEY           # prints one value, or nothing
    python3 -I config.py set KEY VALUE     # e.g. notebook_url, google_account
    python3 -I config.py path              # where the file lives

File: $KOKORO_TTS_CONFIG, else $XDG_CONFIG_HOME/kokoro-tts/config.json, else ~/.config/kokoro-tts/config.json
"""
import json, os, sys
from pathlib import Path

PATH = Path(os.environ.get("KOKORO_TTS_CONFIG") or
            Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kokoro-tts" / "config.json")


def load():
    try:
        return json.loads(PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "show"
    cfg = load()
    if cmd == "show":
        print(json.dumps(cfg, indent=1))
    elif cmd == "get" and len(argv) == 3:
        v = cfg.get(argv[2])
        if v is not None:
            print(v)
    elif cmd == "set" and len(argv) == 4:
        cfg[argv[2]] = argv[3]
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(cfg, indent=1) + "\n")
        os.chmod(PATH, 0o600)
        print(f"saved {argv[2]} in {PATH}")
    elif cmd == "path":
        print(PATH)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
