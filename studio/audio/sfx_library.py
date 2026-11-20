"""Procedural Cartoon Sound Effects and Background Music Synthesizer.
100% Royalty-Free and Commercial-Safe, synthesized locally using NumPy & SoundFile.
"""

import math
from pathlib import Path
from typing import Dict, Optional
import numpy as np
import soundfile as sf
from studio.config import ASSETS_DIR

SFX_DIR = ASSETS_DIR / "sfx"
MUSIC_DIR = ASSETS_DIR / "music"
SFX_DIR.mkdir(parents=True, exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_RATE = 44100


def synth_whoosh(filename: Path = SFX_DIR / "whoosh.wav", duration: float = 0.45):
    """Synthesizes a cartoon air whoosh / leap sound."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    # Bandpass filtered sweeping noise + sine
    noise = np.random.uniform(-1, 1, len(t))
    envelope = np.sin(np.pi * (t / duration)) ** 2
    f_sweep = 200 + 1200 * np.sin(np.pi * (t / duration))
    carrier = np.sin(2 * np.pi * f_sweep * t)
    audio = (0.6 * noise + 0.4 * carrier) * envelope
    # Soft clip
    audio = np.clip(audio * 0.7, -1.0, 1.0)
    sf.write(str(filename), audio, SAMPLE_RATE)
    return filename


def synth_twinkle(filename: Path = SFX_DIR / "twinkle.wav", duration: float = 0.8):
    """Synthesizes magical cartoon sparkle chime."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    # Arpeggio of bright sine bells: C6, E6, G6, C7
    freqs = [1046.50, 1318.51, 1567.98, 2093.00, 2637.02]
    audio = np.zeros_like(t)
    note_dur = duration / len(freqs)
    for i, f in enumerate(freqs):
        start_idx = int(i * note_dur * SAMPLE_RATE)
        sub_t = t[start_idx:] - (i * note_dur)
        if len(sub_t) > 0:
            decay = np.exp(-sub_t * 9.0)
            note = np.sin(2 * np.pi * f * sub_t) * decay
            audio[start_idx:] += note * 0.35
    audio = np.clip(audio, -1.0, 1.0)
    sf.write(str(filename), audio, SAMPLE_RATE)
    return filename


def synth_boing(filename: Path = SFX_DIR / "boing.wav", duration: float = 0.6):
    """Synthesizes funny cartoon spring boing."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    f0 = 180.0
    f1 = 480.0
    # Pitch bend upwards then wobble
    pitch = f0 + (f1 - f0) * (1 - np.exp(-t * 12.0)) + 45.0 * np.sin(2 * np.pi * 18.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch) / SAMPLE_RATE
    envelope = np.exp(-t * 4.5)
    audio = np.sin(phase) * envelope * 0.75
    sf.write(str(filename), audio, SAMPLE_RATE)
    return filename


def synth_pop(filename: Path = SFX_DIR / "pop.wav", duration: float = 0.12):
    """Synthesizes quick cartoon cork pop."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    pitch = 900.0 * np.exp(-t * 40.0)
    phase = 2 * np.pi * np.cumsum(pitch) / SAMPLE_RATE
    envelope = np.exp(-t * 50.0)
    audio = np.sin(phase) * envelope * 0.8
    sf.write(str(filename), audio, SAMPLE_RATE)
    return filename


def synth_success_ding(filename: Path = SFX_DIR / "success_ding.wav", duration: float = 1.2):
    """Synthesizes bright cartoon victory ding."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    freq = 1760.0  # A6
    harmonics = [1.0, 2.0, 3.0, 4.2]
    weights = [0.6, 0.25, 0.1, 0.05]
    audio = np.zeros_like(t)
    for h, w in zip(harmonics, weights):
        audio += w * np.sin(2 * np.pi * freq * h * t) * np.exp(-t * (4.0 * h))
    audio = np.clip(audio * 0.8, -1.0, 1.0)
    sf.write(str(filename), audio, SAMPLE_RATE)
    return filename


def synth_cartoon_bgm(filename: Path = MUSIC_DIR / "whimsical_bgm.wav", duration: float = 35.0):
    """Synthesizes a playful, light acoustic marimba/pizzicato background music track."""
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    audio = np.zeros_like(t)

    # Playful 4-bar bouncy progression in C Major: C - Am - F - G (120 BPM = 0.5s per beat)
    chord_roots = [261.63, 220.00, 174.61, 196.00]  # C4, A3, F3, G3
    bar_dur = 2.0  # 4 beats per bar at 120 bpm

    num_bars = int(duration / bar_dur) + 1
    for bar in range(num_bars):
        root = chord_roots[bar % len(chord_roots)]
        # Marimba arpeggio notes (root, 3rd, 5th, octave)
        scale_steps = [1.0, 1.25, 1.5, 2.0]
        for beat in range(4):
            note_time = bar * bar_dur + beat * 0.5
            if note_time >= duration:
                break
            f = root * scale_steps[beat % len(scale_steps)]
            start_idx = int(note_time * SAMPLE_RATE)
            sub_len = min(int(0.45 * SAMPLE_RATE), len(t) - start_idx)
            if sub_len > 0:
                sub_t = np.linspace(0, sub_len / SAMPLE_RATE, sub_len, False)
                # Marimba mallet attack + quick decay
                decay = np.exp(-sub_t * 12.0)
                note = (np.sin(2 * np.pi * f * sub_t) + 0.3 * np.sin(4 * np.pi * f * sub_t)) * decay
                audio[start_idx:start_idx + sub_len] += note * 0.25

    # Gentle overall volume level for background bed (-16dB)
    audio = np.clip(audio * 0.35, -1.0, 1.0)
    # Stereo expansion (subtle delay on right channel)
    stereo = np.column_stack([audio, np.roll(audio, 120)])
    sf.write(str(filename), stereo, SAMPLE_RATE)
    return filename


class SFXLibrary:
    """Manages sound effects generation and caching."""

    def __init__(self):
        self.ensure_assets()

    def ensure_assets(self):
        """Builds all procedural sound files if not present."""
        if not (SFX_DIR / "whoosh.wav").exists():
            synth_whoosh()
        if not (SFX_DIR / "twinkle.wav").exists():
            synth_twinkle()
        if not (SFX_DIR / "boing.wav").exists():
            synth_boing()
        if not (SFX_DIR / "pop.wav").exists():
            synth_pop()
        if not (SFX_DIR / "success_ding.wav").exists():
            synth_success_ding()
        if not (MUSIC_DIR / "whimsical_bgm.wav").exists():
            synth_cartoon_bgm()

    def get_sfx(self, name: str) -> Optional[Path]:
        p = SFX_DIR / f"{name}.wav"
        if p.exists():
            return p
        return SFX_DIR / "pop.wav"

    def get_bgm(self) -> Path:
        return MUSIC_DIR / "whimsical_bgm.wav"


if __name__ == "__main__":
    lib = SFXLibrary()
    print("All procedural SFX and BGM generated successfully!")
