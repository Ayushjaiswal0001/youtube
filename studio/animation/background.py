"""Procedural Multi-Layer 2D Cartoon Backgrounds for 1080x1920 Vertical Video.
Includes parallax layers for:
1. Jungle Clearing (Sunny morning, distant hills, vines, meadow)
2. Forest Path (Sunbeam shafts, winding dirt road, tall trunks, mushrooms)
3. Riverbank (Flowing blue water, animated ripples, sandy shore, reeds, lilies)
4. Cave Entrance (Rocky cavern arch, stalactites, glowing moss, twilight opening)
"""

import math
from typing import Tuple, Dict, Callable
import cairo
from studio.characters.rig_base import draw_ellipse


class BackgroundRenderer:
    """Renders layered vector backgrounds optimized for vertical Shorts/Reels."""

    def __init__(self, width: int = 1080, height: int = 1920):
        self.width = width
        self.height = height

    # The camera pans and zooms over the background, and the parallax shift moves the art
    # itself, so the art is drawn with an overscan margin. Without it a panned frame shows a
    # bare strip at the edge, which the close-up camera exposed.
    OVERSCAN = 1.13

    def render_by_name(self, name: str, cr: cairo.Context, t: float,
                       camera_x: float = 0.0, camera_y: float = 0.0):
        """Dispatches to the requested background renderer with safe default fallback."""
        bg_map: Dict[str, Callable] = {
            "jungle_clearing": self.render_jungle_clearing,
            "forest_path": self.render_forest_path,
            "riverbank": self.render_riverbank,
            "cave_entrance": self.render_cave_entrance,
            "haunted_haveli": self.render_haunted_haveli,
            "village_night": self.render_village_night,
        }
        render_fn = bg_map.get(name, self.render_jungle_clearing)
        cr.save()
        cr.translate(self.width / 2.0, self.height / 2.0)
        cr.scale(self.OVERSCAN, self.OVERSCAN)
        cr.translate(-self.width / 2.0, -self.height / 2.0)
        render_fn(cr, t, camera_x, camera_y)
        cr.restore()

    # -------------------------------------------------------------------------
    # 1. JUNGLE CLEARING
    # -------------------------------------------------------------------------
    def render_jungle_clearing(self, cr: cairo.Context, t: float,
                               camera_x: float = 0.0, camera_y: float = 0.0):
        """Renders vibrant cartoon jungle clearing with animated clouds and swaying foliage."""
        w, h = self.width, self.height

        cr.save()
        cr.translate(-camera_x * 0.3, -camera_y * 0.3)

        # 1. Sky Gradient (Bright sunny morning)
        sky = cairo.LinearGradient(0, 0, 0, h * 0.65)
        sky.add_color_stop_rgb(0.0, 0.35, 0.75, 0.98)
        sky.add_color_stop_rgb(0.6, 0.70, 0.88, 0.99)
        sky.add_color_stop_rgb(1.0, 0.95, 0.92, 0.82)
        cr.rectangle(0, 0, w, h)
        cr.set_source(sky)
        cr.fill()

        # Sun Rays
        cr.save()
        cr.translate(w * 0.85, h * 0.12)
        draw_ellipse(cr, 0, 0, 90, 90, fill_color=(1.0, 0.95, 0.5, 0.85))
        draw_ellipse(cr, 0, 0, 130, 130, fill_color=(1.0, 0.95, 0.5, 0.25))
        cr.restore()

        # 2. Animated Fluffy Clouds
        cloud_offsets = [
            ((t * 18.0) % (w + 400) - 200, h * 0.16, 1.2),
            (((t * 12.0) + 600) % (w + 400) - 200, h * 0.25, 0.9),
            (((t * 15.0) + 300) % (w + 400) - 200, h * 0.08, 0.7)
        ]
        for cx, cy, c_scale in cloud_offsets:
            cr.save()
            cr.translate(cx, cy)
            cr.scale(c_scale, c_scale)
            draw_ellipse(cr, 0, 0, 90, 45, fill_color=(1.0, 1.0, 1.0, 0.85))
            draw_ellipse(cr, -45, 5, 60, 40, fill_color=(1.0, 1.0, 1.0, 0.85))
            draw_ellipse(cr, 45, 5, 65, 40, fill_color=(1.0, 1.0, 1.0, 0.85))
            draw_ellipse(cr, 10, -20, 55, 42, fill_color=(1.0, 1.0, 1.0, 0.92))
            cr.restore()

        # 3. Distant Mountains
        cr.save()
        cr.set_source_rgba(0.40, 0.62, 0.72, 0.75)
        cr.move_to(-50, h * 0.65)
        cr.line_to(w * 0.25, h * 0.48)
        cr.line_to(w * 0.55, h * 0.58)
        cr.line_to(w * 0.85, h * 0.45)
        cr.line_to(w + 50, h * 0.62)
        cr.line_to(w + 50, h)
        cr.line_to(-50, h)
        cr.close_path()
        cr.fill()
        cr.restore()

        # 4. Midground Rolling Hills
        cr.save()
        cr.set_source_rgba(0.28, 0.55, 0.32, 0.90)
        cr.move_to(-50, h * 0.62)
        cr.curve_to(w * 0.3, h * 0.55, w * 0.6, h * 0.66, w + 50, h * 0.58)
        cr.line_to(w + 50, h)
        cr.line_to(-50, h)
        cr.close_path()
        cr.fill()
        cr.restore()

        # 5. Left Jungle Tree & Swaying Vine
        cr.save()
        cr.set_source_rgb(0.42, 0.26, 0.14)
        cr.move_to(-80, 0)
        cr.curve_to(60, h * 0.3, 10, h * 0.6, -20, h)
        cr.line_to(-120, h)
        cr.close_path()
        cr.fill()
        sway_left = math.sin(t * 1.8) * 8.0
        draw_ellipse(cr, 60 + sway_left, h * 0.15, 180, 120, fill_color=(0.18, 0.58, 0.24, 0.95))
        draw_ellipse(cr, 140 + sway_left, h * 0.25, 140, 100, fill_color=(0.24, 0.68, 0.28, 0.95))

        vine_sway = math.sin(t * 2.2) * 20.0
        cr.set_source_rgb(0.20, 0.48, 0.18)
        cr.set_line_width(6.0)
        cr.move_to(80, h * 0.25)
        cr.curve_to(110 + vine_sway, h * 0.42, 70 + vine_sway * 1.5, h * 0.55, 95 + vine_sway * 1.2, h * 0.68)
        cr.stroke()
        draw_ellipse(cr, 105 + vine_sway, h * 0.45, 14, 8, fill_color=(0.30, 0.72, 0.22, 1.0))
        draw_ellipse(cr, 85 + vine_sway * 1.2, h * 0.58, 14, 8, fill_color=(0.30, 0.72, 0.22, 1.0))
        cr.restore()

        # Right Tree Canopy
        cr.save()
        sway_right = math.sin(t * 1.6 + 1.0) * 10.0
        draw_ellipse(cr, w - 40 + sway_right, h * 0.12, 190, 130, fill_color=(0.16, 0.52, 0.22, 0.95))
        draw_ellipse(cr, w - 120 + sway_right, h * 0.22, 150, 100, fill_color=(0.22, 0.64, 0.26, 0.95))
        cr.restore()

        # 6. Foreground Grassy Stage
        cr.save()
        ground = cairo.LinearGradient(0, h * 0.70, 0, h)
        ground.add_color_stop_rgb(0.0, 0.45, 0.78, 0.25)
        ground.add_color_stop_rgb(0.4, 0.32, 0.65, 0.20)
        ground.add_color_stop_rgb(1.0, 0.20, 0.45, 0.14)
        cr.move_to(-50, h * 0.73)
        cr.curve_to(w * 0.35, h * 0.70, w * 0.75, h * 0.74, w + 50, h * 0.72)
        cr.line_to(w + 50, h + 50)
        cr.line_to(-50, h + 50)
        cr.close_path()
        cr.set_source(ground)
        cr.fill()

        # Flowers
        flower_colors = [(0.98, 0.82, 0.15, 1.0), (0.95, 0.35, 0.55, 1.0), (1.0, 1.0, 1.0, 0.9)]
        flower_positions = [
            (140, h * 0.76, 0), (260, h * 0.82, 1),
            (520, h * 0.77, 2), (840, h * 0.80, 0), (960, h * 0.76, 1)
        ]
        for fx, fy, col_idx in flower_positions:
            draw_ellipse(cr, fx, fy, 7, 7, fill_color=flower_colors[col_idx])
            draw_ellipse(cr, fx, fy, 3, 3, fill_color=(0.95, 0.50, 0.10, 1.0))
        cr.restore()

        cr.restore()

    # -------------------------------------------------------------------------
    # 2. FOREST PATH
    # -------------------------------------------------------------------------
    def render_forest_path(self, cr: cairo.Context, t: float,
                           camera_x: float = 0.0, camera_y: float = 0.0):
        """Renders deep forest trail with warm sunbeams, layered timber, and winding earthen road."""
        w, h = self.width, self.height

        cr.save()
        cr.translate(-camera_x * 0.25, -camera_y * 0.25)

        # 1. Canopy Sky Gradient (Amber / Emerald woodland mood)
        sky = cairo.LinearGradient(0, 0, 0, h * 0.6)
        sky.add_color_stop_rgb(0.0, 0.15, 0.38, 0.25) # deep pine green
        sky.add_color_stop_rgb(0.5, 0.35, 0.55, 0.28) # warm foliage filter
        sky.add_color_stop_rgb(1.0, 0.88, 0.80, 0.50) # golden sunbeams
        cr.rectangle(0, 0, w, h)
        cr.set_source(sky)
        cr.fill()

        # 2. Diagonal Golden Sunbeam Shafts (Animated pulse)
        beam_pulse = 0.15 + math.sin(t * 1.5) * 0.05
        cr.save()
        beam_grad = cairo.LinearGradient(w * 0.7, 0, w * 0.3, h * 0.8)
        beam_grad.add_color_stop_rgba(0.0, 1.0, 0.95, 0.6, beam_pulse * 1.5)
        beam_grad.add_color_stop_rgba(1.0, 1.0, 0.90, 0.4, 0.0)

        # Beam polygon 1
        cr.move_to(w * 0.5, 0)
        cr.line_to(w * 0.8, 0)
        cr.line_to(w * 0.4, h * 0.85)
        cr.line_to(w * 0.15, h * 0.85)
        cr.close_path()
        cr.set_source(beam_grad)
        cr.fill()
        cr.restore()

        # 3. Dense Distant Tree Trunks (Layer 1 - deep forest silhouette)
        cr.save()
        cr.set_source_rgba(0.18, 0.28, 0.20, 0.85)
        distant_trunks = [0.15, 0.32, 0.50, 0.68, 0.85]
        for dt in distant_trunks:
            cr.rectangle(w * dt - 18, h * 0.15, 36, h * 0.65)
        cr.fill()
        cr.restore()

        # 4. Dense Midground Foliage
        cr.save()
        for i in range(6):
            tree_x = (i * 220) - 60
            sway = math.sin(t * 1.4 + i) * 6.0
            draw_ellipse(cr, tree_x + sway, h * 0.35, 130, 90, fill_color=(0.14, 0.40, 0.20, 0.92))
            draw_ellipse(cr, tree_x + 50 + sway, h * 0.38, 110, 80, fill_color=(0.20, 0.48, 0.24, 0.92))
        cr.restore()

        # 5. Prominent Foreground Tree Trunks (Left and Right)
        # Left giant oak
        cr.save()
        cr.set_source_rgb(0.36, 0.22, 0.12)
        cr.move_to(-40, 0)
        cr.curve_to(70, h * 0.4, 40, h * 0.7, -30, h)
        cr.line_to(-120, h)
        cr.close_path()
        cr.fill()
        # Bark details
        cr.set_source_rgb(0.28, 0.16, 0.08)
        cr.set_line_width(4)
        cr.move_to(20, h * 0.2); cr.curve_to(35, h * 0.4, 25, h * 0.6, 10, h * 0.8); cr.stroke()
        cr.restore()

        # Right giant oak
        cr.save()
        cr.set_source_rgb(0.38, 0.24, 0.14)
        cr.move_to(w + 40, 0)
        cr.curve_to(w - 70, h * 0.35, w - 50, h * 0.7, w + 30, h)
        cr.line_to(w + 120, h)
        cr.close_path()
        cr.fill()
        cr.restore()

        # 6. Grassy Hillside Base
        cr.save()
        ground = cairo.LinearGradient(0, h * 0.68, 0, h)
        ground.add_color_stop_rgb(0.0, 0.30, 0.56, 0.22)
        ground.add_color_stop_rgb(1.0, 0.18, 0.38, 0.15)
        cr.move_to(-50, h * 0.72)
        cr.curve_to(w * 0.4, h * 0.68, w * 0.7, h * 0.73, w + 50, h * 0.71)
        cr.line_to(w + 50, h + 50)
        cr.line_to(-50, h + 50)
        cr.close_path()
        cr.set_source(ground)
        cr.fill()
        cr.restore()

        # 7. Winding Earthen Dirt Road / Trail through the center
        cr.save()
        trail = cairo.LinearGradient(0, h * 0.70, 0, h)
        trail.add_color_stop_rgb(0.0, 0.78, 0.65, 0.45) # light sunlit dirt
        trail.add_color_stop_rgb(1.0, 0.58, 0.42, 0.28) # warm rich soil
        cr.move_to(w * 0.46, h * 0.69)
        cr.curve_to(w * 0.38, h * 0.76, w * 0.25, h * 0.88, w * 0.15, h + 20)
        cr.line_to(w * 0.92, h + 20)
        cr.curve_to(w * 0.78, h * 0.88, w * 0.62, h * 0.76, w * 0.54, h * 0.69)
        cr.close_path()
        cr.set_source(trail)
        cr.fill()

        # Trail edge stones & cartoon mushrooms
        stones = [(w * 0.28, h * 0.79, 14, 8), (w * 0.72, h * 0.81, 18, 10), (w * 0.35, h * 0.90, 22, 12)]
        for sx, sy, sw, sh in stones:
            draw_ellipse(cr, sx, sy, sw, sh, fill_color=(0.55, 0.52, 0.48, 1.0))
            draw_ellipse(cr, sx - 2, sy - 2, sw * 0.7, sh * 0.7, fill_color=(0.72, 0.70, 0.66, 1.0))

        # Cute red toadstools (mushrooms) on grass border
        mushrooms = [(w * 0.18, h * 0.76), (w * 0.86, h * 0.78)]
        for mx, my in mushrooms:
            # Stalk
            cr.set_source_rgb(0.92, 0.90, 0.85)
            cr.rectangle(mx - 4, my - 6, 8, 14)
            cr.fill()
            # Red cap
            draw_ellipse(cr, mx, my - 8, 16, 12, fill_color=(0.90, 0.22, 0.18, 1.0))
            # White dots
            draw_ellipse(cr, mx - 6, my - 10, 3, 3, fill_color=(1.0, 1.0, 1.0, 0.95))
            draw_ellipse(cr, mx + 5, my - 9, 2.5, 2.5, fill_color=(1.0, 1.0, 1.0, 0.95))
            draw_ellipse(cr, mx, my - 13, 3, 3, fill_color=(1.0, 1.0, 1.0, 0.95))
        cr.restore()

        cr.restore()

    # -------------------------------------------------------------------------
    # 3. RIVERBANK
    # -------------------------------------------------------------------------
    def render_riverbank(self, cr: cairo.Context, t: float,
                         camera_x: float = 0.0, camera_y: float = 0.0):
        """Renders sunny riverbank with flowing cyan water, ripples, sandy bank, and reeds."""
        w, h = self.width, self.height

        cr.save()
        cr.translate(-camera_x * 0.3, -camera_y * 0.3)

        # 1. Sky Gradient (Bright afternoon breeze)
        sky = cairo.LinearGradient(0, 0, 0, h * 0.5)
        sky.add_color_stop_rgb(0.0, 0.30, 0.68, 0.95)
        sky.add_color_stop_rgb(0.6, 0.65, 0.85, 0.98)
        sky.add_color_stop_rgb(1.0, 0.92, 0.95, 0.98)
        cr.rectangle(0, 0, w, h)
        cr.set_source(sky)
        cr.fill()

        # Sun over water
        cr.save()
        cr.translate(w * 0.25, h * 0.14)
        draw_ellipse(cr, 0, 0, 75, 75, fill_color=(1.0, 0.92, 0.45, 0.90))
        draw_ellipse(cr, 0, 0, 115, 115, fill_color=(1.0, 0.95, 0.6, 0.22))
        cr.restore()

        # 2. Far River Shore (Lush green hills across the water)
        cr.save()
        cr.set_source_rgba(0.24, 0.58, 0.35, 0.88)
        cr.move_to(-50, h * 0.45)
        cr.curve_to(w * 0.3, h * 0.40, w * 0.7, h * 0.48, w + 50, h * 0.42)
        cr.line_to(w + 50, h * 0.55)
        cr.line_to(-50, h * 0.55)
        cr.close_path()
        cr.fill()
        cr.restore()

        # 3. Flowing Blue River Body
        cr.save()
        river = cairo.LinearGradient(0, h * 0.44, 0, h * 0.74)
        river.add_color_stop_rgb(0.0, 0.20, 0.55, 0.82) # deeper azure
        river.add_color_stop_rgb(0.5, 0.32, 0.72, 0.88) # bright turquoise
        river.add_color_stop_rgb(1.0, 0.45, 0.82, 0.92) # shallow shore shimmer
        cr.rectangle(0, h * 0.44, w, h * 0.32)
        cr.set_source(river)
        cr.fill()

        # Animated Water Ripples (Sine waves drifting right)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for row in range(5):
            ry = h * 0.48 + row * 45
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.35 - row * 0.04)
            cr.set_line_width(4.0 - row * 0.4)
            cr.move_to(0, ry)
            offset = t * 60.0 * (1.0 + row * 0.2)
            for x in range(0, w + 60, 40):
                wave_y = ry + math.sin((x + offset) * 0.04) * 6.0
                cr.line_to(x, wave_y)
            cr.stroke()

        # Floating Lily Pads on river
        lilies = [(w * 0.18, h * 0.58), (w * 0.65, h * 0.52), (w * 0.42, h * 0.66)]
        for lx, ly in lilies:
            bob = math.sin(t * 3.0 + lx) * 3.0
            draw_ellipse(cr, lx, ly + bob, 32, 14, fill_color=(0.18, 0.62, 0.28, 0.90))
            # Pink water lily blossom
            draw_ellipse(cr, lx + 6, ly + bob - 4, 8, 8, fill_color=(0.98, 0.45, 0.72, 1.0))
            draw_ellipse(cr, lx + 6, ly + bob - 4, 3, 3, fill_color=(1.0, 0.95, 0.3, 1.0))
        cr.restore()

        # 4. Foreground Sandy Pebble Shoreline
        cr.save()
        shore = cairo.LinearGradient(0, h * 0.70, 0, h)
        shore.add_color_stop_rgb(0.0, 0.92, 0.84, 0.62) # bright wet golden sand
        shore.add_color_stop_rgb(0.3, 0.82, 0.72, 0.48) # dry sand
        shore.add_color_stop_rgb(1.0, 0.45, 0.68, 0.28) # shoreline grass transition
        cr.move_to(-50, h * 0.71)
        cr.curve_to(w * 0.35, h * 0.68, w * 0.65, h * 0.74, w + 50, h * 0.70)
        cr.line_to(w + 50, h + 50)
        cr.line_to(-50, h + 50)
        cr.close_path()
        cr.set_source(shore)
        cr.fill()

        # Shoreline smooth colored pebbles
        pebbles = [
            (w * 0.12, h * 0.73, 16, 9, (0.6, 0.58, 0.55)),
            (w * 0.28, h * 0.76, 20, 11, (0.75, 0.68, 0.60)),
            (w * 0.55, h * 0.74, 14, 8, (0.85, 0.80, 0.72)),
            (w * 0.82, h * 0.77, 24, 13, (0.52, 0.50, 0.48)),
            (w * 0.92, h * 0.73, 18, 10, (0.70, 0.62, 0.52))
        ]
        for px, py, pw, ph, pcol in pebbles:
            draw_ellipse(cr, px, py, pw, ph, fill_color=(*pcol, 1.0))
            draw_ellipse(cr, px - 2, py - 2, pw * 0.6, ph * 0.6, fill_color=(1.0, 1.0, 1.0, 0.25))

        # Reeds / Cattails on Left & Right Bank
        cr.set_line_width(5.0)
        cr.set_source_rgb(0.28, 0.54, 0.22)
        reed_bases = [50, 80, 110, w - 80, w - 50]
        for rbx in reed_bases:
            reed_sway = math.sin(t * 2.0 + rbx) * 12.0
            cr.move_to(rbx, h * 0.78)
            cr.curve_to(rbx + reed_sway * 0.5, h * 0.68, rbx + reed_sway, h * 0.60, rbx + reed_sway * 1.2, h * 0.52)
            cr.stroke()
            # Brown cattail sausage on top
            draw_ellipse(cr, rbx + reed_sway * 1.1, h * 0.56, 7, 20, fill_color=(0.42, 0.22, 0.12, 1.0))
        cr.restore()

        cr.restore()

    # -------------------------------------------------------------------------
    # 4. CAVE ENTRANCE
    # -------------------------------------------------------------------------
    def render_cave_entrance(self, cr: cairo.Context, t: float,
                             camera_x: float = 0.0, camera_y: float = 0.0):
        """Renders atmospheric rocky cavern arch with glowing crystals and twilight exterior."""
        w, h = self.width, self.height

        cr.save()
        cr.translate(-camera_x * 0.2, -camera_y * 0.2)

        # 1. Exterior Sky through Arch (Twilight Purple-Blue with Moon)
        sky = cairo.LinearGradient(0, 0, 0, h * 0.7)
        sky.add_color_stop_rgb(0.0, 0.08, 0.08, 0.20) # deep midnight indigo
        sky.add_color_stop_rgb(0.6, 0.18, 0.15, 0.35) # twilight violet
        sky.add_color_stop_rgb(1.0, 0.35, 0.25, 0.45) # dusk horizon
        cr.rectangle(0, 0, w, h)
        cr.set_source(sky)
        cr.fill()

        # Glowing Crescent Moon & Stars in opening
        cr.save()
        cr.translate(w * 0.52, h * 0.22)
        draw_ellipse(cr, 0, 0, 42, 42, fill_color=(1.0, 0.95, 0.80, 0.95))
        draw_ellipse(cr, 12, -4, 36, 36, fill_color=(0.08, 0.08, 0.20, 1.0)) # moon shadow cutout
        cr.restore()

        # Twinkling stars
        stars = [(w * 0.38, h * 0.16), (w * 0.65, h * 0.18), (w * 0.45, h * 0.28), (w * 0.58, h * 0.32)]
        for sx, sy in stars:
            s_pulse = 0.5 + 0.5 * math.sin(t * 4.0 + sx)
            draw_ellipse(cr, sx, sy, 3 * s_pulse, 3 * s_pulse, fill_color=(1.0, 1.0, 0.9, 0.85))

        # 2. Giant Rocky Cavern Arch (Framing the scene from top and sides)
        cr.save()
        cr.set_source_rgb(0.14, 0.14, 0.18) # dark charcoal cave stone

        # Left cavern wall & arch
        cr.move_to(-40, -40)
        cr.line_to(w + 40, -40)
        cr.line_to(w + 40, h + 40)
        cr.line_to(-40, h + 40)
        cr.close_path()

        # Subtractive opening for the archway
        cr.move_to(w * 0.20, h * 0.70)
        cr.curve_to(w * 0.18, h * 0.15, w * 0.82, h * 0.15, w * 0.80, h * 0.70)
        cr.close_path()
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.fill()
        cr.restore()

        # 3. Hanging Stalactites from ceiling
        stalactites = [
            (w * 0.25, h * 0.24, 40, 90),
            (w * 0.38, h * 0.18, 30, 70),
            (w * 0.62, h * 0.19, 35, 80),
            (w * 0.75, h * 0.25, 45, 100),
            (w * 0.12, h * 0.35, 50, 120),
            (w * 0.88, h * 0.38, 55, 130),
        ]
        cr.save()
        for st_x, st_y, st_w, st_h in stalactites:
            cr.set_source_rgb(0.18, 0.18, 0.24)
            cr.move_to(st_x - st_w / 2, st_y)
            cr.line_to(st_x + st_w / 2, st_y)
            cr.line_to(st_x, st_y + st_h)
            cr.close_path()
            cr.fill()
            # Highlight ridge
            cr.set_source_rgba(0.30, 0.30, 0.38, 0.6)
            cr.set_line_width(2.5)
            cr.move_to(st_x - st_w * 0.2, st_y)
            cr.line_to(st_x, st_y + st_h)
            cr.stroke()
        cr.restore()

        # 4. Mysterious Glowing Cyan Crystals on Cave Walls
        crystal_glow = 0.65 + 0.35 * math.sin(t * 3.0)
        crystals = [
            (w * 0.08, h * 0.55, 20, 40),
            (w * 0.14, h * 0.62, 16, 32),
            (w * 0.86, h * 0.58, 22, 45),
            (w * 0.92, h * 0.65, 18, 35)
        ]
        cr.save()
        for cx, cy, cw, ch in crystals:
            # Halo glow
            draw_ellipse(cr, cx, cy, cw * 2.2, ch * 1.5, fill_color=(0.10, 0.85, 0.95, 0.18 * crystal_glow))
            # Crystal body
            cr.set_source_rgba(0.20, 0.95, 0.90, 0.90)
            cr.move_to(cx, cy - ch / 2)
            cr.line_to(cx + cw / 2, cy)
            cr.line_to(cx, cy + ch / 2)
            cr.line_to(cx - cw / 2, cy)
            cr.close_path()
            cr.fill()
            # Core bright highlight
            draw_ellipse(cr, cx, cy, cw * 0.3, ch * 0.3, fill_color=(0.95, 1.0, 1.0, 0.95))
        cr.restore()

        # 5. Rocky Cavern Ground Stage
        cr.save()
        ground = cairo.LinearGradient(0, h * 0.68, 0, h)
        ground.add_color_stop_rgb(0.0, 0.22, 0.22, 0.28) # shadowed stone
        ground.add_color_stop_rgb(0.4, 0.16, 0.16, 0.22)
        ground.add_color_stop_rgb(1.0, 0.10, 0.10, 0.14)
        cr.move_to(-50, h * 0.70)
        cr.curve_to(w * 0.3, h * 0.72, w * 0.7, h * 0.69, w + 50, h * 0.71)
        cr.line_to(w + 50, h + 50)
        cr.line_to(-50, h + 50)
        cr.close_path()
        cr.set_source(ground)
        cr.fill()

        # Floor boulders / rocks
        floor_rocks = [
            (w * 0.15, h * 0.75, 45, 22),
            (w * 0.32, h * 0.78, 30, 16),
            (w * 0.68, h * 0.76, 38, 18),
            (w * 0.88, h * 0.74, 55, 26)
        ]
        for rx, ry, rw, rh in floor_rocks:
            draw_ellipse(cr, rx, ry, rw, rh, fill_color=(0.14, 0.14, 0.18, 1.0))
            draw_ellipse(cr, rx - 3, ry - 3, rw * 0.6, rh * 0.6, fill_color=(0.25, 0.25, 0.32, 0.6))
        cr.restore()

        cr.restore()


    # -------------------------------------------------------------------------
    # 5. HAUNTED HAVELI
    # -------------------------------------------------------------------------
    def render_haunted_haveli(self, cr: cairo.Context, t: float,
                              camera_x: float = 0.0, camera_y: float = 0.0):
        """Moonlit haunted haveli facade with flickering windows and drifting fog."""
        w, h = self.width, self.height
        cr.save()
        cr.translate(-camera_x * 0.25, -camera_y * 0.25)

        sky = cairo.LinearGradient(0, 0, 0, h * 0.8)
        sky.add_color_stop_rgb(0.0, 0.035, 0.045, 0.11)
        sky.add_color_stop_rgb(0.55, 0.11, 0.09, 0.22)
        sky.add_color_stop_rgb(1.0, 0.22, 0.14, 0.25)
        cr.rectangle(0, 0, w, h)
        cr.set_source(sky)
        cr.fill()

        # Moon and halo
        glow = 0.55 + 0.12 * math.sin(t * 1.2)
        draw_ellipse(cr, w * 0.78, h * 0.16, 125, 125,
                     fill_color=(0.65, 0.72, 0.95, 0.10 * glow))
        draw_ellipse(cr, w * 0.78, h * 0.16, 74, 74,
                     fill_color=(0.88, 0.90, 0.78, 0.92))
        draw_ellipse(cr, w * 0.78 + 16, h * 0.16 - 8, 64, 64,
                     fill_color=(0.035, 0.045, 0.11, 1.0))

        # Stars
        stars = [
            (w * 0.12, h * 0.08, 2.4), (w * 0.25, h * 0.15, 1.8),
            (w * 0.42, h * 0.07, 2.0), (w * 0.56, h * 0.19, 2.8),
            (w * 0.90, h * 0.09, 2.1), (w * 0.68, h * 0.28, 1.6),
            (w * 0.18, h * 0.27, 1.5), (w * 0.47, h * 0.30, 1.9),
        ]
        for sx, sy, sr in stars:
            pulse = 0.55 + 0.45 * math.sin(t * 2.4 + sx * 0.05)
            draw_ellipse(cr, sx, sy, sr * pulse, sr * pulse,
                         fill_color=(1.0, 0.98, 0.82, 0.85))

        # Distant treeline
        cr.set_source_rgba(0.035, 0.06, 0.07, 0.95)
        cr.move_to(-20, h * 0.58)
        cr.curve_to(w * 0.18, h * 0.50, w * 0.30, h * 0.60, w * 0.48, h * 0.54)
        cr.curve_to(w * 0.68, h * 0.47, w * 0.82, h * 0.58, w + 20, h * 0.52)
        cr.line_to(w + 20, h * 0.76)
        cr.line_to(-20, h * 0.76)
        cr.close_path()
        cr.fill()

        # Haveli silhouette
        facade = (0.16, 0.13, 0.16)
        cr.set_source_rgb(*facade)
        cr.rectangle(w * 0.12, h * 0.34, w * 0.76, h * 0.40)
        cr.fill()

        # Central upper storey and domes
        cr.rectangle(w * 0.35, h * 0.25, w * 0.30, h * 0.12)
        cr.fill()
        draw_ellipse(cr, w * 0.50, h * 0.245, 92, 58, fill_color=(*facade, 1.0))
        draw_ellipse(cr, w * 0.50, h * 0.23, 52, 40, fill_color=(0.20, 0.16, 0.19, 1.0))
        cr.set_source_rgb(*facade)
        cr.rectangle(w * 0.487, h * 0.16, w * 0.026, h * 0.09)
        cr.fill()
        draw_ellipse(cr, w * 0.50, h * 0.16, 32, 32, fill_color=(*facade, 1.0))

        # Side minarets
        for x in (w * 0.16, w * 0.80):
            cr.set_source_rgb(*facade)
            cr.rectangle(x, h * 0.30, 42, h * 0.43)
            cr.fill()
            draw_ellipse(cr, x + 21, h * 0.29, 38, 38, fill_color=(*facade, 1.0))
            cr.set_source_rgb(0.24, 0.19, 0.18)
            cr.rectangle(x - 7, h * 0.335, 56, 14)
            cr.fill()

        # Cornice and stone bands
        cr.set_source_rgb(0.25, 0.20, 0.19)
        cr.rectangle(w * 0.10, h * 0.335, w * 0.80, 18)
        cr.fill()
        cr.rectangle(w * 0.10, h * 0.415, w * 0.80, 10)
        cr.fill()

        # Windows: left dark, center amber, right broken
        win_y = h * 0.43
        win_w, win_h = 86, 130
        input_glow = 0.72 + 0.12 * math.sin(t * 7.1) + 0.06 * math.sin(t * 13.7)
        for wx in (w * 0.24, w * 0.62):
            cr.set_source_rgba(0.06, 0.065, 0.07, 1.0)
            cr.rectangle(wx, win_y, win_w, win_h)
            cr.fill()
            cr.set_source_rgb(0.30, 0.24, 0.18)
            cr.set_line_width(6)
            cr.rectangle(wx, win_y, win_w, win_h)
            cr.stroke()
            cr.set_line_width(3)
            cr.move_to(wx + win_w / 2, win_y)
            cr.line_to(wx + win_w / 2, win_y + win_h)
            cr.move_to(wx, win_y + win_h / 2)
            cr.line_to(wx + win_w, win_y + win_h / 2)
            cr.stroke()

        # Warm flickering window on the right
        right_x = w * 0.62
        draw_ellipse(cr, right_x + win_w / 2, win_y + win_h / 2, 105, 125,
                     fill_color=(1.0, 0.60, 0.12, 0.11 * input_glow))
        cr.set_source_rgba(1.0, 0.66, 0.18, 0.72 * input_glow)
        cr.rectangle(right_x + 8, win_y + 8, win_w - 16, win_h - 16)
        cr.fill()
        cr.set_source_rgba(0.25, 0.12, 0.05, 0.45)
        cr.set_line_width(3)
        cr.move_to(right_x + win_w / 2, win_y)
        cr.line_to(right_x + win_w / 2, win_y + win_h)
        cr.move_to(right_x, win_y + win_h / 2)
        cr.line_to(right_x + win_w, win_y + win_h / 2)
        cr.stroke()

        # Broken window on the left: jagged remaining glass
        left_x = w * 0.24
        cr.save()
        cr.set_source_rgba(0.30, 0.38, 0.42, 0.55)
        cr.move_to(left_x + 8, win_y + 8)
        cr.line_to(left_x + 34, win_y + 12)
        cr.line_to(left_x + 22, win_y + 52)
        cr.line_to(left_x + 50, win_y + 38)
        cr.line_to(left_x + 42, win_y + 92)
        cr.line_to(left_x + 12, win_y + 80)
        cr.close_path()
        cr.fill()
        cr.restore()
        cr.set_source_rgba(0.02, 0.02, 0.03, 0.8)
        cr.move_to(left_x + 46, win_y + 64)
        cr.line_to(left_x + 78, win_y + 74)
        cr.line_to(left_x + 62, win_y + 102)
        cr.line_to(left_x + 70, win_y + 122)
        cr.line_to(left_x + 40, win_y + 118)
        cr.close_path()
        cr.fill()

        # Grand arched door
        door_x, door_y = w * 0.43, h * 0.60
        door_w, door_h = w * 0.14, h * 0.14
        cr.set_source_rgba(0.025, 0.025, 0.03, 1.0)
        cr.move_to(door_x, door_y + door_h)
        cr.line_to(door_x, door_y + door_h * 0.35)
        cr.curve_to(door_x, door_y - 10, door_x + door_w, door_y - 10,
                    door_x + door_w, door_y + door_h * 0.35)
        cr.line_to(door_x + door_w, door_y + door_h)
        cr.close_path()
        cr.fill()
        cr.set_source_rgb(0.27, 0.18, 0.12)
        cr.set_line_width(9)
        cr.move_to(door_x - 4, door_y + door_h)
        cr.line_to(door_x - 4, door_y + door_h * 0.35)
        cr.curve_to(door_x - 4, door_y - 18, door_x + door_w + 4, door_y - 18,
                    door_x + door_w + 4, door_y + door_h * 0.35)
        cr.line_to(door_x + door_w + 4, door_y + door_h)
        cr.stroke()
        draw_ellipse(cr, door_x + door_w * 0.76, door_y + door_h * 0.62,
                     5, 5, fill_color=(0.75, 0.60, 0.25, 0.85))

        # Crumbling plinth and foreground courtyard
        cr.set_source_rgb(0.12, 0.10, 0.12)
        cr.rectangle(-20, h * 0.73, w + 40, h * 0.27)
        cr.fill()

        ground = cairo.LinearGradient(0, h * 0.74, 0, h)
        ground.add_color_stop_rgb(0.0, 0.19, 0.16, 0.17)
        ground.add_color_stop_rgb(0.55, 0.12, 0.11, 0.12)
        ground.add_color_stop_rgb(1.0, 0.055, 0.055, 0.06)
        cr.set_source(ground)
        cr.rectangle(0, h * 0.74, w, h * 0.26)
        cr.fill()

        # Path to the door
        cr.set_source_rgba(0.25, 0.22, 0.20, 0.65)
        cr.move_to(w * 0.40, h)
        cr.line_to(w * 0.47, h * 0.75)
        cr.line_to(w * 0.56, h * 0.75)
        cr.line_to(w * 0.66, h)
        cr.close_path()
        cr.fill()

        # A few dead branches
        cr.set_source_rgb(0.10, 0.08, 0.09)
        cr.set_line_width(10)
        for bx, by, dx, dy in [
            (w * 0.05, h * 0.79, 130, -180),
            (w * 0.96, h * 0.81, -120, -160),
        ]:
            cr.move_to(bx, by)
            cr.curve_to(bx + dx * 0.4, by + dy * 0.5,
                        bx + dx * 0.7, by + dy * 0.8,
                        bx + dx, by + dy)
            cr.stroke()

        # Drifting fog bands
        for i, y_frac in enumerate((0.70, 0.78, 0.86)):
            fog = cairo.LinearGradient(0, 0, w, 0)
            fog.add_color_stop_rgba(0.0, 0.55, 0.62, 0.68, 0.0)
            fog.add_color_stop_rgba(0.35, 0.55, 0.62, 0.68, 0.10 + i * 0.02)
            fog.add_color_stop_rgba(0.65, 0.55, 0.62, 0.68, 0.08 + i * 0.02)
            fog.add_color_stop_rgba(1.0, 0.55, 0.62, 0.68, 0.0)
            shift = math.sin(t * 0.5 + i) * 80
            cr.save()
            cr.translate(shift, 0)
            cr.rectangle(-100, h * y_frac, w + 200, 90 + i * 18)
            cr.set_source(fog)
            cr.fill()
            cr.restore()

        # Fireflies
        for i in range(6):
            fx = (w * 0.15 + i * 137 + math.sin(t * 0.8 + i) * 28) % w
            fy = h * 0.68 + math.cos(t * 1.1 + i * 1.7) * 70
            fp = 0.4 + 0.6 * math.sin(t * 3.0 + i * 2.1) ** 2
            draw_ellipse(cr, fx, fy, 4 * fp, 4 * fp,
                         fill_color=(1.0, 0.78, 0.25, 0.75 * fp))

        cr.restore()

    # -------------------------------------------------------------------------
    # 6. VILLAGE NIGHT
    # -------------------------------------------------------------------------
    def render_village_night(self, cr: cairo.Context, t: float,
                             camera_x: float = 0.0, camera_y: float = 0.0):
        """Quiet village at night with warm hut windows and a moonlit path."""
        w, h = self.width, self.height
        cr.save()
        cr.translate(-camera_x * 0.22, -camera_y * 0.22)

        sky = cairo.LinearGradient(0, 0, 0, h * 0.75)
        sky.add_color_stop_rgb(0.0, 0.02, 0.04, 0.10)
        sky.add_color_stop_rgb(0.55, 0.07, 0.10, 0.22)
        sky.add_color_stop_rgb(1.0, 0.22, 0.17, 0.22)
        cr.rectangle(0, 0, w, h)
        cr.set_source(sky)
        cr.fill()

        draw_ellipse(cr, w * 0.18, h * 0.15, 90, 90, fill_color=(0.85, 0.88, 0.78, 0.18))
        draw_ellipse(cr, w * 0.18, h * 0.15, 48, 48, fill_color=(0.92, 0.93, 0.82, 0.95))
        draw_ellipse(cr, w * 0.18 + 13, h * 0.15 - 5, 41, 41, fill_color=(0.02, 0.04, 0.10, 1.0))

        for i in range(14):
            sx = (i * 173 + 40) % w
            sy = h * (0.04 + ((i * 37) % 24) / 100.0)
            pulse = 0.45 + 0.55 * math.sin(t * 2.0 + i)
            draw_ellipse(cr, sx, sy, 1.8 * pulse, 1.8 * pulse,
                         fill_color=(1.0, 0.96, 0.76, 0.75))

        # Hills and treeline
        cr.set_source_rgb(0.055, 0.09, 0.07)
        cr.move_to(-20, h * 0.56)
        cr.curve_to(w * 0.22, h * 0.48, w * 0.50, h * 0.62, w * 0.75, h * 0.52)
        cr.curve_to(w * 0.88, h * 0.47, w * 0.96, h * 0.54, w + 20, h * 0.50)
        cr.line_to(w + 20, h)
        cr.line_to(-20, h)
        cr.close_path()
        cr.fill()

        # Huts with warm windows
        huts = [(w * 0.08, w * 0.20, h * 0.57, 0.55),
                (w * 0.38, w * 0.24, h * 0.59, 0.75),
                (w * 0.70, w * 0.22, h * 0.56, 0.62)]
        for hx, hw, hy, scale in huts:
            cr.set_source_rgb(0.15, 0.10, 0.08)
            cr.rectangle(hx, hy, hw, h * 0.18)
            cr.fill()
            cr.set_source_rgb(0.22, 0.13, 0.08)
            cr.move_to(hx - hw * 0.08, hy)
            cr.line_to(hx + hw * 0.5, hy - h * 0.07)
            cr.line_to(hx + hw * 1.08, hy)
            cr.close_path()
            cr.fill()
            # Door
            cr.set_source_rgb(0.07, 0.045, 0.035)
            cr.rectangle(hx + hw * 0.42, hy + h * 0.08, hw * 0.20, h * 0.10)
            cr.fill()
            # Window
            wx = hx + hw * 0.18
            wy = hy + h * 0.045
            flicker = 0.78 + 0.12 * math.sin(t * 5.3 + hx * 0.01)
            draw_ellipse(cr, wx + hw * 0.12, wy + h * 0.03,
                         hw * 0.22, h * 0.05,
                         fill_color=(1.0, 0.62, 0.14, 0.12 * flicker))
            cr.set_source_rgba(1.0, 0.68, 0.20, 0.75 * flicker)
            cr.rectangle(wx, wy, hw * 0.24, h * 0.06)
            cr.fill()
            cr.set_source_rgba(0.18, 0.09, 0.04, 0.8)
            cr.set_line_width(3)
            cr.move_to(wx + hw * 0.12, wy)
            cr.line_to(wx + hw * 0.12, wy + h * 0.06)
            cr.move_to(wx, wy + h * 0.03)
            cr.line_to(wx + hw * 0.24, wy + h * 0.03)
            cr.stroke()

        # Trees
        cr.set_source_rgb(0.055, 0.07, 0.055)
        for tx, ty, tr in [(w * 0.30, h * 0.60, 1.2), (w * 0.60, h * 0.61, 0.9),
                           (w * 0.95, h * 0.58, 1.1)]:
            cr.rectangle(tx - 8, ty, 16, h * 0.20)
            cr.fill()
            draw_ellipse(cr, tx, ty - 12, 56 * tr, 72 * tr, fill_color=(0.06, 0.10, 0.07, 1.0))

        # Ground and path
        ground = cairo.LinearGradient(0, h * 0.72, 0, h)
        ground.add_color_stop_rgb(0.0, 0.14, 0.13, 0.11)
        ground.add_color_stop_rgb(0.5, 0.10, 0.09, 0.08)
        ground.add_color_stop_rgb(1.0, 0.05, 0.05, 0.05)
        cr.set_source(ground)
        cr.rectangle(0, h * 0.72, w, h * 0.28)
        cr.fill()
        cr.set_source_rgba(0.32, 0.28, 0.22, 0.55)
        cr.move_to(w * 0.42, h)
        cr.line_to(w * 0.47, h * 0.74)
        cr.line_to(w * 0.55, h * 0.74)
        cr.line_to(w * 0.62, h)
        cr.close_path()
        cr.fill()

        # Low fog
        fog = cairo.LinearGradient(0, 0, w, 0)
        fog.add_color_stop_rgba(0.0, 0.65, 0.72, 0.82, 0.0)
        fog.add_color_stop_rgba(0.45, 0.65, 0.72, 0.82, 0.08)
        fog.add_color_stop_rgba(1.0, 0.65, 0.72, 0.82, 0.0)
        cr.save()
        cr.translate(math.sin(t * 0.4) * 50, 0)
        cr.rectangle(-100, h * 0.77, w + 200, 80)
        cr.set_source(fog)
        cr.fill()
        cr.restore()

        cr.restore()
