# Style library

Generated from `library/styles.json` (that file is the source of truth; add styles there).

**status**: `native` = engine + example in `styles/`, render-verified by design · `adapted` = a written recipe on a native engine; **not render-verified until you QA a render** · `prompt-pack` = prompts for the user's own external tools.

## 2D

| id | status | engine | best for | recipe |
|---|---|---|---|---|
| `inside-out` | native | inside-out | body, health, science, what-if, food | See styles/inside-out/STYLE.md |
| `stick-story` | native | stick-story | survival, life-hack, how-to, preparedness, what-would-you-do | See styles/stick-story/STYLE.md |
| `cartoon-2d` | adapted | inside-out | funny-story, comedy, kids-story, animals, everyday | Inside Out engine; widen palette in lib.js C, add 2-3 exaggerated expressions (squash/stretch via K.man scale), thick ink outline on everything. |
| `minimalist-character` | adapted | stick-story | life, philosophy, mental-health-light, productivity, motivation | Stick Story engine; monochrome + one accent colour, no room details, generous negative space, slow eases. |
| `whiteboard` | adapted | stick-story | education, business, finance, how-to, concept | Stick Story engine on white #FAFAFA, black marker strokes drawn on progressively (stroke-dash reveal), 2 marker colours only. |
| `vector-2d` | adapted | inside-out | tech, product, business, education, science | Inside Out engine; flat geometric shapes, 4-5 colour brand palette, rounded rectangles, no outlines on shapes. |
| `cutout` | adapted | paper-atlas | history, satire, folk-tale, politics, culture | Paper Atlas engine with jointed paper limbs (rotating pivots), visible paper edge shadow, slight jitter at 12 fps. |
| `anime` | adapted | inside-out | action, fantasy, drama, school, sports | Inside Out engine; add speed lines, impact frames, hold frames with limited animation, big eye highlights, dramatic zoom-ins. Original characters only, no existing franchise designs. |
| `traditional-handdrawn` | adapted | inside-out | storytelling, nostalgia, kids-story, fable | Inside Out engine; wobbly line (per-frame vertex jitter at 12 fps), pencil texture, imperfect colour fill offset from line. |
| `frame-by-frame` | adapted | inside-out | art, experimental, music, abstract | Render at 12 fps with deliberate per-frame redraw variance (line boil). Expensive to author; use only when the brief asks for it. |

## 3D

| id | status | engine | best for | recipe |
|---|---|---|---|---|
| `deep-dive` | native | deep-dive | body, health, science, what-if, space | See styles/deep-dive/STYLE.md |
| `night-file` | native | night-file | mystery, true-crime, horror, unsolved, conspiracy | See styles/night-file/STYLE.md |
| `stylized-3d` | adapted | tall-tale | kids-story, adventure, fantasy, everyday | Tall Tale 3D engine: saturated palette, rounded 3D sets, characters stay 2D cut-outs (a fully 3D-modelled character rig is not available in this skill). |
| `pixar-inspired` | adapted | tall-tale | kids-story, emotional, family, adventure | Tall Tale 3D engine: warm key light + cool fill, soft bloom, shallow depth of field, big-eyed original characters, rounded props. Never copy existing characters or designs. |
| `low-poly` | adapted | deep-dive | tech, gaming, nature, space, abstract | Deep Dive engine with flatShading materials, no textures, 6-8 colour palette, simple directional light, no bloom. |
| `clay-3d` | adapted | deep-dive | food, kids-story, comedy, product | Deep Dive engine; soft roughness 0.9, fingerprint-noise bump map, rounded geometry, slightly low 12 fps stepped motion. |
| `realistic-3d` | adapted | deep-dive | science, medicine, engineering, space, architecture | Deep Dive engine with physically based materials, HDR environment, shadows at 2048+, shallow DoF. Needs a GPU for sane render times. |
| `cinematic-3d` | adapted | night-file | thriller, sci-fi, trailer, epic, documentary | Night File engine: single motivated key light, volumetric fog, anamorphic bloom, slow dolly, letterbox bars, teal-orange grade. |
| `3d-cartoon` | adapted | tall-tale | funny-story, kids-story, everyday, animals | Tall Tale 3D engine as-is, bias toward faster cuts and more exaggerated mood states. |
| `isometric` | adapted | deep-dive | tech, business, city, process, architecture | Deep Dive engine with OrthographicCamera at 35.264/45 deg, flat shaded blocks, one accent colour, objects animate in by dropping/extruding. |

## Stylized / artistic

