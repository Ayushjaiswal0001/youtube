"""Chrome-backed Devanagari overlay rendering.

Cairo on Windows can shape Hindi with Uniscribe, but the Linux/CI path cannot rely
on it. Headless Chrome renders the same HTML/CSS text identically on both platforms,
so the studio composites transparent PNG overlays instead of drawing text itself.
"""

from __future__ import annotations

import base64
import html
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

WIDTH = 1080
HEIGHT = 1920
FONT_CANDIDATES = (
    "Baloo2-Variable.ttf",
    "NotoSansDevanagari-Variable.ttf",
)
CHROME_CANDIDATES = (
    os.environ.get("CHROME_PATH", ""),
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)


def _chrome_path() -> str:
    for candidate in CHROME_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return candidate
    found = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    if found:
        return found
    raise FileNotFoundError("Chrome/Chromium not found; set CHROME_PATH")


def _font_path(fonts_dir: Path) -> Path:
    for name in FONT_CANDIDATES:
        candidate = fonts_dir / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Devanagari font not found in {fonts_dir}")


def _data_uri(path: Path) -> str:
    return "data:font/ttf;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _page(text: str, *, kind: str, font_uri: str, kicker: str = "") -> str:
    escaped = html.escape(text).replace("\n", "<br>")
    sub_size = 56
    if kind == "subtitle":
        if len(text) > 65:
            sub_size = 44
        elif len(text) > 55:
            sub_size = 52
    if kind == "title":
        body = f"""
        <div class="title-wrap">
          <div class="kicker">{html.escape(kicker)}</div>
          <div class="title">{escaped}</div>
        </div>
        """
    else:
        body = f'<div class="subtitle-wrap"><div class="subtitle">{escaped}</div></div>'

    return f"""<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<style>
@font-face {{
  font-family: 'FactoryHindi';
  src: url('{font_uri}') format('truetype');
  font-weight: 400 800;
}}
* {{ box-sizing: border-box; }}
html, body {{
  margin: 0; padding: 0; width: {WIDTH}px; height: {HEIGHT}px;
  background: transparent; overflow: hidden;
  font-family: 'FactoryHindi', 'Baloo 2', 'Noto Sans Devanagari', sans-serif;
}}
.subtitle-wrap {{
  position: absolute; left: 0; right: 0; bottom: 360px;
  display: flex; justify-content: center; padding: 0 90px;
}}
.subtitle {{
  display: inline-block; max-width: 940px; padding: 22px 36px 26px;
  border-radius: 30px;
  background: linear-gradient(180deg, rgba(16,13,31,0.90), rgba(8,6,18,0.82));
  border: 2px solid rgba(255,255,255,0.17);
  box-shadow: 0 12px 34px rgba(0,0,0,0.42), inset 0 1px 0 rgba(255,255,255,0.10);
  color: #FFF7E8; font-size: {sub_size}px; font-weight: 700; line-height: 1.30;
  text-align: center; letter-spacing: 0.2px;
  text-shadow: 0 3px 0 rgba(0,0,0,0.35), 0 0 16px rgba(255,184,76,0.14);
}}
.title-wrap {{
  position: absolute; left: 0; right: 0; top: 230px;
  display: flex; flex-direction: column; align-items: center;
  text-align: center; padding: 0 60px;
}}
.kicker {{
  margin-bottom: 16px; padding: 10px 22px 12px; border-radius: 999px;
  background: rgba(12,8,20,0.74); border: 2px solid rgba(255,209,102,0.48);
  color: #FFD166; font-size: 28px; font-weight: 800; letter-spacing: 1.8px;
  text-transform: uppercase;
}}
.title {{
  max-width: 960px; color: #FFF8E7; font-size: 88px; font-weight: 800;
  line-height: 1.16; letter-spacing: 0.2px;
  text-shadow: 0 4px 0 rgba(0,0,0,0.42), 0 0 26px rgba(255,174,64,0.28),
               0 0 60px rgba(120,70,180,0.22);
}}
</style>
</head>
<body>{body}</body>
</html>"""


