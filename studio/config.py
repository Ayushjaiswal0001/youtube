"""Portable studio configuration for the autonomous Hindi animation pipeline."""

from pathlib import Path
import os

# Project directories. Every path can be relocated for CI or per-episode builds.
BASE_DIR = Path(os.environ.get("STUDIO_BASE_DIR", Path(__file__).resolve().parent.parent)).resolve()
STUDIO_DIR = Path(__file__).resolve().parent
ASSETS_DIR = Path(os.environ.get("STUDIO_ASSETS_DIR", BASE_DIR / "assets")).resolve()
OUTPUT_DIR = Path(
    os.environ.get("STUDIO_OUTPUT_DIR", BASE_DIR / "build" / "natkhat-toons" / "studio_output")
).resolve()
EPISODES_DIR = Path(os.environ.get("STUDIO_EPISODES_DIR", OUTPUT_DIR / "episodes")).resolve()
INTERMEDIATE_DIR = Path(
    os.environ.get("STUDIO_INTERMEDIATE_DIR", OUTPUT_DIR / "intermediate")
).resolve()
LOGS_DIR = Path(os.environ.get("STUDIO_LOGS_DIR", BASE_DIR / "build" / "logs")).resolve()
DATA_DIR = Path(
    os.environ.get("STUDIO_DATA_DIR", BASE_DIR / "pipeline_state" / "natkhat-toons" / "studio_data")
).resolve()

for d in [ASSETS_DIR, OUTPUT_DIR, EPISODES_DIR, INTERMEDIATE_DIR, LOGS_DIR, DATA_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Video Specifications (Vertical 9:16 for Shorts / Reels)
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30
SAMPLE_RATE = 44100

# Target Timings
MIN_EPISODE_SECONDS = 20
MAX_EPISODE_SECONDS = 65
TEST_SCENE_SECONDS = 10

# Bundled Hindi typography. Cairo text shaping is avoided; Chrome renders Hindi
# overlays from these font files. Nirmala UI remains a local fallback only.
HINDI_FONT_PATH = os.environ.get(
    "STUDIO_HINDI_FONT_PATH",
    str(ASSETS_DIR / "fonts" / "Baloo2-Variable.ttf"),
)
HINDI_FONT_NAME = os.environ.get("STUDIO_HINDI_FONT_NAME", "Baloo 2")

# Audio & Voice Settings (Edge-TTS + gTTS fallback)
VOICES = {
    "narrator": {
        "voice": "hi-IN-MadhurNeural",
        "rate": "+5%",
        "pitch": "+0Hz",
    },
    "chiku": {
        "voice": "hi-IN-MadhurNeural",
        "rate": "+18%",
        "pitch": "+25Hz",
    },
    "gappu": {
        "voice": "hi-IN-SwaraNeural",
        "rate": "+12%",
        "pitch": "+15Hz",
    },
}

# Quality & Performance Constraints
MAX_RAM_MB = 1800
SEQUENTIAL_RENDERING = True
CLEANUP_INTERMEDIATE = True
