# Platform profiles

Profiles live in `library/platforms.json` (aspect, size, fps, max length, sweet spot, hook window, cut cadence, caption zone, unsafe margins). `qc.py --platform <name>` checks against them.

| platform | aspect | length sweet spot | hook | cut every |
|---|---|---|---|---|
| reels | 9:16 | 15-35 s | 1.5 s | 1.5-3 s |
| shorts | 9:16 | 25-45 s (max 60) | 1.5 s | 1.5-3.5 s |
| tiktok | 9:16 | 15-45 s | 1.2 s | 1.2-3 s |
| youtube | 16:9 | 2-8 min | 5 s | 3-8 s |
| square | 1:1 | 20-45 s | 2 s | 2-4 s |

## What is actually supported (be honest with the user)
**Only 1080x1920 (9:16) is supported by the bundled engines.** Canvas size is fixed in each engine (`W`/`H` in `lib.js` / `engine.js`, `index.html`, `capture.mjs --window-size`) and every shot is positioned by hand for that frame.
For 16:9 or 1:1 the engine must be recomposed, not just resized:
1. change `W`,`H` (and canvas sizes, `--window-size`, GL size in `main.js`),
2. move the caption band (`CAP` in `captions.js`) to the profile's `caption_zone`,
3. re-author every shot's layout for the new frame (hero positions assume x centre = 540),
4. re-run `qc.py --platform <name>`.
Until that is done and a render has been looked at, do not promise those formats. Other practical route: render 9:16 and place it on a blurred or branded 16:9/1:1 canvas with ffmpeg (works, but is a pillarboxed vertical video, not a native layout).
