"""Scene Renderer for Autonomous Hindi Animation Studio.
Renders 1080x1920 30fps frames with PyCairo vector graphics, multi-layer parallax,
skeletal rigged characters (Chiku & Gappu), animated lipsync, cartoon effects,
and mixes dialogue audio, sound effects, and background music with FFmpeg.
"""

import math
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
import cairo

from studio.config import VIDEO_WIDTH, VIDEO_HEIGHT, FPS, INTERMEDIATE_DIR
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig
from studio.characters.lipsync import VisemeTrack
from studio.animation.background import BackgroundRenderer
from studio.animation.camera import Camera
from studio.animation.effects import draw_sparkle, draw_dust_puff, draw_exclamation_pop
from studio.audio.sfx_library import SFXLibrary


class SceneRenderer:
    """Renders a single animated scene into a high-quality vertical MP4."""

    def __init__(self, width: int = VIDEO_WIDTH, height: int = VIDEO_HEIGHT, fps: int = FPS):
        self.width = width
        self.height = height
        self.fps = fps
        self.bg_renderer = BackgroundRenderer(width, height)
        self.sfx_lib = SFXLibrary()

    def render_scene(self, scene_data: Dict[str, Any], audio_data: Dict[str, Any],
                     output_mp4: Path, sfx_delay_ms: int = 400) -> Path:
        """Renders frames, mixes audio, and produces scene MP4."""
        duration = audio_data["duration"]
        # Add slight 0.5s pause at the end for natural pacing
        total_duration = duration + 0.5
        total_frames = max(int(total_duration * self.fps), 15)

        scene_num = scene_data.get("scene_num", 1)
        speaker = scene_data.get("speaker", "narrator")
        dialogue = scene_data.get("dialogue", "")
        chiku_pose = scene_data.get("chiku_pose", "idle")
        gappu_pose = scene_data.get("gappu_pose", "idle")
        camera_style = scene_data.get("camera", "medium_pan")
        sfx_name = scene_data.get("sfx", "whoosh")
        bg_name = scene_data.get("bg", "jungle_clearing")

        # Initialize Camera
        camera = Camera(self.width, self.height)
        if "zoom" in camera_style:
            camera.zoom = 1.15
        elif "close_up" in camera_style:
            camera.zoom = 1.25

        # Initialize Character Rigs
        # Chiku stands on left, Gappu on right
        chiku = ChikuRig(x=380, y=1450, scale=1.35)
        chiku.facing = 1.0  # looking right
        gappu = GappuRig(x=780, y=1450, scale=1.12)
        gappu.facing = -1.0  # looking left

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width, self.height)
        cr = cairo.Context(surface)

        subtitle_surface = None
        subtitle_path = scene_data.get("subtitle_png")
        if subtitle_path:
            try:
                subtitle_surface = cairo.ImageSurface.create_from_png(str(subtitle_path))
            except Exception as exc:
                print(f"[Render] WARNING: could not load subtitle overlay {subtitle_path}: {exc}")

        title_surface = None
        title_path = scene_data.get("title_png")
        if title_path:
            try:
                title_surface = cairo.ImageSurface.create_from_png(str(title_path))
            except Exception as exc:
                print(f"[Render] WARNING: could not load title overlay {title_path}: {exc}")

        # Mix the audio bed first so the video encoder can mux it directly.
        sfx_path = self.sfx_lib.get_sfx(sfx_name)
        bgm_path = self.sfx_lib.get_bgm()
        voice_path = Path(audio_data["audio_path"])
        lipsync_track = VisemeTrack.from_audio(voice_path, fps=self.fps)
        mixed_audio = INTERMEDIATE_DIR / f"scene_{scene_num:03d}_mixed.wav"
        filter_complex = (
            f"[0:a]volume=1.0[v];"
            f"[1:a]adelay={sfx_delay_ms}|{sfx_delay_ms},volume=0.75[s];"
            f"[2:a]volume=0.16[m];"
            f"[v][s][m]amix=inputs=3:duration=first:dropout_transition=2[aout]"
        )
        audio_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(voice_path),
            "-i",
            str(sfx_path),
            "-i",
            str(bgm_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[aout]",
            "-ac",
            "2",
            "-ar",
            "44100",
            str(mixed_audio),
        ]
        audio_result = subprocess.run(
            audio_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if audio_result.returncode != 0:
            raise RuntimeError(f"Scene {scene_num} audio mix failed: {audio_result.stderr[-2000:]}")

        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        print(f"[Render] Scene {scene_num}: Rendering {total_frames} frames ({total_duration:.2f}s)...")
        encode_cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-nostats",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-s",
            f"{self.width}x{self.height}",
            "-r",
            str(self.fps),
            "-i",
            "-",
            "-i",
            str(mixed_audio),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_mp4),
        ]
        encoder = subprocess.Popen(
            encode_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if encoder.stdin is None:
            raise RuntimeError("could not open ffmpeg stdin")
        try:
            for frame_idx in range(total_frames):
                t = frame_idx / float(self.fps)
                is_dialogue_playing = t <= duration
                chiku_talking = is_dialogue_playing and (speaker == "chiku")
                gappu_talking = is_dialogue_playing and (speaker == "gappu")

                if camera_style == "medium_pan":
                    camera.pan_x = math.sin(t * 0.4) * 30.0
                elif camera_style == "action_shake" and (0.3 < t < 1.2):
                    camera.trigger_shake(0.2)
                camera.update(1.0 / self.fps)

                cr.save()
                cr.set_operator(cairo.OPERATOR_CLEAR)
                cr.paint()
                cr.restore()

                self.bg_renderer.render_by_name(bg_name, cr, t, camera.pan_x, camera.pan_y)

                cr.save()
                camera.apply(cr, t)
                chiku.update_pose(chiku_pose, t, is_talking=chiku_talking, phoneme_intensity=0.8,
                                  lipsync=lipsync_track)
                gappu.update_pose(gappu_pose, t, is_talking=gappu_talking, phoneme_intensity=0.7,
                                  lipsync=lipsync_track)

                if sfx_name == "twinkle" or "\u092a\u0924\u094d\u0925\u0930" in dialogue:
                    sparkle_rot = t * 2.5
                    draw_sparkle(
                        cr,
                        460 + math.sin(t * 3) * 15,
                        1150 + math.cos(t * 3) * 15,
                        32 + math.sin(t * 6) * 8,
                        sparkle_rot,
                    )
                    draw_sparkle(
                        cr,
                        520,
                        1100,
                        20 + math.cos(t * 5) * 6,
                        -sparkle_rot * 1.2,
                    )

                if chiku_pose == "excited_jump" and (t % 0.78 < 0.25):
                    draw_dust_puff(cr, 380, 1460, progress=(t % 0.78) / 0.25, scale=1.2)

                if chiku_pose == "shocked_freeze" and t < 1.2:
                    draw_exclamation_pop(cr, 380, 1020, progress=min(1.0, t / 0.8))

                chiku.draw(cr)
                gappu.draw(cr)
                cr.restore()

                if title_surface is not None and t < 2.8:
                    alpha = min(1.0, max(0.0, (2.8 - t) / 0.6))
                    cr.set_source_surface(title_surface, 0, 0)
                    cr.paint_with_alpha(alpha)

                if subtitle_surface is not None and is_dialogue_playing:
                    cr.set_source_surface(subtitle_surface, 0, 0)
                    cr.paint()

                surface.flush()
                stride = surface.get_stride()
                row_bytes = self.width * 4
                if stride == row_bytes:
                    payload = bytes(surface.get_data())
                else:
                    raw = surface.get_data()
                    payload = b"".join(
                        raw[row * stride : row * stride + row_bytes]
                        for row in range(self.height)
                    )
                encoder.stdin.write(payload)

            encoder.stdin.close()
            stderr = encoder.stderr.read().decode("utf-8", errors="replace") if encoder.stderr else ""
            return_code = encoder.wait(timeout=120)
            if return_code != 0:
                raise RuntimeError(f"Scene {scene_num} encode failed: {stderr[-2000:]}")
        except Exception as exc:
            encoder.kill()
            err = ""
            if encoder.stderr is not None:
                err = encoder.stderr.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Scene {scene_num} video pipe failed: {err[-2000:]}") from exc

        print(f"[Render] Scene {scene_num} successfully encoded -> {output_mp4}")
        return output_mp4
