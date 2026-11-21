"""Scene Renderer for Autonomous Hindi Animation Studio.
Renders 1080x1920 30fps frames with PyCairo vector graphics, multi-layer parallax,
skeletal rigged characters (Chiku & Gappu), animated lipsync, cartoon effects,
and mixes dialogue audio, sound effects, and background music with FFmpeg.
"""

import json
import math
import os
import subprocess
import zlib
from pathlib import Path
from typing import Dict, Any, Optional
import cairo

from studio.config import VIDEO_WIDTH, VIDEO_HEIGHT, FPS, INTERMEDIATE_DIR
from studio.audio.loudness import normalize_file
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig
from studio.characters.gaze import (
    ANCHOR_CAMERA,
    FaceController,
    expression_for_pose,
    gaze_toward,
)
from studio.characters.lipsync import VisemeTrack
from studio.characters.locomotion import MotionController, motions_for
from studio.characters.interaction import (
    InteractionDirector,
    plan_interaction,
    replace_body_hip,
)
from studio.characters.performance import (
    PerformanceFace,
    PerformancePlan,
    PerformanceTrack,
    plan_performance,
)
from studio.characters.visemes import VisemeTimeline
from studio.animation.background import BackgroundRenderer
from studio.animation.camera import Camera, CameraDirector
from studio.animation.framing import (
    FramingReport,
    plan_shot,
    subject_from_schema,
)
from studio.animation.transitions import ffmpeg_fade_filters
from studio.animation.effects import (
    draw_sparkle, draw_dust_puff, draw_exclamation_pop, draw_vignette,
)
from studio.audio.sfx_library import SFXLibrary


CHIKU_X = 380.0
GAPPU_X = 780.0
CHARACTER_Y = 1450.0
EYE_HEIGHT = 1180.0


def _seed_for(*parts) -> int:
    """Stable seed so a re-render of the same scene animates identically."""

    return zlib.crc32(":".join(str(part) for part in parts).encode("utf-8"))


def _gaze_beats(own_x: float, partner_x: float, span: float,
                speaking: bool, facing: float = 1.0) -> list:
    """Alternate eye contact with looks away, so nobody stares unblinkingly.

    A speaker looks at their partner more than a listener does, but both keep returning
    to the other character: that is what reads as a conversation instead of two solos.
    """

    screen_x, screen_y = gaze_toward(own_x, partner_x, EYE_HEIGHT, EYE_HEIGHT)
    # Rigs draw with scale * facing, so screen-space gaze is mirrored for a left-facing
    # character: convert to the rig's local axis before handing it to the pupil offset.
    partner = (screen_x * facing, screen_y)
    away = (-partner[0] * 0.55, partner[1] - 0.3) if speaking else ANCHOR_CAMERA
    events: list = []
    period = 2.1 if speaking else 2.8
    index = 0
    at = 0.0
    while at < span:
        events.append((at, partner if index % 2 == 0 else away))
        at += period
        index += 1
    return events


