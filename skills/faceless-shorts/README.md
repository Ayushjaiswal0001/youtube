# Faceless Shorts: a free Claude skill

Narrated faceless shorts (YouTube Shorts, TikTok, Reels) made 100% in code on your own computer: script, AI voice,
word-synced captions, animation, sound effects and music, rendered to MP4. No AI video, no API keys, no credits.

**Styles** (each has a style sheet, a style guide and a finished example video project)
1. **Deep Dive 3D** (flagship): Zack D. Films-like 3D "What happens if…?" explainers. Example: *What happens if you hold your breath?*
2. **Night File 3D**: unsolved mysteries and true crime in dark 3D rooms. Example: *The man who jumped out of a plane* (D.B. Cooper).
3. **Inside Out**: flat 2D x-ray explainers. Example: *What if you swallow gum?*
4. **Stick Story**: stick-figure survival steps. Example: *What if the power went out for 3 days?*
5. **Paper Atlas**: history in cut paper and maps. Example: *How one bakery burned down London*.
6. **Tall Tale 3D**: funny true stories, flat 2D cartoon people in a sunny 3D world. Example: *The girl who was mailed to grandma*.

**New in v2: an animation production system, not just six looks**
- **Style decision engine** (`scripts/select_style.py`): reads the idea and picks the style from a 44-entry library (6 render-verified engines + adapted recipes for cartoon, whiteboard, pixel-art, motion graphics, kinetic typography, storybook, comic, silhouette, low-poly, isometric...). Explains why, warns about hardware/audience/aspect problems, can propose one hybrid accent.
- **Pre-production** (`scripts/preproduction.py`): brief, decision, character + environment bible (palette/line/light/frame-rate locks), per-line storyboard (beat, shot, camera, light, transition, timing, continuity), optional prompt pack for your own external AI tools.
- **Automatic QC** (`scripts/qc.py`): objective checks on script, captions, timing, pacing, sources, bible, resolution, fps, A/V sync, audio level, black/frozen frames, with a visual checklist for what only eyes can judge.
- Honest status flags: `native` (engine + example), `adapted` (recipe, not render-verified), `prompt-pack`. See `reference/style-library.md`, `CHANGELOG.md`.

**How it works**
script.json → Kokoro voice (local, free) → Whisper word timings (local, free) → shots drawn in code, each cut and caption
placed on its word → procedural sound + music → headless Chrome captures every frame → ffmpeg renders the MP4.
Claude checks a contact sheet of the whole video before you ever see it.
Optional: when you ask, Claude uploads the finished short to your YouTube channel through Zapier (it confirms title, visibility and category first).

**Needs:** Claude Code (or Claude with a linked computer), Node.js 22+, ffmpeg, Google Chrome, Python 3.10+, ~1 GB for the
voice and Whisper models. Claude installs what's missing.

**Windows:** run the scripts in Git Bash (installed with Git for Windows; Claude Code uses it already).

**Install:** put this folder at `~/.claude/skills/faceless-shorts/`, then run `bash scripts/setup.sh` (prints "All set")
and `bash scripts/selftest.sh` (prints "SELFTEST PASSED"). `bash scripts/selftest.sh --logic` checks only the selector/pre-production/QC (no Chrome, seconds).

**OpenCode:** copy the folder to `~/.config/opencode/skills/faceless-shorts/` (or `.opencode/skills/faceless-shorts/` in a project; `.claude/skills/` also works). `SKILL.md` frontmatter is `name` + `description` only; the name matches the folder.

**Platforms:** only 9:16 (1080x1920) is supported by the engines; see `reference/platforms.md` for what 16:9 / 1:1 would take. Start a new session and ask:
"Make a Deep Dive 3D short: what happens if you crack your knuckles?"

**Layout:** `SKILL.md` (what Claude follows) · `scripts/` (setup, selftest, new_video, voice, words, estimate, **select_style, preproduction, qc**) ·
`library/` (**styles.json, hybrids.json, platforms.json**) · `reference/` (**style-library, storytelling, consistency, platforms, brief**) · `tests/concepts.json` ·
`styles/<style>/` (`style-sheet.png`, `STYLE.md`, `example/` = a complete project that renders as-is).

**Licenses:** the code, stories, drawings and sound are original and free to use in your videos. Inter font: SIL Open Font
License 1.1. Installed on first use: Kokoro-82M (Apache-2.0) via kokoro-onnx (MIT), faster-whisper + Whisper small.en (MIT),
numpy, scipy.
