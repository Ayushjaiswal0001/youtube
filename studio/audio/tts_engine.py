"""TTS Engine for Hindi Voice Generation.
Supports multi-character voices (Narrator, Chiku, Gappu) with Edge-TTS, gTTS fallback,
audio file caching to prevent duplicate downloads, and descriptive offline diagnostics.
"""

import asyncio
import subprocess
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
import edge_tts
from gtts import gTTS
from studio.config import VOICES, ASSETS_DIR, INTERMEDIATE_DIR


class TTSEngine:
    """Handles text-to-speech generation with character-specific voices and fallback cascade."""

    def __init__(self, output_dir: Path = INTERMEDIATE_DIR):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Uses ffprobe to obtain exact audio duration in seconds."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(res.stdout.strip())

    @staticmethod
    def _boundaries_path(audio_path: Path) -> Path:
        return audio_path.with_suffix(".boundaries.json")

    def _save_boundaries(self, audio_path: Path, text: str, duration: float,
                         boundaries: List[Dict[str, Any]], synthetic: bool = False) -> None:
        """Persist sentence timing next to the cached audio so lip-sync can reuse it.

        ``synthetic`` marks the whole-line fallback we invent when the service gave us no
        timing. It is kept for diagnostics but *not* treated as real timing on reload,
        otherwise a cached line would silently lose the sentence windows it once had.
        """
        try:
            payload = {"text": text, "duration": duration, "boundaries": boundaries,
                       "synthetic": synthetic}
            self._boundaries_path(audio_path).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"  [TTS] could not persist boundaries for {audio_path.name}: {exc}")

    def _load_boundaries(self, audio_path: Path) -> Optional[List[Dict[str, Any]]]:
        path = self._boundaries_path(audio_path)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("synthetic"):
            return None
        boundaries = payload.get("boundaries")
        if isinstance(boundaries, list) and boundaries:
            return boundaries
        return None

    def _is_valid_audio(self, audio_path: Path) -> bool:
        """Verifies an audio file exists, has content (>500 bytes), and is readable by ffprobe."""
        if not audio_path.exists() or audio_path.stat().st_size < 500:
            return False
        try:
            dur = self._get_audio_duration(audio_path)
            return dur > 0.1
        except Exception:
            return False

    async def _generate_edge_tts(self, text: str, voice_cfg: Dict[str, str], out_path: Path) -> List[Dict[str, Any]]:
        """Generates audio and collects boundary timestamps using Edge-TTS."""
        voice = voice_cfg.get("voice", "hi-IN-MadhurNeural")
        rate = voice_cfg.get("rate", "+0%")
        pitch = voice_cfg.get("pitch", "+0Hz")

        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        boundaries = []

        temp_path = out_path.with_name(f"{out_path.stem}_tmp.mp3")
        try:
            with open(temp_path, "wb") as f:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "SentenceBoundary":
                        start_sec = chunk["offset"] / 10_000_000.0
                        dur_sec = chunk["duration"] / 10_000_000.0
                        boundaries.append({
                            "text": chunk.get("text", ""),
                            "start": start_sec,
                            "end": start_sec + dur_sec
                        })
            if temp_path.exists() and temp_path.stat().st_size > 500:
                temp_path.replace(out_path)
                return boundaries
            raise RuntimeError("Edge-TTS generated empty or truncated audio file")
        finally:
            temp_path.unlink(missing_ok=True)

    def _generate_gtts_fallback(self, text: str, out_path: Path):
        """Generates fallback audio via Google Translate TTS."""
        temp_path = out_path.with_name(f"{out_path.stem}_gtts_tmp.mp3")
        try:
            tts = gTTS(text=text, lang="hi")
            tts.save(str(temp_path))
            if temp_path.exists() and temp_path.stat().st_size > 500:
                temp_path.replace(out_path)
            else:
                raise RuntimeError("gTTS produced empty file")
        finally:
            temp_path.unlink(missing_ok=True)

    def generate_dialogue(self, text: str, speaker: str = "narrator", tag: str = "dialogue") -> Dict[str, Any]:
        """Generates speech audio for a line of dialogue with caching and fallback."""
        voice_cfg = VOICES.get(speaker, VOICES["narrator"])
        out_path = self.output_dir / f"{tag}_{speaker}.mp3"

        # 1. Cache hit check: if valid audio already exists on disk, reuse it
        if self._is_valid_audio(out_path):
            duration = self._get_audio_duration(out_path)
            print(f"  [TTS Cache Hit] Reusing existing valid audio ({duration:.2f}s): {out_path.name}")
            cached = self._load_boundaries(out_path)
            if cached is None:
                cached = [{"text": text, "start": 0.0, "end": duration}]
                self._save_boundaries(out_path, text, duration, cached, synthetic=True)
            return {
                "audio_path": str(out_path),
                "speaker": speaker,
                "text": text,
                "duration": duration,
                "boundaries": cached
            }

        # 2. Primary attempt: Edge-TTS (with retry for transient network issues)
        boundaries = []
        edge_error = None
        for attempt in range(2):
            try:
                boundaries = asyncio.run(self._generate_edge_tts(text, voice_cfg, out_path))
                if self._is_valid_audio(out_path):
                    break
            except Exception as e:
                edge_error = e
                time.sleep(0.5)

        # 3. Secondary attempt: gTTS fallback if Edge-TTS failed
        if not self._is_valid_audio(out_path):
            print(f"[TTS Fallback to gTTS] Edge-TTS error ({edge_error}). Trying gTTS...")
            try:
                self._generate_gtts_fallback(text, out_path)
            except Exception as gtts_err:
                raise RuntimeError(
                    f"TTS Generation Failed for dialogue \"{text[:35]}...\":\n"
                    f"  1. Edge-TTS error: {edge_error}\n"
                    f"  2. gTTS error: {gtts_err}\n"
                    f"Please check your network connection."
                )

        duration = self._get_audio_duration(out_path)
        if not boundaries:
            boundaries = [{
                "text": text,
                "start": 0.0,
                "end": duration
            }]

        self._save_boundaries(out_path, text, duration, boundaries)

        return {
            "audio_path": str(out_path),
            "speaker": speaker,
            "text": text,
            "duration": duration,
            "boundaries": boundaries
        }
