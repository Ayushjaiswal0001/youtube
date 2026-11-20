# Character & visual consistency system

`scripts/preproduction.py` creates `preproduction/bible.json`. **Fill every `LOCKED` field before building**; `qc.py` fails a project whose characters are mostly empty.

## Character sheet (one per recurring character)
`face` (head shape, eyes, brows, nose, mouth) · `hair_or_hat` · `clothing` (every item + colour) · `body_proportions` (head:body ratio, height class) · `colour_scheme` (hex list) · `signature_prop` · `personality_in_motion` (how they walk, react, gesture) · `default_expression` · `expression_set`.

## Environment sheet (one per location)
Layout (left→right list of objects), palette, key props and their positions, light direction + colour, time of day, camera positions already used.

## Rules
1. Write the sheet once, reuse the exact words in every shot description and every external prompt.
2. In code styles, put the character in ONE function/const (look object) and call it in every shot. Never re-type colours inline.
3. A costume or location change is an explicit storyboard row, never an accident.
4. Props live with one owner at a time.
5. Screen direction: exit right → enter left, unless a turn-around is shown.
6. Hybrids: palette lock, line-weight lock, light lock, frame-rate lock from `library/hybrids.json`.
7. QA by comparing the first, middle and last frame of the contact sheet side by side. `qc.py` cannot see this; Claude must look.

## For external AI tools (prompt-pack only)
Reuse the same character paragraph word for word, same seed/reference image if the tool supports it, and re-check after every generation. Drift is the norm; budget for re-rolls.
