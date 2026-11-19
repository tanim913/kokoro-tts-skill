# Cover

`cover.html` is the source of the repository cover: a blue revised page of a radio-play script, set in Courier Prime with red pen cues in Nanum Pen Script (both loaded from Google Fonts). Render it with headless Chrome:

```bash
google-chrome --headless=new --hide-scrollbars --window-size=1280,640 --force-device-scale-factor=2 \
  --virtual-time-budget=8000 --screenshot=cover.png cover.html                 # 2560x1280, the README banner
google-chrome --headless=new --hide-scrollbars --window-size=1280,640 --force-device-scale-factor=1 \
  --virtual-time-budget=8000 --screenshot=social-preview.png cover.html        # 1280x640, GitHub social preview
```