def _expression_schedule(scene_data, character: str, pose: str,
                         speaking: bool) -> list:
    """Build the expression timeline for one character in one scene."""

    posed = expression_for_pose(pose)
    if speaking:
        base = scene_data.get(f"{character}_expression") or posed
    else:
        # A listener keeps whatever their pose says, unless the pose is plain neutral, in
        # which case they get the attentive listening face.
        base = (scene_data.get(f"{character}_listening_expression")
                or (posed if posed != "neutral" else "listening"))
    schedule = [(0.0, base)]
    for change in scene_data.get(f"{character}_expressions") or []:
        try:
            at = float(change["at"])
            name = str(change["name"])
        except (KeyError, TypeError, ValueError):
            continue
        schedule.append((max(0.0, at), name))
    return schedule


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
        story_id = str(scene_data.get("story_id") or audio_data.get("story_id")
                       or Path(output_mp4).parent.name)
        speaker = scene_data.get("speaker", "narrator")
        dialogue = scene_data.get("dialogue", "")
        chiku_pose = scene_data.get("chiku_pose", "idle")
        gappu_pose = scene_data.get("gappu_pose", "idle")
        camera_style = scene_data.get("camera", "medium_pan")
        sfx_name = scene_data.get("sfx", "whoosh")
        bg_name = scene_data.get("bg", "jungle_clearing")

        # Camera direction (T35): a style is a short deterministic move, not a static zoom.
        camera = Camera(self.width, self.height)
        director = CameraDirector(camera_style, total_duration, (self.width, self.height))

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

        # Face controllers (T32): gaze, saccades, blinks and expressions per character.
        chiku_face = FaceController(
            chiku.schema,
            seed=_seed_for(story_id, scene_num, "chiku"),
            span=total_duration + 2.0,
            schedule=_expression_schedule(scene_data, "chiku", chiku_pose,
                                          speaker == "chiku"),
            scripted_gaze=_gaze_beats(CHIKU_X, GAPPU_X, total_duration,
                                      speaking=speaker == "chiku",
                                      facing=chiku.facing),
        )
        gappu_face = FaceController(
            gappu.schema,
            seed=_seed_for(story_id, scene_num, "gappu"),
            span=total_duration + 2.0,
            schedule=_expression_schedule(scene_data, "gappu", gappu_pose,
                                          speaker == "gappu"),
            scripted_gaze=_gaze_beats(GAPPU_X, CHIKU_X, total_duration,
                                      speaking=speaker == "gappu",
                                      facing=gappu.facing),
        )
        # Interaction layer (T35b): keeps the two bodies apart, turns them toward each
        # other, and lets a speaker's emphasis reach the listener. With the plan empty and
        # the anchors already apart this resolves to the identity transform, so existing
        # episodes render unchanged. FACTORY_NO_INTERACTION=1 removes it entirely.
        interaction = InteractionDirector(
            anchor_a=chiku.schema.anchor["x"], anchor_b=gappu.schema.anchor["x"],
            plan=(None if os.environ.get("FACTORY_NO_INTERACTION")
                  else plan_interaction(dialogue, duration=total_duration, speaker=speaker,
                                        listener=("gappu" if speaker == "chiku" else "chiku"),
                                        seed=_seed_for(story_id, scene_num, "interaction"))),
            facing_a=int(math.copysign(1, chiku.facing)),
            facing_b=int(math.copysign(1, gappu.facing)),
        )

        # Shot planning (T39): the camera is told what has to be on screen. The subjects come
        # from the character schemas - the same source the rigs use - so the framing can never
        # disagree with the drawing. A character that gestures must be fully in frame, so the
        # scripted style is treated as a request and widened when it would crop one.
        subjects = {
            "chiku": subject_from_schema("chiku", chiku.schema),
            "gappu": subject_from_schema("gappu", gappu.schema),
        }
        # The planner applies each kind's own semantics: a close-up must belong to the character
        # who is performing, and a relational shot (medium/two_shot/wide) must hold the whole
        # cast. `must_show` is only for a caller that insists on particular characters.
        must_show = None
        # A hand-off or any scene that is about the pair rather than one of them asks for both
        # characters on screen; pair lock is the blunt version of that, and also a switch for
        # A/B renders while the shot policy is being decided by eye.
        if (os.environ.get("FACTORY_CAMERA_PAIR_LOCK") == "1"
                or str(scene_data.get("interaction", "")) in ("contact", "hand_off")):
            must_show = ["chiku", "gappu"]
        shot = plan_shot(camera_style, subjects, (self.width, self.height),
                         speaker=speaker if speaker in subjects else None,
                         must_show=must_show)
        if os.environ.get("FACTORY_CAMERA_FRAMING", "1") == "1":
            director.shot = shot
        if shot.escalated:
            print(f"[Render] Scene {scene_num}: camera {camera_style} -> {shot.kind} "
                  f"({shot.reason}) to keep {', '.join(shot.subjects)} in frame")
        framing = FramingReport((self.width, self.height), required=tuple(shot.subjects))
        framing_gesture_frames = 0

        # Locomotion layer (T33). Scenes without a motion keep the pose exactly as it was,
        # so every existing episode renders unchanged.
        chiku_motion = MotionController(
            motions_for(scene_data, "chiku")[0], duration=total_duration,
            seed=_seed_for(story_id, scene_num, "chiku", "motion"), facing=chiku.facing)
        gappu_motion = MotionController(
            motions_for(scene_data, "gappu")[0], duration=total_duration,
            seed=_seed_for(story_id, scene_num, "gappu", "motion"), facing=gappu.facing)

        # Performance layer (T34): reaction beats derived from the spoken line, so the
        # listener nods and recoils instead of standing in an authored pose for the whole
        # scene. An empty plan leaves every frame exactly as it was.
        # FACTORY_NO_PERFORMANCE=1 disables the layer, which is how the A/B render that
        # proves this layer only adds motion is produced, and the switch to pull if the
        # beats ever look wrong in a real episode.
        if os.environ.get("FACTORY_NO_PERFORMANCE"):
            plan = PerformancePlan()
        else:
            plan = plan_performance(dialogue, duration=total_duration, speaker=speaker,
                                    seed=_seed_for(story_id, scene_num, "performance"))
        chiku_perf = PerformanceTrack(plan.for_character("chiku"), total_duration)
        gappu_perf = PerformanceTrack(plan.for_character("gappu"), total_duration)
        if plan.chiku or plan.gappu:
            print(f"[Render] Scene {scene_num}: performance beats "
                  f"chiku={len(plan.chiku)} gappu={len(plan.gappu)}")

        chiku.attach_face(PerformanceFace(chiku_face, chiku_perf))
        gappu.attach_face(PerformanceFace(gappu_face, gappu_perf))

        # Mix the audio bed first so the video encoder can mux it directly.
        sfx_path = self.sfx_lib.get_sfx(sfx_name)
        bgm_path = self.sfx_lib.get_bgm()
        voice_path = Path(audio_data["audio_path"])
        lipsync_track = VisemeTrack.from_audio(voice_path, fps=self.fps)
        dialogue_text = str(audio_data.get("text") or scene_data.get("dialogue") or "")
        viseme_timeline = VisemeTimeline.from_text(
            dialogue_text,
            duration=duration,
            fps=self.fps,
            boundaries=audio_data.get("boundaries"),
            envelope=lipsync_track if len(lipsync_track) else None,
        )
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

        # EBU R128 normalisation (T36). The animated path used to ship at about -24 LUFS,
        # ten LU below reference; a linear gain fixes the level without touching duration,
        # so A/V sync and lip-sync stay exact. A file that cannot be measured is reported
        # rather than silently replaced.
        loudness = normalize_file(mixed_audio, keep_duration=total_duration)
        measured = loudness.get("after") or {}
        if loudness.get("applied"):
            print(f"[Render] Scene {scene_num}: loudness "
                  f"{(loudness.get('before') or {}).get('integrated_lufs', float('nan')):.1f} -> "
                  f"{measured.get('integrated_lufs', float('nan')):.1f} LUFS "
                  f"(peak {measured.get('true_peak_dbtp', float('nan')):.1f} dBTP, "
                  f"delta {loudness.get('duration_delta')}s)")
        else:
            print(f"[Render] Scene {scene_num}: WARNING loudness not applied: "
                  f"{loudness.get('error', 'unknown')}")

        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        print(f"[Render] Scene {scene_num}: Rendering {total_frames} frames ({total_duration:.2f}s)...")
        # Scene transitions (T37): a location change dips to black, a beat in the same
        # location cuts directly. Time-based, so it never touches the frame loop.
        fade_filters = ffmpeg_fade_filters(
            float(scene_data.get("fade_in") or 0.0),
            float(scene_data.get("fade_out") or 0.0),
            total_duration,
        )
        if fade_filters:
            print(f"[Render] Scene {scene_num}: transitions {'; '.join(fade_filters)}")
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
            *(["-vf", ",".join(fade_filters)] if fade_filters else []),
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

                # Interaction resolves the two bodies together, so it has to run after both
                # motions are known and before either rig is posed - and before the camera,
                # which now frames the characters where they actually are this frame.
                chiku_body = chiku_perf.accent_at(t).on_body(chiku_motion.state_at(t))
                gappu_body = gappu_perf.accent_at(t).on_body(gappu_motion.state_at(t))
                hip_a, hip_b = interaction.resolve(chiku_body.hip_x, gappu_body.hip_x)
                chiku_body = replace_body_hip(chiku_body, hip_a)
                gappu_body = replace_body_hip(gappu_body, hip_b)
                layer_a, layer_b = interaction.bodies(t, hip_a, hip_b, speaker)
                if layer_a is not None:
                    chiku_body = chiku_body.merged_with(layer_a)
                if layer_b is not None:
                    gappu_body = gappu_body.merged_with(layer_b)

                camera_frame = director.state_at(
                    t, positions={"chiku": chiku.x + hip_a, "gappu": gappu.x + hip_b})
                camera.zoom = camera_frame.zoom
                camera.pan_x = camera_frame.pan_x
                camera.pan_y = camera_frame.pan_y
                reach_a = interaction.amount_at(t, 0)
                reach_b = interaction.amount_at(t, 1)
                if reach_a > 0.0 or reach_b > 0.0:
                    framing_gesture_frames += 1
                framing.add(t, camera.zoom, camera.pan_x, camera.pan_y, subjects,
                            reach={"chiku": reach_a, "gappu": reach_b})
                if camera_style == "action_shake" and 0.3 < t < 1.2:
                    camera.trigger_shake(0.2)
                camera.update(1.0 / self.fps)

                cr.save()
                cr.set_operator(cairo.OPERATOR_CLEAR)
                cr.paint()
                cr.restore()

                self.bg_renderer.render_by_name(
                    bg_name, cr, t, camera.pan_x, camera.pan_y,
                    zoom=(camera.zoom if os.environ.get("FACTORY_CAMERA_ZOOM_BG", "1") == "1"
                          else 1.0))

                cr.save()
                camera.apply(cr, t)
                face_a, face_b = interaction.facing(hip_a, hip_b)
                if face_a != int(math.copysign(1, chiku.facing)):
                    chiku.facing = float(face_a)
                if face_b != int(math.copysign(1, gappu.facing)):
                    gappu.facing = float(face_b)

                chiku.update_pose(
                    chiku_pose, t, is_talking=chiku_talking, phoneme_intensity=0.8,
                    lipsync=lipsync_track, timeline=viseme_timeline,
                    body=chiku_body)
                gappu.update_pose(
                    gappu_pose, t, is_talking=gappu_talking, phoneme_intensity=0.7,
                    lipsync=lipsync_track, timeline=viseme_timeline,
                    body=gappu_body)
                chiku.face_state_at(t)
                gappu.face_state_at(t)

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

                # A close-up frames one character: drawing the other would leave a sliver
                # of them at the frame edge, which reads as a mistake rather than a shot.
                if director.subject != "gappu":
                    chiku.draw(cr)
                if director.subject != "chiku":
                    gappu.draw(cr)
                cr.restore()

                # Lens vignette (T35): screen space, above the scene and below the
                # subtitle band so captions keep full contrast.
                draw_vignette(cr, self.width, self.height)

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
            # Include the exception: an empty ffmpeg stderr used to hide a Python bug in the
            # frame loop behind "video pipe failed", which told a reader nothing.
            raise RuntimeError(
                f"Scene {scene_num} video pipe failed: {type(exc).__name__}: {exc} "
                f"| ffmpeg: {err[-1500:]}") from exc

        # Framing report (T39): what the camera actually covered, frame by frame, measured with
        # the same projection the renderer used. Written next to the scene so QC can gate on it
        # and a human can see which subject was cropped and by how much.
        summary = framing.summary()
        summary.update({
            "scene": scene_num,
            "camera_style": camera_style,
            "shot": shot.kind,
            "shot_subjects": list(shot.subjects),
            "shot_zoom": round(shot.zoom, 4),
            "escalated": shot.escalated,
            "reason": shot.reason,
            "gesture_frames": framing_gesture_frames,
        })
        try:
            report_path = Path(output_mp4).with_name(Path(output_mp4).stem + "_framing.json")
            report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
            cropped = {name: data["cropped_frames"]
                       for name, data in summary["subjects"].items()
                       if data["cropped_frames"]}
            print(f"[Render] Scene {scene_num} framing: shot={shot.kind} "
                  f"zoom={shot.zoom:.2f} "
                  + (f"CROPPED {cropped}" if cropped else "all subjects in frame"))
        except Exception as exc:  # a report must never fail a render
            print(f"[Render] WARNING: could not write framing report: {exc}")

        print(f"[Render] Scene {scene_num} successfully encoded -> {output_mp4}")
        return output_mp4