| id | status | engine | best for | recipe |
|---|---|---|---|---|
| `paper-atlas` | native | paper-atlas | history, geography, politics, economics, biography | See styles/paper-atlas/STYLE.md |
| `paper-cut` | adapted | paper-atlas | history, culture, folk-tale, geography, fable | Paper Atlas engine as-is with theme palette swapped for non-history topics. |
| `stop-motion` | adapted | paper-atlas | crafts, kids-story, quirky, product | Paper Atlas engine rendered at 8-12 fps with positional jitter and lighting flicker; hold poses for 2-3 frames. |
| `claymation` | adapted | deep-dive | kids-story, comedy, quirky, food | Same as clay-3d plus 12 fps stepped motion and thumbprint texture; deformation by squash/stretch. |
| `puppet` | adapted | paper-atlas | folk-tale, satire, kids-story, fable | Paper Atlas engine with a proscenium stage frame, rods/strings visible from above, limited jointed motion. |
| `watercolor` | adapted | paper-atlas | nature, travel, poetry, memoir, emotional | Paper Atlas engine; replace flat fills with soft-edged washes (multi-pass blurred shapes), paper grain overlay, colour bleed on transitions. |
| `sketch` | adapted | stick-story | process, design, education, how-to, concept | Stick Story engine; pencil strokes drawn on (dash reveal) over off-white paper, graphite grey + one highlight colour. |
| `storybook` | adapted | paper-atlas | kids-story, fable, fairy-tale, bedtime, folk-tale | Paper Atlas engine; page-turn transitions, soft parallax layers, painterly textures, serif narration captions at bottom. |
| `comic-book` | adapted | inside-out | superhero, action, mystery, sci-fi, adventure | Inside Out engine; halftone dot fills, thick ink, panel borders that reveal, onomatopoeia bursts, motion between panels. |
| `pixel-art` | adapted | inside-out | gaming, retro, tech, nostalgia, comedy | Inside Out engine drawn to a 270x480 offscreen canvas, nearest-neighbour upscaled x4, 16-colour palette, 8-12 fps. |
| `silhouette` | adapted | night-file | horror, folk-tale, mystery, fable, drama | Night File engine or Paper Atlas layers: black figures against coloured gradient backdrops, backlit, no facial detail. |

## Motion & social

| id | status | engine | best for | recipe |
|---|---|---|---|---|
| `motion-graphics` | adapted | inside-out | business, data, economics, finance, marketing | Inside Out engine without hero character; shapes, icons, counters, wipes, grid layouts; brand palette. |
| `kinetic-typography` | adapted | inside-out | motivation, quotes, poetry, music, speech | Inside Out engine captions system promoted to the main visual: word-by-word scale/rotate, big type, background colour shifts on beat. |
| `animated-infographic` | adapted | inside-out | data, economics, finance, geography, news | Inside Out engine; charts drawn from data (bars grow, lines draw, counters tick), one takeaway per shot. |
| `explainer` | adapted | inside-out | education, business, tech, science, how-to | Inside Out engine; problem -> mechanism -> result structure, icons + simple hero. |
| `loop` | adapted | inside-out | satisfying, abstract, mood, product, art | Inside Out engine; design shot so frame at t=0 equals frame at t=duration; no voice or sparse text; 6-15 s. |
| `cinematic-reel` | adapted | night-file | motivation, travel, mood, trailer, brand | Night File engine with warmer grade; letterbox, slow push-ins, typography titles, music-led pacing. |
| `text-image` | adapted | inside-out | news, quotes, facts, listicle, business | Inside Out engine; supplied images with Ken Burns moves and animated text callouts. Images must be user-supplied or original code art. |
| `parallax` | adapted | paper-atlas | storytelling, nature, history, landscape, fairy-tale | Paper Atlas layered cut-outs moved at different speeds on camera pan; 4-6 depth layers. |

## Storytelling

| id | status | engine | best for | recipe |
|---|---|---|---|---|
| `animated-storytelling` | adapted | paper-atlas | story, biography, history, memoir, folk-tale | Pick the engine by genre; this entry is the generic narrative structure from reference/storytelling.md. |
| `character-storytelling` | adapted | tall-tale | story, comedy, drama, everyday, kids-story | Tall Tale 3D if budget allows, else Inside Out/Stick Story with a locked character bible. |

## Hybrid

| id | status | engine | best for | recipe |
|---|---|---|---|---|
| `tall-tale` | native | tall-tale | funny-story, true-story, con, loophole, history-funny | See styles/tall-tale/STYLE.md |
| `mixed-media` | adapted | paper-atlas | art, culture, documentary, memoir, music | Paper Atlas base with 2 other textures (pencil, halftone) following hybrid rules in library/hybrids.json. |

## AI-assisted

| id | status | engine | best for | recipe |
|---|---|---|---|---|
| `ai-assisted` | prompt-pack | - | any | The skill does NOT generate images or video. It writes a scene-by-scene prompt pack with a locked character bible for the user to run in their own tools, then can assemble the returned clips with ffmpeg + captions + audio. |

## Adding a style
1. Append an entry to `library/styles.json` (id, name, family, status, engine, topics, moods, audiences, complexity 1-5, character_need 0-3, recipe).
2. Optionally add tests to `tests/concepts.json`.
3. `scripts/py scripts/select_style.py --self-test`.
4. Make it `native` only after it has its own `styles/<id>/` (style sheet, STYLE.md, rendering example) per SKILL.md "Adding a new style".
