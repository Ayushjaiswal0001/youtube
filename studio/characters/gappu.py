"""Gappu (गप्पू) Character Rig - Reusable 2D Vector Animation.
The smart, observant little mouse with round spectacles.
"""

import math
from typing import Optional, Tuple
import cairo
from studio.characters.mouth import draw_mouth
from studio.characters.rig_base import (
    JointNode, Viseme, draw_ellipse, draw_capsule,
    ease_in_out_quad, ease_out_bounce
)

# Gappu Character Palette
COLOR_FUR = (0.45, 0.55, 0.65, 1.0)       # #748DA6 Slate-Blue Cartoon Fur
COLOR_FUR_LIGHT = (0.82, 0.88, 0.94, 1.0) # Light blue/white tummy
COLOR_EAR_INNER = (0.98, 0.79, 0.85, 1.0) # Soft Pink Inner Ear
COLOR_NOSE = (0.95, 0.50, 0.65, 1.0)      # Cute Pink Nose
COLOR_BOWTIE = (0.18, 0.80, 0.44, 1.0)    # #2ECC71 Lime Green Bowtie
COLOR_GLASSES = (0.15, 0.18, 0.22, 1.0)   # Dark frame
COLOR_GLASS_TINT = (0.88, 0.96, 1.0, 0.35)
COLOR_EYE_WHITE = (1.0, 1.0, 1.0, 1.0)
COLOR_PUPIL = (0.10, 0.12, 0.15, 1.0)
COLOR_SHADOW = (0.1, 0.1, 0.15, 0.25)
COLOR_OUTLINE = (0.18, 0.18, 0.22, 1.0)


