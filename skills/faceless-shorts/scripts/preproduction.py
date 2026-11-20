#!/usr/bin/env python3
"""Pre-production pack for a short (standard library only).

  scripts/py scripts/preproduction.py <project> --brief "the idea" [--platform shorts] [--duration 35]
        [--style <id>] [--accent <id>] [--characters "Mia: 8-year-old girl, red raincoat; Rex: grey tabby"]
        [--prompts]            # also write prompts.md for the user's OWN external AI tools (never run by this skill)

Reads <project>/script.json (and data/lines.json for real timing when it exists) and writes <project>/preproduction/:
  brief.json        what we understood (topic, audience, mood, platform, duration, resources)
  decision.json     the style decision from select_style.py (+ chosen style/accent, with reasons)
  bible.json        palette lock, character sheets (locked fields), environment sheets, camera + light rules
  storyboard.json   one row per script line: beat, shot, camera, movement, light, transition, timing, continuity
  storyboard.md     the same, human readable
  prompts.md        (--prompts) per-scene visual-generation prompts built from the bible (for user-run tools)

Every row is a PLAN. Nothing here renders; the build step (SKILL.md section 3) turns the plan into src/shots.js.
"""
import argparse, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import select_style as SS  # noqa: E402

ROOT = HERE.parent

# camera vocabulary per style family: (shot, movement)
CAM = {
    '3d': {'hook': ('medium, eye level, subject centred', 'slow push-in'), 'build': ('over-the-shoulder / wide establishing', 'lateral dolly'),
           'turn': ('extreme close-up on the detail', 'quick punch-in on the key word'), 'payoff': ('wide reveal, low angle', 'crane up'),
           'close': ('medium to camera', 'slow pull-back, hold')},
    '2d': {'hook': ('centred hero + object, flat', 'slow push-in'), 'build': ('cutaway / x-ray or diagram', 'pan along the path'),
           'turn': ('close-up with a big graphic', 'punch-in + flash cut'), 'payoff': ('wide, symbols settle', 'ease-out zoom'),
           'close': ('hero to camera', 'static hold, tiny bob')},
    'stylized': {'hook': ('establishing tableau', 'slow parallax drift'), 'build': ('map / layered scene', 'pan with parallax'),
                 'turn': ('detail insert', 'cut on action'), 'payoff': ('wide tableau', 'gentle pull-back'), 'close': ('final image, title card feel', 'hold')},
    'motion': {'hook': ('bold type or hero number', 'scale-in'), 'build': ('icon / chart build', 'wipe on beat'),
               'turn': ('single stat or contrast', 'snap cut'), 'payoff': ('summary frame', 'ease settle'), 'close': ('CTA / brand frame', 'hold')},
    'hybrid': {'hook': ('medium, subject centred', 'slow push-in'), 'build': ('wide establishing', 'lateral dolly'),
               'turn': ('close-up on reaction', 'punch-in on the key word'), 'payoff': ('wide reveal', 'crane up'), 'close': ('medium to camera', 'hold')},
    'storytelling': {'hook': ('establishing tableau', 'slow push-in'), 'build': ('character in context', 'pan'),
                     'turn': ('close-up reaction', 'cut on action'), 'payoff': ('wide', 'pull-back'), 'close': ('final image', 'hold')},
    'ai': {'hook': ('medium', 'slow push-in'), 'build': ('wide', 'dolly'), 'turn': ('close-up', 'push-in'), 'payoff': ('wide', 'crane'), 'close': ('medium', 'hold')},
}
LIGHT = {'night-file': 'single motivated key light, deep shadow, cool fill', 'deep-dive': 'warm sun key + soft fill, x-ray scenes cyan self-lit',
         'tall-tale': 'bright midday sun outside, warm bulbs inside, pink sunset for endings', 'paper-atlas': 'flat even light, soft paper drop shadows',
         'inside-out': 'flat, no lighting (depth by tone shifts)', 'stick-story': 'flat, day/night by background colour only'}
