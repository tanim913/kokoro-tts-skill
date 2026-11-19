#!/usr/bin/env python3
"""Hold a file's text on the X clipboard for a while, so the browser can paste it with ctrl+v.

Usage (run in the background, then paste within the window):
    python3 -I clip.py CELL_FILE [SECONDS]      # default 90 seconds

Tk owns the X selection only while this process runs, so keep it alive until the paste is verified.
Prints the character count, which must equal the Monaco model length after pasting.
"""
import sys, tkinter

text = open(sys.argv[1], encoding="utf-8").read()
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 90
r = tkinter.Tk()
r.withdraw()
r.clipboard_clear()
r.clipboard_append(text)
r.update()
r.after(int(seconds * 1000), r.destroy)
print("on clipboard:", len(text), "chars for", int(seconds), "s", flush=True)
r.mainloop()
