#!/usr/bin/env python3
"""Automatic quality control for a short (standard library + ffmpeg/ffprobe).

  scripts/py scripts/qc.py <project>                              data checks only (before rendering)
  scripts/py scripts/qc.py <project> --video renders/x.mp4        data + video checks
  options: --platform shorts|reels|tiktok|youtube|square   --strict (warnings fail)   --json

Levels: FAIL (do not ship), WARN (look at it), PASS. Exit code 1 if any FAIL.

What it measures (objective): script structure, caption rules, line/word timing coverage, cut cadence, sources,
character-bible completeness, resolution/aspect/fps, duration vs script, audio present + level + clipping,
black frames, frozen frames, A/V length mismatch.
What it CANNOT judge (it prints a visual checklist instead; Claude must look at the contact sheet):
animation quality, character consistency, scene continuity, visual appeal, style fit, rendering glitches inside a frame.
"""
import argparse, json, re, subprocess, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAT = json.loads((HERE.parent / 'library/platforms.json').read_text())['profiles']
R = []


def add(level, area, msg):
    R.append((level, area, msg))


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def data_checks(P, plat):
    try:
        S = json.loads((P / 'script.json').read_text())
    except Exception as e:
        add('FAIL', 'script', f'script.json unreadable: {e}')
        return None
    lines = S.get('lines') or []
    if not lines:
        add('FAIL', 'script', 'no lines')
        return S
    add('PASS', 'script', f'{len(lines)} lines, voice {S.get("voice")}, music {S.get("music")}')
    if not S.get('sources'):
        add('WARN', 'facts', 'no "sources" in script.json: factual claims are unchecked')
    words = sum(len(l['text'].split()) for l in lines)
    add('PASS' if 40 <= words <= 260 else 'WARN', 'script', f'{words} words')
    style_tall = (P / 'src/core/toon.js').exists()
    style_flat = (P / 'src/core/kit.js').exists() and not (P / 'src/core/board.js').exists()   # Inside Out: strict 1-3 words, one yellow word
    for i, l in enumerate(lines):
        if 'caps' not in l:
            continue
        for ch in [c.strip() for c in l['caps'].split('|')]:
            toks = ch.split()
            stars = ch.count('*')
            if style_flat and not (1 <= len(toks) <= 3):
                add('WARN', 'captions', f'line {i+1}: chunk "{ch}" has {len(toks)} words (want 1-3)')
            if style_flat and stars != 1:
                add('WARN', 'captions', f'line {i+1}: chunk "{ch}" has {stars} highlighted words (want exactly 1)')
    lj, wj = P / 'data/lines.json', P / 'data/words.json'
    if not (lj.exists() and wj.exists()):
        add('WARN', 'timing', 'data/lines.json or words.json missing: run voice.py + words.py (or estimate.py)')
        return S
    L = json.loads(lj.read_text())
    ls = L['lines']
    if L.get('estimated'):
        add('WARN', 'timing', 'timing is ESTIMATED (no real voice yet)')
    if len(ls) != len(lines):
        add('FAIL', 'timing', f'script has {len(lines)} lines but timing has {len(ls)}: re-run words.py')
    prev = -1
    lo, hi = (plat.get('cut_every_s') or [1.5, 3.5])
    long_, short_ = [], []
    for x in ls:
        if x['start'] < prev - 1e-6:
            add('FAIL', 'timing', f'line {x["i"]+1} starts before the previous one ended')
        prev = x['end']
        d = x['end'] - x['start']
        (long_ if d > hi + 1.5 else short_ if d < 0.6 else []).append(x['i'] + 1)
    if long_:
        add('WARN', 'pacing', f'lines {long_} run > {hi + 1.5:.1f}s: split into two shots to keep the {lo}-{hi}s cut rhythm')
    if short_:
        add('WARN', 'pacing', f'lines {short_} are < 0.6 s: may be too fast to read')
    add('PASS', 'timing', f'{len(ls)} lines timed, total {L["duration"]:.1f}s')
    mx = plat.get('max_s')
    if mx and L['duration'] > mx:
        add('FAIL', 'platform', f'{L["duration"]:.1f}s exceeds the {mx}s limit for this platform')
    ss = [40, 60] if style_tall else plat.get('sweet_spot_s')   # Tall Tale is documented as 40-60 s
    if ss and not (ss[0] <= L['duration'] <= ss[1]):
        add('WARN', 'platform', f'{L["duration"]:.1f}s is outside the {ss[0]}-{ss[1]}s sweet spot')
    W = json.loads(wj.read_text())
    cover = {w['line'] for w in W}
    miss = [i + 1 for i in range(len(lines)) if i not in cover]
    add('FAIL' if miss else 'PASS', 'timing', f'lines without word timings: {miss}' if miss else 'every line has word timings')
    if ls and W and W[0]['s'] > 1.2 and ls[0]['start'] > 1.2:
        add('WARN', 'hook', f'first word at {W[0]["s"]:.1f}s: the hook should start within ~1s')
    return S