class GappuRig:
    """Reusable 2D skeletal rig for Gappu the Mouse."""

    def __init__(self, x: float = 0.0, y: float = 0.0, scale: float = 0.75):
        self.x = x
        self.y = y
        self.scale = scale
        self.facing = -1.0  # -1.0 faces left toward Chiku, 1.0 faces right

        # Joint Nodes
        self.root = JointNode("root", local_x=x, local_y=y)
        self.torso = JointNode("torso", parent=self.root, local_y=-150)
        self.head = JointNode("head", parent=self.torso, local_y=-120)

        # Facial & Gestural State
        self.blink_t = 0.0
        self.look_x = 0.0
        self.look_y = 0.0
        self.viseme = Viseme.SMILE
        self.mouth_open = 0.0
        self.eyebrow_tilt = 0.0
        self.eyebrow_y = 0.0
        self.glasses_slide = 0.0  # pushes glasses up nose

        # Limbs
        self.arm_l_angle = 0.1
        self.arm_r_angle = -0.1
        self.leg_l_angle = 0.0
        self.leg_r_angle = 0.0
        self.tail_wave = 0.0
        self.jump_y = 0.0

    def update_pose(self, pose: str, t: float, is_talking: bool = False, phoneme_intensity: float = 0.5,
                    lipsync: object | None = None, timeline: object | None = None):
        """Update Gappu's joints based on time and pose."""
        # Idle breathing
        breath = math.sin(t * 3.0 + 1.0) * 3.0
        self.torso.local_y = -150 + breath
        self.torso.local_rot = math.sin(t * 1.2) * 0.02

        # Blinking (every 4.0s)
        blink_cycle = ((t + 1.2) % 4.0)
        if blink_cycle < 0.15:
            self.blink_t = math.sin((blink_cycle / 0.15) * math.pi)
        else:
            self.blink_t = 0.0

        # Gentle tail twitch
        self.tail_wave = math.sin(t * 3.5) * 0.3

        # Talking mouth animation: narration envelope when available, sine fallback.
        if is_talking:
            if timeline is not None and len(timeline):  # type: ignore[arg-type]
                self.viseme = timeline.shape_at(t)  # type: ignore[union-attr]
                envelope = lipsync.at(t) if (lipsync is not None and len(lipsync)) else 1.0  # type: ignore[union-attr]
                if envelope <= 0.06:
                    self.viseme = Viseme.CLOSED
                    self.mouth_open = 0.0
                else:
                    self.mouth_open = timeline.scale_at(t) * (0.35 + 0.65 * envelope) * phoneme_intensity  # type: ignore[union-attr]
            elif lipsync is not None and len(lipsync):  # type: ignore[arg-type]
                self.mouth_open = lipsync.at(t) * phoneme_intensity  # type: ignore[union-attr]
                self.viseme = lipsync.viseme_at(t)  # type: ignore[union-attr]
            else:
                self.mouth_open = abs(math.sin(t * 14.0)) * phoneme_intensity
                if self.mouth_open > 0.6:
                    self.viseme = Viseme.OPEN_WIDE
                elif self.mouth_open > 0.3:
                    self.viseme = Viseme.OPEN_SMALL
                else:
                    self.viseme = Viseme.SMILE
        else:
            self.mouth_open = 0.0
            self.viseme = Viseme.SMILE

        # Pose specifics
        if pose == "idle" or pose == "observing":
            self.head.local_rot = math.sin(t * 1.5) * 0.04
            self.arm_l_angle = 0.2 + math.sin(t * 2.0) * 0.05
            self.arm_r_angle = -0.2 - math.sin(t * 2.0) * 0.05
            self.leg_l_angle = 0.0
            self.leg_r_angle = 0.0
            self.eyebrow_y = 0.0
            self.eyebrow_tilt = 0.0
            self.glasses_slide = 0.0

        elif pose == "skeptical_eyebrow":
            # One brow raised high, arms folded
            self.head.local_rot = -0.08
            self.arm_l_angle = 0.9   # folded arms
            self.arm_r_angle = -0.9
            self.eyebrow_y = -10.0
            self.eyebrow_tilt = -0.25
            self.glasses_slide = 2.0

        elif pose == "laughing_point":
            # Giggling with one hand pointing at Chiku
            self.head.local_rot = math.sin(t * 10.0) * 0.15
            self.arm_l_angle = -1.1  # pointing forward
            self.arm_r_angle = 0.6   # clutching tummy laughing
            self.eyebrow_y = -4.0
            self.eyebrow_tilt = 0.15
            self.jump_y = -abs(math.sin(t * 10.0)) * 12.0
            if not is_talking:
                self.viseme = Viseme.OPEN_WIDE

        elif pose == "satisfied_nod":
            self.head.local_rot = math.sin(t * 5.0) * 0.12  # nodding
            self.arm_l_angle = 0.3
            self.arm_r_angle = -0.3
            self.eyebrow_y = -2.0
            self.eyebrow_tilt = 0.1
            if not is_talking:
                self.viseme = Viseme.SMILE

        elif pose == "facepalm":
            self.head.local_rot = 0.18  # head hung down
            self.arm_l_angle = -1.5     # hand covering face
            self.arm_r_angle = 0.1
            self.eyebrow_y = 6.0
            self.eyebrow_tilt = -0.2

        elif pose == "hands_on_hips":
            self.head.local_rot = -0.05
            self.arm_l_angle = 0.8
            self.arm_r_angle = -0.8
            self.eyebrow_y = -4.0
            self.eyebrow_tilt = 0.1

    def draw(self, cr: cairo.Context):
        """Renders full 2D vector mouse to Cairo context."""
        cr.save()
        cr.translate(self.x, self.y + self.jump_y)
        cr.scale(self.scale * self.facing, self.scale)

        # 1. Shadow
        shadow_scale = max(0.5, 1.0 - abs(self.jump_y) / 80.0)
        draw_ellipse(cr, 0, 0, 75 * shadow_scale, 20 * shadow_scale,
                     fill_color=(0.1, 0.1, 0.15, 0.25 * shadow_scale))

        # 2. Long Thin Mouse Tail
        cr.save()
        cr.translate(20, -110)
        cr.set_source_rgba(0.95, 0.65, 0.75, 1.0)  # pinkish mouse tail
        cr.set_line_width(8)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(0, 0)
        c1x = 60 + self.tail_wave * 30
        c1y = 20
        c2x = 90 - self.tail_wave * 25
        c2y = -50
        endx = 70 + self.tail_wave * 15
        endy = -90
        cr.curve_to(c1x, c1y, c2x, c2y, endx, endy)
        cr.stroke_preserve()
        cr.set_source_rgba(*COLOR_OUTLINE)
        cr.set_line_width(3)
        cr.stroke()
        cr.restore()

        # 3. Feet
        # Left Foot
        draw_ellipse(cr, -24, -10, 22, 14, fill_color=COLOR_EAR_INNER, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        # Right Foot
        draw_ellipse(cr, 24, -10, 22, 14, fill_color=COLOR_EAR_INNER, stroke_color=COLOR_OUTLINE, stroke_width=3.5)

        # 4. Plump Pear-shaped Torso
        cr.save()
        cr.translate(0, self.torso.local_y + 80)
        cr.rotate(self.torso.local_rot)

        # Body base
        draw_ellipse(cr, 0, 0, 56, 68, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)

        # Light tummy patch
        draw_ellipse(cr, 0, 8, 36, 48, fill_color=COLOR_FUR_LIGHT)

        # Cute Lime-Green Bowtie
        cr.save()
        cr.translate(0, -56)
        cr.set_source_rgba(*COLOR_BOWTIE)
        cr.move_to(0, 0)
        cr.line_to(-22, -12)
        cr.line_to(-22, 12)
        cr.close_path()
        cr.move_to(0, 0)
        cr.line_to(22, -12)
        cr.line_to(22, 12)
        cr.close_path()
        cr.fill_preserve()
        cr.set_source_rgba(*COLOR_OUTLINE)
        cr.set_line_width(3.0)
        cr.stroke()
        draw_ellipse(cr, 0, 0, 7, 7, fill_color=COLOR_BOWTIE, stroke_color=COLOR_OUTLINE, stroke_width=3.0)
        cr.restore()

        # 5. Arms
        # Left Arm
        cr.save()
        cr.translate(-42, -25)
        cr.rotate(self.arm_l_angle)
        draw_capsule(cr, 0, 0, -18, 55, 12, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        draw_ellipse(cr, -18, 60, 12, 11, fill_color=COLOR_EAR_INNER, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        cr.restore()

        # Right Arm
        cr.save()
        cr.translate(42, -25)
        cr.rotate(self.arm_r_angle)
        draw_capsule(cr, 0, 0, 18, 55, 12, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        draw_ellipse(cr, 18, 60, 12, 11, fill_color=COLOR_EAR_INNER, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        cr.restore()

        # 6. Head & Face
        cr.save()
        cr.translate(0, -78)
        cr.rotate(self.head.local_rot)

        # Big Cute Mouse Ears!
        # Left Ear
        draw_ellipse(cr, -62, -45, 38, 44, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, -62, -45, 26, 32, fill_color=COLOR_EAR_INNER)
        # Right Ear
        draw_ellipse(cr, 62, -45, 38, 44, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, 62, -45, 26, 32, fill_color=COLOR_EAR_INNER)

        # Head Base
        draw_ellipse(cr, 0, -10, 58, 52, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)

        # Whiskers!
        cr.set_source_rgba(*COLOR_OUTLINE)
        cr.set_line_width(2.5)
        # Left Whiskers
        cr.move_to(-25, 10); cr.line_to(-75, 5); cr.stroke()
        cr.move_to(-25, 16); cr.line_to(-72, 22); cr.stroke()
        # Right Whiskers
        cr.move_to(25, 10); cr.line_to(75, 5); cr.stroke()
        cr.move_to(25, 16); cr.line_to(72, 22); cr.stroke()

        # Pink Mouse Nose
        draw_ellipse(cr, 0, 8, 11, 8, fill_color=COLOR_NOSE, stroke_color=COLOR_OUTLINE, stroke_width=2.5)

        # Mouth
        draw_mouth(cr, self.viseme, self.mouth_open, anchor_y=22, size=0.82, stroke_width=3.0)

        # Eyes
        for eye_x in [-20, 20]:
            cr.save()
            cr.translate(eye_x, -16)
            if self.blink_t > 0.8:
                cr.set_source_rgba(*COLOR_OUTLINE)
                cr.set_line_width(3.0)
                cr.move_to(-10, 0)
                cr.curve_to(-4, 4, 4, 4, 10, 0)
                cr.stroke()
            else:
                eye_h = 18 * (1.0 - self.blink_t)
                draw_ellipse(cr, 0, 0, 14, eye_h, fill_color=COLOR_EYE_WHITE, stroke_color=COLOR_OUTLINE, stroke_width=3.0)
                draw_ellipse(cr, self.look_x * 4, self.look_y * 3, 8, 10 * (1.0 - self.blink_t), fill_color=COLOR_PUPIL)
                draw_ellipse(cr, -3 + self.look_x * 4, -3 + self.look_y * 3, 3, 3, fill_color=(1.0, 1.0, 1.0, 0.9))
            cr.restore()

        # Big Round Geek Glasses (Gappu's signature feature!)
        for is_right, lens_x in [(False, -21), (True, 21)]:
            cr.save()
            cr.translate(lens_x, -16 + self.glasses_slide)
            # Glass tint fill
            draw_ellipse(cr, 0, 0, 22, 22, fill_color=COLOR_GLASS_TINT,
                         stroke_color=COLOR_GLASSES, stroke_width=4.5)
            # Lens reflection diagonal glint
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.45)
            cr.set_line_width(2.5)
            cr.move_to(-12, -12); cr.line_to(-4, -4); cr.stroke()
            cr.move_to(4, 4); cr.line_to(12, 12); cr.stroke()
            cr.restore()

        # Glasses bridge across nose
        cr.save()
        cr.translate(0, -16 + self.glasses_slide)
        cr.set_source_rgba(*COLOR_GLASSES)
        cr.set_line_width(4.5)
        cr.move_to(-5, 0); cr.line_to(5, 0); cr.stroke()
        cr.restore()

        # Eyebrows above glasses
        for is_right, eb_x in [(False, -21), (True, 21)]:
            cr.save()
            cr.translate(eb_x, -42 + self.eyebrow_y)
            rot = self.eyebrow_tilt if not is_right else -self.eyebrow_tilt
            cr.rotate(rot)
            cr.set_source_rgba(*COLOR_OUTLINE)
            cr.set_line_width(3.5)
            cr.move_to(-11, 0)
            cr.curve_to(-4, -3, 4, -3, 11, 0)
            cr.stroke()
            cr.restore()

        cr.restore()  # Head restore
        cr.restore()  # Torso restore
        cr.restore()  # Main restore
