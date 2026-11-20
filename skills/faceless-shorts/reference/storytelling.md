# Visual storytelling engine

Every shot must earn its place: it shows what the line says, advances the story, and sets up the next shot. Use this
as a checklist while writing `preproduction/storyboard` and `src/shots.js`.

## Beat structure (what `preproduction.py` assigns per line)
| beat | job | default shot | default camera |
|---|---|---|---|
| hook | the first frame already shows the surprise or question | subject + object, centred | slow push-in |
| build | explain one idea per shot | wide / cutaway / diagram | pan or lateral dolly |
| turn | the twist ("but", "until", myth) | close-up on the detail or reaction | punch-in on the key word |
| payoff | the consequence | wide reveal | crane up / pull-back |
| close | punchy last line that loops to the hook | subject to camera | hold |

## Per-shot decisions (write all of them in the storyboard row)
- **Composition:** one subject, one secondary element, nothing else. Subject off the caption band (y 1250-1550 on 9:16) and the platform UI margins (`library/platforms.json`).
- **Expression / acting:** a face change on every beat (neutral → shock → smirk). Characters look at camera only on the twist or last line.
- **Movement:** every shot has camera motion; subject motion starts a few frames after the cut, ends before the next one.
- **Camera angle:** eye level = neutral; low = power/awe; high = vulnerability/overview; close-up = emotion or a key detail; wide = place and scale.
- **Light & shadow:** one direction per scene (`bible.json` `light_rule`). Mood by temperature: warm = safe/funny, cool = clinical/eerie, red accent = danger.
- **Background:** defined once per environment; new angle = same objects in the same places.
- **Colour:** palette lock (max 6 colours). Colour carries meaning (danger red, x-ray cyan) and never changes meaning mid-video.
- **Transition:** hard cut + whoosh by default; match-cut on shape or motion when possible; fades only for time passing. No decorative wipes.
- **Pacing:** cut every 1.5-3.5 s on 9:16; split any line over ~5 s into two shots; end 0.9 s after the last word.
- **Emotional arc:** curiosity → escalation → surprise → resolution. If two shots in a row feel the same, cut one or change the emotion.

## Test for "does this scene contribute?"
Cover the caption and mute the audio: can you still tell what is happening and what the character feels? If not, the shot is decoration. Fix or cut it.