def bible_checks(P):
    b = P / 'preproduction/bible.json'
    sb = P / 'preproduction/storyboard.json'
    if not b.exists():
        add('WARN', 'consistency', 'no preproduction/bible.json: character/environment consistency is unplanned')
        return
    B = json.loads(b.read_text())
    for c in B.get('characters', []):
        empty = [k for k, v in c['LOCKED'].items() if v in ('', [], None)]
        add('FAIL' if len(empty) > 3 else 'WARN' if empty else 'PASS', 'consistency',
            f'character {c["name"]}: ' + (f'unfilled locked fields {empty}' if empty else 'all locked fields set'))
    if not B.get('palette_lock', {}).get('colours'):
        add('WARN', 'consistency', 'palette_lock.colours is empty: fill it so every shot uses the same colours')
    if sb.exists():
        rows = json.loads(sb.read_text())
        add('PASS', 'storyboard', f'{len(rows)} storyboard rows')


def video_checks(P, v, plat, draft=False):
    if not shutil.which('ffprobe'):
        add('FAIL', 'video', 'ffprobe not found')
        return
    pr = run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(v)])
    if pr.returncode:
        add('FAIL', 'video', f'cannot read {v}: {pr.stderr.strip()[:120]}')
        return
    J = json.loads(pr.stdout)
    vs = next((s for s in J['streams'] if s['codec_type'] == 'video'), None)
    au = next((s for s in J['streams'] if s['codec_type'] == 'audio'), None)
    if not vs:
        add('FAIL', 'video', 'no video stream')
        return
    w, h = vs['width'], vs['height']
    if plat.get('w'):
        add('PASS' if (w, h) == (plat['w'], plat['h']) else 'FAIL', 'resolution', f'{w}x{h} (want {plat["w"]}x{plat["h"]} for {plat["aspect"]})')
    num, den = (vs.get('avg_frame_rate') or '0/1').split('/')
    fps = float(num) / float(den or 1)
    add('PASS' if abs(fps - plat.get('fps', 30)) < 0.6 or plat.get('fps') is None else 'WARN', 'fps', f'{fps:.2f} fps')
    if vs.get('pix_fmt') not in ('yuv420p', 'yuvj420p'):
        add('WARN', 'compat', f'pix_fmt {vs.get("pix_fmt")}: some phones/uploaders need yuv420p')
    dur = float(J['format']['duration'])
    lj = P / 'data/lines.json'
    if lj.exists():
        want = json.loads(lj.read_text())['duration']
        if abs(dur - want) > 0.6 and not draft:
            add('WARN', 'sync', f'video {dur:.1f}s vs script timing {want:.1f}s (use --draft for partial clips)')
        else:
            add('PASS', 'sync', f'video {dur:.1f}s vs script {want:.1f}s')
    if not au:
        add('FAIL', 'audio', 'no audio stream')
    else:
        ad = float(au.get('duration') or dur)
        add('PASS' if abs(ad - dur) < 0.35 else 'WARN', 'sync', f'audio {ad:.2f}s vs video {dur:.2f}s')
        vd = run(['ffmpeg', '-v', 'info', '-i', str(v), '-af', 'volumedetect', '-vn', '-f', 'null', '-'])
        mean = re.search(r'mean_volume: (-?[\d.]+)', vd.stderr)
        mx = re.search(r'max_volume: (-?[\d.]+)', vd.stderr)
        if mean:
            m = float(mean.group(1))
            add('FAIL' if m < -45 else 'WARN' if m < -28 or m > -9 else 'PASS', 'audio', f'mean level {m} dB (good: about -24 to -14)')
        if mx and float(mx.group(1)) >= -0.1:
            add('WARN', 'audio', f'peaks at {mx.group(1)} dB: possible clipping')
    bd = run(['ffmpeg', '-v', 'info', '-i', str(v), '-vf', 'blackdetect=d=0.4:pic_th=0.98', '-an', '-f', 'null', '-'])
    blacks = re.findall(r'black_start:([\d.]+) black_end:([\d.]+)', bd.stderr)
    blacks = [(float(a), float(b)) for a, b in blacks if not (float(a) < 0.1 or float(b) >= dur - 0.15)]  # intentional fade in/out ignored
    add('WARN' if blacks else 'PASS', 'rendering', f'unexpected black frames at {blacks[:4]}' if blacks else 'no unexpected black frames')
    fz = run(['ffmpeg', '-v', 'info', '-i', str(v), '-vf', 'freezedetect=n=-60dB:d=1.2', '-an', '-f', 'null', '-'])
    fr = re.findall(r'freeze_start: ([\d.]+)', fz.stderr)
    add('WARN' if len(fr) else 'PASS', 'rendering', f'frozen picture from {fr[:4]}s: static shot > 1.2 s (add camera motion)' if fr else 'no frozen stretches')