TURN_WORDS = re.compile(r"\b(but|however|until|yet|except|then suddenly|twist|myth|actually|turns out|instead)\b", re.I)
EMO = [('shock', r"\b(shock|suddenly|vanish|disappear|scream|explod)"), ('worry', r"\b(danger|block|risk|trouble|panic|warning)"),
       ('joy', r"\b(win|won|laugh|clever|perfect|success|delivered)"), ('curiosity', r"\b(what|why|how|if)\b")]


def beat(i, n, text):
    if i == 0:
        return 'hook'
    if i >= n - 1:
        return 'close'
    if TURN_WORDS.search(text):
        return 'turn'
    return 'payoff' if i >= int(n * 0.75) else 'build'


def emotion(text):
    for name, rx in EMO:
        if re.search(rx, text, re.I):
            return name
    return 'neutral'


def parse_chars(s):
    out = []
    for part in [p.strip() for p in (s or '').split(';') if p.strip()]:
        name, _, desc = part.partition(':')
        out.append({'name': name.strip(), 'description': desc.strip()})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project')
    ap.add_argument('--brief', required=True)
    ap.add_argument('--platform')
    ap.add_argument('--duration', type=float)
    ap.add_argument('--audience')
    ap.add_argument('--style')
    ap.add_argument('--accent')
    ap.add_argument('--characters', default='')
    ap.add_argument('--resources', default='')
    ap.add_argument('--prompts', action='store_true')
    a = ap.parse_args()
    P = Path(a.project)
    S = json.loads((P / 'script.json').read_text())
    lines = S['lines']
    n = len(lines)
    timing = None
    if (P / 'data/lines.json').exists():
        timing = {l['i']: l for l in json.loads((P / 'data/lines.json').read_text())['lines']}

    brief = {'text': a.brief + ' ' + S.get('title', '')}
    for k in ('platform', 'duration', 'audience'):
        if getattr(a, k):
            brief[k] = getattr(a, k)
    if a.resources:
        brief['resources'] = [r.strip() for r in a.resources.split(',')]
    if a.style:
        brief['prefer_style'] = a.style
    dec = SS.decide(brief)
    chosen = a.style or dec['picks'][0]['id']
    if chosen not in SS.BY_ID:
        sys.exit(f'unknown style {chosen}; see select_style.py --list')
    st = SS.BY_ID[chosen]
    accent = a.accent
    if accent:
        ok, msg = SS.pair_check(chosen, accent)
        if ok is False:
            sys.exit(f'refusing hybrid {chosen}+{accent}: {msg}')
    elif 'hybrid_suggestion' in dec:
        accent = None  # suggestion stays a suggestion until the user/plan accepts it
    plat = SS.PLAT[dec['analysis']['platform']]

    out = P / 'preproduction'
    out.mkdir(exist_ok=True)
    (out / 'brief.json').write_text(json.dumps({'idea': a.brief, 'title': S.get('title'), **dec['analysis']}, indent=1))
    (out / 'decision.json').write_text(json.dumps({'chosen': chosen, 'accent': accent, 'status': st['status'], 'engine': st['engine'],
                                                   'recipe': st['recipe'], 'ranking': dec['picks'], 'hybrid_suggestion': dec.get('hybrid_suggestion')}, indent=1))

    chars = parse_chars(a.characters)
    bible = {
        'style': chosen, 'accent': accent, 'engine': st['engine'], 'platform': dec['analysis']['platform'], 'aspect': dec['analysis']['aspect'],
        'palette_lock': {'max_colours': 6, 'colours': [], 'note': 'Fill from styles/%s/STYLE.md palette or the recipe; never add a 7th colour.' % st['engine']},
        'line_and_shape_lock': 'outline weight, corner roundness and texture come from the primary style only',
        'light_rule': LIGHT.get(st['engine'], 'consistent direction in every shot'),
        'frame_rate_lock': 'stepped styles force the whole shot to their fps (see recipe)',
        'characters': [{'name': c['name'], 'description': c['description'],
                        'LOCKED': {'face': '', 'hair_or_hat': '', 'clothing': '', 'body_proportions': '', 'colour_scheme': [], 'signature_prop': '',
                                   'personality_in_motion': '', 'default_expression': '', 'expression_set': ['neutral', 'happy', 'shock', 'worried']}} for c in chars],
        'environments': [], 'continuity_rules': [
            'A character keeps the same clothing, colours and proportions in every shot (change only via an explicit costume-change line in the storyboard).',
            'Each environment is defined once (layout, palette, key props, light direction) and reused; new angle = same objects in the same places.',
            'A prop is in exactly one place per moment: it moves with whoever holds it.',
            'Screen direction: if a character exits right, they enter left in the next shot unless a turn-around is shown.']}
    (out / 'bible.json').write_text(json.dumps(bible, indent=1))

    cam = CAM.get(st['family'], CAM['2d'])
    sb, t = [], 0.0
    for i, ln in enumerate(lines):
        b = beat(i, n, ln['text'])
        if timing and i in timing:
            s0, s1 = timing[i]['start'], timing[i]['end']
        else:
            w = len(ln['text'].split())
            s0, s1 = t, t + w / 2.8
            t = s1 + float(ln.get('gap', S.get('gap', 0.3)))
        shot, move = cam[b]
        lo, hi = plat.get('cut_every_s', [1.5, 3.5]) if plat.get('cut_every_s') else [1.5, 3.5]
        sb.append({'line': i, 'text': ln['text'], 'beat': b, 'emotion': emotion(ln['text']), 'start': round(s0, 2), 'end': round(s1, 2),
                   'duration': round(s1 - s0, 2), 'shot': shot, 'camera_move': move, 'light': bible['light_rule'],
                   'transition_in': 'hard cut + whoosh' if b != 'hook' else 'none (first frame must already be the hook)',
                   'continuity': [c['name'] for c in chars if c['name'].lower() in ln['text'].lower()] or 'carry subject from previous shot',
                   'split_hint': 'split into two shots' if (s1 - s0) > hi else ''})
    (out / 'storyboard.json').write_text(json.dumps(sb, indent=1))
    md = [f"# Storyboard: {S.get('title','')}", f"style **{chosen}**" + (f" + accent **{accent}**" if accent else '') + f" · {dec['analysis']['aspect']} · engine `{st['engine']}` ({st['status']})", '',
          '| # | time | beat | on screen | camera | transition |', '|---|---|---|---|---|---|']
    for r in sb:
        md.append(f"| {r['line']+1} | {r['start']:.1f}-{r['end']:.1f}s | {r['beat']} | {r['text']} | {r['shot']} / {r['camera_move']} | {r['transition_in']} |")
    (out / 'storyboard.md').write_text('\n'.join(md) + '\n')

    if a.prompts:
        pr = ['# Scene prompts for YOUR external tools', '', 'This skill does not generate images or video. Paste these into your own tool, keep the character block identical in every prompt, then bring the clips back to be assembled with captions + audio.', '']
        cb = ' '.join(f"[{c['name']}: {c['description']}]" for c in chars) or '[describe the main character once, then reuse it word for word]'
        for r in sb:
            pr += [f"## Scene {r['line']+1} ({r['duration']}s)", f"{st['name']} style. {cb} Action: {r['text'].rstrip('.,')}. Shot: {r['shot']}. Camera: {r['camera_move']}. Light: {r['light']}. Mood: {r['emotion']}. Aspect {dec['analysis']['aspect']}. Keep palette, outfit and proportions identical to previous scenes.", '']
        (out / 'prompts.md').write_text('\n'.join(pr))
    print(f"preproduction → {out}: style={chosen}{'+'+accent if accent else ''} engine={st['engine']} ({st['status']}), {n} scenes"
          f"{', real timing' if timing else ', estimated timing'}; fill bible.json LOCKED fields before building")
    if st['status'] != 'native':
        print(f"note: '{chosen}' is an adapted recipe on the {st['engine']} engine and has not been render-verified; QA the contact sheet before promising the look.")


if __name__ == '__main__':
    main()
