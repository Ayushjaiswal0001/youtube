"""Chiku (चीकू) Character Rig - Reusable 2D Vector Animation.
The cheeky, energetic monkey protagonist.
"""

import math
from typing import Optional, Tuple
import cairo
from studio.characters.rig_base import (
    JointNode, Viseme, draw_ellipse, draw_capsule,
    ease_in_out_quad, ease_out_bounce, spring_overshoot
)

# Chiku Character Palette
COLOR_FUR = (0.88, 0.54, 0.24, 1.0)       # #E08A3C Warm Golden Monkey Tan
COLOR_FUR_DARK = (0.75, 0.42, 0.16, 1.0)  # #BF6B29 Shading
COLOR_MUZZLE = (0.99, 0.85, 0.71, 1.0)    # #FDD9B5 Soft Peach
COLOR_INNER_EAR = (0.96, 0.75, 0.65, 1.0)
COLOR_VEST = (0.84, 0.19, 0.19, 1.0)      # #D63031 Crimson Cartoon Vest
COLOR_VEST_TRIM = (0.98, 0.80, 0.20, 1.0) # Yellow Vest Trim
COLOR_EYE_WHITE = (1.0, 1.0, 1.0, 1.0)
COLOR_PUPIL = (0.12, 0.10, 0.08, 1.0)
COLOR_SHADOW = (0.1, 0.1, 0.15, 0.25)
COLOR_OUTLINE = (0.25, 0.15, 0.08, 1.0)