VISUAL_CHECKLIST = [
    'Style fit: does this look like the chosen style on EVERY frame of the contact sheet (no engine defaults leaking)?',
    'Character consistency: face, outfit, proportions, colours identical in shots 1, middle and last.',
    'Scene continuity: props/locations/time-of-day/screen direction carry across cuts; nothing appears before its cause.',
    'Composition: subject inside safe zone, nothing under the caption band or platform UI.',
    'Animation quality: motion eases, no popping, no jitter unless the style calls for it.',
    'Story clarity: each shot shows what the line says at that moment; reveals land on their word.',
    'Transitions: motivated, not decorative; no flash on a non-cut.',
    'Sound: voice intelligible over music; effects soft.',
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project')
    ap.add_argument('--video')
    ap.add_argument('--platform', default='shorts', choices=list(PLAT))
    ap.add_argument('--draft', action='store_true', help='clip is a partial/draft render: skip the full-length check')
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    P = Path(a.project)
    plat = PLAT[a.platform]
    data_checks(P, plat)
    bible_checks(P)
    if a.video:
        video_checks(P, Path(a.video) if Path(a.video).is_absolute() else (P / a.video if (P / a.video).exists() else Path(a.video)), plat, a.draft)
    fails = [r for r in R if r[0] == 'FAIL']
    warns = [r for r in R if r[0] == 'WARN']
    if a.json:
        print(json.dumps({'results': R, 'fails': len(fails), 'warns': len(warns)}, indent=1))
    else:
        for lv, area, msg in R:
            print(f'{lv:<5} {area:<12} {msg}')
        print('\nVisual review still required (qc.py cannot judge these):')
        for c in VISUAL_CHECKLIST:
            print('  [ ]', c)
        print(f'\nQC: {len(fails)} fail, {len(warns)} warn')
    sys.exit(1 if fails or (a.strict and warns) else 0)


if __name__ == '__main__':
    main()