def _screenshot(
    page_html: str,
    out_path: Path,
    *,
    width: int,
    height: int,
    scale: int = 2,
    label: str = "overlay",
) -> Path:
    chrome = _chrome_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hindi_overlay_") as td:
        tmp = Path(td)
        page = tmp / "overlay.html"
        page.write_text(page_html, encoding="utf-8")
        raw = tmp / "raw.png"
        cmd = [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--allow-file-access-from-files",
            f"--force-device-scale-factor={scale}",
            f"--window-size={width},{height}",
            "--default-background-color=00000000",
            "--virtual-time-budget=2500",
            "--run-all-compositor-stages-before-draw",
            f"--screenshot={raw}",
            page.resolve().as_uri(),
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0 or not raw.is_file():
            raise RuntimeError(f"Chrome {label} render failed: {result.stderr[-1500:]}")
        image = Image.open(raw).convert("RGBA")
        if image.size != (width, height):
            image = image.resize((width, height), Image.LANCZOS)
        if image.getchannel("A").getbbox() is None:
            raise RuntimeError(f"Chrome produced a fully transparent {label}")
        image.save(out_path, "PNG")
    return out_path


def _render_png(text: str, out_path: Path, *, kind: str, fonts_dir: Path, kicker: str = "") -> Path:
    font_uri = _data_uri(_font_path(fonts_dir))
    return _screenshot(
        _page(text, kind=kind, font_uri=font_uri, kicker=kicker),
        out_path,
        width=WIDTH,
        height=HEIGHT,
        label=kind,
    )


def render_thumbnail_overlay(
    text: str,
    out_path: Path,
    *,
    fonts_dir: Path,
    kicker: str = "",
    footer: str = "",
    width: int = 1280,
    height: int = 720,
) -> Path:
    escaped = html.escape(text).replace("\n", "<br>")
    font_uri = _data_uri(_font_path(fonts_dir))
    page = f"""<!doctype html>
<html lang="hi">
<head>
<meta charset="utf-8">
<style>
@font-face {{
  font-family: 'FactoryHindi';
  src: url('{font_uri}') format('truetype');
  font-weight: 400 800;
}}
* {{ box-sizing: border-box; }}
html, body {{
  margin: 0; padding: 0; width: {width}px; height: {height}px;
  background: transparent; overflow: hidden;
  font-family: 'FactoryHindi', 'Baloo 2', 'Noto Sans Devanagari', sans-serif;
}}
.wrap {{
  position: absolute; left: 54px; right: 330px; bottom: 44px;
  display: flex; flex-direction: column; align-items: flex-start;
  text-align: left;
}}
.kicker {{
  margin-bottom: 14px; padding: 8px 18px 10px; border-radius: 999px;
  background: rgba(14,9,24,0.80); border: 2px solid rgba(255,209,102,0.62);
  color: #FFD166; font-size: 24px; font-weight: 800; letter-spacing: 1.2px;
}}
.title {{
  color: #FFF8E7; font-size: 62px; font-weight: 800;
  line-height: 1.16; letter-spacing: 0.1px;
  text-shadow: 0 4px 0 rgba(0,0,0,0.50), 0 0 26px rgba(255,174,64,0.30);
}}
.footer {{
  margin-top: 14px; padding: 7px 16px 9px; border-radius: 12px;
  background: rgba(14,9,24,0.74); color: #F3E7D0;
  font-size: 22px; font-weight: 700;
}}
</style>
</head>
<body>
  <div class="wrap">
    <div class="kicker">{html.escape(kicker)}</div>
    <div class="title">{escaped}</div>
    <div class="footer">{html.escape(footer)}</div>
  </div>
</body>
</html>"""
    return _screenshot(page, out_path, width=width, height=height, label="thumbnail")


def render_story_overlays(
    story: Dict[str, Any],
    out_dir: Path,
    *,
    fonts_dir: Path,
    kicker: str = "नटखट टून्स",
    title_scene: int = 1,
    force: bool = False,
) -> Dict[int, Dict[str, str]]:
    """Render subtitle PNGs for every scene and one title card for the episode."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result: Dict[int, Dict[str, str]] = {}
    title_png: Optional[Path] = None

    for scene in story.get("scenes", []):
        scene_num = int(scene["scene_num"])
        subtitle_png = out_dir / f"scene_{scene_num:03d}_subtitle.png"
        if force or not subtitle_png.is_file():
            _render_png(scene.get("dialogue", ""), subtitle_png, kind="subtitle", fonts_dir=fonts_dir)
        paths = {"subtitle_png": str(subtitle_png)}

        if scene_num == title_scene:
            if force or title_png is None or not title_png.is_file():
                title_png = out_dir / "title_card.png"
                _render_png(story.get("title", ""), title_png, kind="title",
                            fonts_dir=fonts_dir, kicker=kicker)
            paths["title_png"] = str(title_png)
        result[scene_num] = paths
    return result