class ChikuRig:
    """Reusable 2D skeletal rig for Chiku the Monkey."""

    def __init__(self, x: float = 0.0, y: float = 0.0, scale: float = 1.0):
        self.x = x
        self.y = y
        self.scale = scale
        self.facing = 1.0  # 1.0 = right, -1.0 = left

        # Joint Transforms
        self.root = JointNode("root", local_x=x, local_y=y)
        self.torso = JointNode("torso", parent=self.root, local_y=-220)
        self.head = JointNode("head", parent=self.torso, local_y=-170)

        # Facial State
        self.blink_t = 0.0  # 0.0 = open, 1.0 = closed
        self.look_x = 0.0   # -1.0 to 1.0
        self.look_y = 0.0   # -1.0 to 1.0
        self.eyebrow_tilt = 0.0  # radians
        self.eyebrow_y = 0.0
        self.viseme = Viseme.SMILE
        self.mouth_open = 0.0  # 0.0 to 1.0 for talking

        # Limb Angles (radians)
        self.arm_l_angle = 0.2
        self.arm_r_angle = -0.2
        self.leg_l_angle = 0.0
        self.leg_r_angle = 0.0
        self.tail_wave = 0.0
        self.jump_y = 0.0

    def update_pose(self, pose: str, t: float, is_talking: bool = False, phoneme_intensity: float = 0.5):
        """Update rig joints based on procedural motion and named pose."""
        # Idle breathing / sway
        breath = math.sin(t * 3.5) * 4.0
        self.torso.local_y = -220 + breath
        self.torso.local_rot = math.sin(t * 1.5) * 0.03

        # Periodic Blinking (every 3.2 seconds, lasts 0.15s)
        blink_cycle = (t % 3.2)
        if blink_cycle < 0.15:
            self.blink_t = math.sin((blink_cycle / 0.15) * math.pi)
        else:
            self.blink_t = 0.0

        # Tail natural wavy physics
        self.tail_wave = math.sin(t * 4.0) * 0.25

        # Talking mouth animation
        if is_talking:
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

        # Named Poses
        if pose == "idle":
            self.head.local_rot = math.sin(t * 2.0) * 0.05
            self.arm_l_angle = 0.15 + math.sin(t * 2.5) * 0.08
            self.arm_r_angle = -0.15 - math.sin(t * 2.5) * 0.08
            self.leg_l_angle = 0.0
            self.leg_r_angle = 0.0
            self.jump_y = 0.0
            self.eyebrow_tilt = 0.05
            self.eyebrow_y = 0.0

        elif pose == "excited_jump":
            jump_cycle = (t * 4.0) % math.pi
            self.jump_y = -abs(math.sin(jump_cycle)) * 60.0
            self.head.local_rot = math.sin(t * 8.0) * 0.1
            self.arm_l_angle = -1.2 + math.sin(t * 8.0) * 0.4  # arms raised high in joy
            self.arm_r_angle = 1.2 - math.sin(t * 8.0) * 0.4
            self.leg_l_angle = -0.3
            self.leg_r_angle = 0.3
            self.tail_wave = math.sin(t * 8.0) * 0.5
            self.eyebrow_y = -8.0
            self.eyebrow_tilt = 0.15
            if not is_talking:
                self.viseme = Viseme.OPEN_WIDE

        elif pose == "boast_proud":
            # Hand on hip, other pointing to chest
            self.jump_y = 0.0
            self.head.local_rot = -0.12  # tilted up proudly
            self.arm_l_angle = -0.8      # pointing proudly
            self.arm_r_angle = 0.7       # hand on hip
            self.leg_l_angle = -0.1
            self.leg_r_angle = 0.1
            self.eyebrow_y = -5.0
            self.eyebrow_tilt = 0.2
            if not is_talking:
                self.viseme = Viseme.SMILE

        elif pose == "shocked_freeze":
            self.jump_y = -10.0
            self.head.local_rot = 0.0
            self.arm_l_angle = -1.4  # hands up on head
            self.arm_r_angle = 1.4
            self.leg_l_angle = -0.05
            self.leg_r_angle = 0.05
            self.eyebrow_y = -15.0   # high shocked brows
            self.eyebrow_tilt = 0.35
            self.blink_t = 0.0       # eyes wide open!
            if not is_talking:
                self.viseme = Viseme.SURPRISED

        elif pose == "embarrassed_smile":
            self.jump_y = 0.0
            self.head.local_rot = 0.15  # tilted shyly
            self.arm_l_angle = -0.2
            self.arm_r_angle = -1.2     # scratching head
            self.leg_l_angle = 0.05
            self.leg_r_angle = -0.05
            self.eyebrow_y = 3.0
            self.eyebrow_tilt = -0.1
            if not is_talking:
                self.viseme = Viseme.SMILE

        elif pose == "spinning_slip":
            self.jump_y = -30.0 + math.sin(t * 12.0) * 15.0
            self.head.local_rot = math.sin(t * 16.0) * 0.5
            self.arm_l_angle = math.sin(t * 14.0) * 1.5
            self.arm_r_angle = -math.sin(t * 14.0) * 1.5
            self.leg_l_angle = math.cos(t * 14.0) * 1.0
            self.leg_r_angle = -math.cos(t * 14.0) * 1.0
            self.eyebrow_y = -10.0
            self.eyebrow_tilt = -0.2

    def draw(self, cr: cairo.Context):
        """Renders full 2D vector monkey to Cairo context."""
        cr.save()
        cr.translate(self.x, self.y + self.jump_y)
        cr.scale(self.scale * self.facing, self.scale)

        # 1. Ground Shadow (scales smaller and fades when jumping)
        shadow_scale = max(0.4, 1.0 - abs(self.jump_y) / 100.0)
        draw_ellipse(cr, 0, 0, 95 * shadow_scale, 24 * shadow_scale,
                     fill_color=(0.1, 0.1, 0.15, 0.25 * shadow_scale))

        # 2. Tail (curved bezier path behind torso)
        cr.save()
        cr.translate(-25, -160)
        cr.set_source_rgba(*COLOR_FUR)
        cr.set_line_width(20)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(0, 0)
        # Tail wave key points
        c1x = -70 + self.tail_wave * 40
        c1y = 30
        c2x = -110 - self.tail_wave * 30
        c2y = -60
        endx = -80 + self.tail_wave * 20
        endy = -120
        cr.curve_to(c1x, c1y, c2x, c2y, endx, endy)
        cr.stroke_preserve()
        cr.set_source_rgba(*COLOR_OUTLINE)
        cr.set_line_width(4)
        cr.stroke()
        cr.restore()

        # 3. Legs
        # Left Leg (back)
        cr.save()
        cr.translate(-35, -90)
        cr.rotate(self.leg_l_angle)
        draw_capsule(cr, 0, 0, 0, 90, 16, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        # Foot
        draw_ellipse(cr, 8, 95, 26, 15, fill_color=COLOR_MUZZLE, stroke_color=COLOR_OUTLINE, stroke_width=4)
        cr.restore()

        # Right Leg (front)
        cr.save()
        cr.translate(35, -90)
        cr.rotate(self.leg_r_angle)
        draw_capsule(cr, 0, 0, 0, 90, 16, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        # Foot
        draw_ellipse(cr, 8, 95, 26, 15, fill_color=COLOR_MUZZLE, stroke_color=COLOR_OUTLINE, stroke_width=4)
        cr.restore()

        # 4. Torso with Red Vest
        cr.save()
        cr.translate(0, self.torso.local_y + 110)
        cr.rotate(self.torso.local_rot)

        # Body fur base
        draw_ellipse(cr, 0, 0, 68, 85, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)

        # Peach chest patch
        draw_ellipse(cr, 0, 5, 42, 60, fill_color=COLOR_MUZZLE)

        # Red Cartoon Vest
        cr.set_source_rgba(*COLOR_VEST)
        cr.move_to(-52, -55)
        cr.curve_to(-65, 0, -60, 45, -45, 60)
        cr.line_to(-18, 60)
        cr.curve_to(-30, 20, -30, -30, -25, -55)
        cr.close_path()
        cr.fill_preserve()
        cr.set_source_rgba(*COLOR_OUTLINE)
        cr.set_line_width(3.5)
        cr.stroke()

        cr.set_source_rgba(*COLOR_VEST)
        cr.move_to(52, -55)
        cr.curve_to(65, 0, 60, 45, 45, 60)
        cr.line_to(18, 60)
        cr.curve_to(30, 20, 30, -30, 25, -55)
        cr.close_path()
        cr.fill_preserve()
        cr.set_source_rgba(*COLOR_OUTLINE)
        cr.set_line_width(3.5)
        cr.stroke()

        # Vest gold buttons
        draw_ellipse(cr, -12, 10, 5, 5, fill_color=COLOR_VEST_TRIM)
        draw_ellipse(cr, -12, 35, 5, 5, fill_color=COLOR_VEST_TRIM)

        # 5. Arms
        # Left Arm
        cr.save()
        cr.translate(-50, -35)
        cr.rotate(self.arm_l_angle)
        draw_capsule(cr, 0, 0, -25, 75, 15, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, -26, 80, 18, 16, fill_color=COLOR_MUZZLE, stroke_color=COLOR_OUTLINE, stroke_width=4)
        cr.restore()

        # Right Arm
        cr.save()
        cr.translate(50, -35)
        cr.rotate(self.arm_r_angle)
        draw_capsule(cr, 0, 0, 25, 75, 15, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, 26, 80, 18, 16, fill_color=COLOR_MUZZLE, stroke_color=COLOR_OUTLINE, stroke_width=4)
        cr.restore()

        # 6. Head & Face
        cr.save()
        cr.translate(0, -95)
        cr.rotate(self.head.local_rot)

        # Ears
        # Left Ear
        draw_ellipse(cr, -75, -5, 26, 32, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, -75, -5, 16, 20, fill_color=COLOR_INNER_EAR)
        # Right Ear
        draw_ellipse(cr, 75, -5, 26, 32, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, 75, -5, 16, 20, fill_color=COLOR_INNER_EAR)

        # Main Head Circle
        draw_ellipse(cr, 0, -15, 72, 68, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)

        # Cute hair tuft on top
        cr.set_source_rgba(*COLOR_FUR)
        cr.move_to(-15, -82)
        cr.curve_to(0, -112, 10, -108, 0, -82)
        cr.curve_to(15, -105, 25, -95, 12, -80)
        cr.close_path()
        cr.fill_preserve()
        cr.set_source_rgba(*COLOR_OUTLINE)
        cr.set_line_width(3.5)
        cr.stroke()

        # Peach Face Muzzle Mask
        cr.save()
        cr.translate(0, 12)
        draw_ellipse(cr, 0, 0, 52, 36, fill_color=COLOR_MUZZLE, stroke_color=COLOR_OUTLINE, stroke_width=3.5)

        # Nose
        draw_ellipse(cr, 0, -8, 12, 8, fill_color=(0.2, 0.12, 0.08, 1.0))
        # Nose shine
        draw_ellipse(cr, -3, -10, 3, 2, fill_color=(1.0, 1.0, 1.0, 0.7))

        # Mouth Lip-Sync & Expression
        cr.set_source_rgba(*COLOR_OUTLINE)
        cr.set_line_width(3.5)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)

        if self.viseme == Viseme.OPEN_WIDE or self.viseme == Viseme.SURPRISED:
            # Big cartoon open mouth with tongue
            draw_ellipse(cr, 0, 12, 18, 16 + self.mouth_open * 10,
                         fill_color=(0.55, 0.05, 0.05, 1.0), stroke_color=COLOR_OUTLINE, stroke_width=3.5)
            # Tongue
            draw_ellipse(cr, 0, 18 + self.mouth_open * 6, 12, 8, fill_color=(0.95, 0.45, 0.45, 1.0))
        elif self.viseme == Viseme.OPEN_SMALL:
            draw_ellipse(cr, 0, 10, 14, 9 + self.mouth_open * 6,
                         fill_color=(0.55, 0.05, 0.05, 1.0), stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        elif self.viseme == Viseme.ROUND:
            draw_ellipse(cr, 0, 10, 9, 12,
                         fill_color=(0.55, 0.05, 0.05, 1.0), stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        else:
            # Cute smile arc
            cr.move_to(-18, 6)
            cr.curve_to(-8, 18, 8, 18, 18, 6)
            cr.stroke()
            # Dimple tick
            cr.move_to(17, 3)
            cr.line_to(20, 7)
            cr.stroke()

        cr.restore()  # restore muzzle

        # Eyes
        for eye_x in [-24, 24]:
            cr.save()
            cr.translate(eye_x, -28)

            if self.blink_t > 0.8:
                # Closed blinking eye arc
                cr.set_source_rgba(*COLOR_OUTLINE)
                cr.set_line_width(3.5)
                cr.move_to(-14, 0)
                cr.curve_to(-6, 6, 6, 6, 14, 0)
                cr.stroke()
            else:
                # Open Eye
                eye_h = 22 * (1.0 - self.blink_t)
                draw_ellipse(cr, 0, 0, 17, eye_h, fill_color=COLOR_EYE_WHITE, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
                # Iris / Pupil
                pupil_px = self.look_x * 5
                pupil_py = self.look_y * 4
                draw_ellipse(cr, pupil_px, pupil_py, 10, 12 * (1.0 - self.blink_t), fill_color=COLOR_PUPIL)
                # Catchlight twinkle
                draw_ellipse(cr, pupil_px - 3, pupil_py - 4, 3.5, 3.5, fill_color=(1.0, 1.0, 1.0, 0.95))

            cr.restore()

        # Eyebrows
        for is_right, eb_x in [(False, -24), (True, 24)]:
            cr.save()
            cr.translate(eb_x, -48 + self.eyebrow_y)
            rot = self.eyebrow_tilt if not is_right else -self.eyebrow_tilt
            cr.rotate(rot)
            cr.set_source_rgba(*COLOR_OUTLINE)
            cr.set_line_width(4.5)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(-14, 0)
            cr.curve_to(-5, -4, 5, -4, 14, 0)
            cr.stroke()
            cr.restore()

        cr.restore()  # Head restore
        cr.restore()  # Torso restore
        cr.restore()  # Main restore
