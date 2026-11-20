#!/usr/bin/env python3
"""Animation style decision engine (standard library only).

  scripts/py scripts/select_style.py "what happens if you hold your breath" --platform shorts --duration 35
  scripts/py scripts/select_style.py --brief-file brief.json          # structured brief, see reference/brief.md
  scripts/py scripts/select_style.py "..." --json                      # machine-readable
  scripts/py scripts/select_style.py --hybrid paper-atlas kinetic-typography
  scripts/py scripts/select_style.py --list [--family 2d|3d|stylized|motion|hybrid|storytelling|ai]
  scripts/py scripts/select_style.py --self-test                       # runs tests/concepts.json

How it decides (all of it is in this file, nothing hidden):
 1. Read the brief (free text and/or fields) -> topic tags, mood tags, audience, story-need, platform, duration, resources.
 2. Score every style in library/styles.json: topic fit, mood fit, audience fit, character need vs story need,
    complexity vs duration + available hardware, and a preference for styles with a verified native engine.
 3. Rank, flag hard blocks (wrong audience, 3D without GPU on a long video, non-9:16 on a 9:16-only engine), and
    optionally propose ONE hybrid accent from library/hybrids.json.
 4. Ask for clarification ONLY if no topic could be recognised (confidence < 0.25).
"""
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = json.loads((ROOT / 'library/styles.json').read_text())['styles']
PLAT = json.loads((ROOT / 'library/platforms.json').read_text())['profiles']
HY = json.loads((ROOT / 'library/hybrids.json').read_text())
BY_ID = {s['id']: s for s in LIB}
import math
_DF = {}
for _s in LIB:
    for _t in set(_s['topics']) | set(_s['moods']):
        _DF[_t] = _DF.get(_t, 0) + 1


def rarity(tag):
    """A tag claimed by few styles is a stronger signal than one claimed by many (like IDF)."""
    return 1 + 0.35 * math.log(len(LIB) / max(_DF.get(tag, 1), 1))

# keyword -> topic tag (substring match on the lower-cased brief). Add rows freely.
TOPIC_WORDS = {
    'body': ['body', 'organ', 'stomach', 'heart', 'brain', 'blood', 'muscle', 'swallow', 'knuckle', 'breath', 'sleep', 'digest'],
    'health': ['health', 'disease', 'symptom', 'vitamin', 'doctor', 'medicine', 'diet', 'immune'],
    'science': ['science', 'physics', 'chemistry', 'biology', 'atom', 'cell', 'planet', 'quantum', 'experiment', 'evolution', 'gravity'],
    'space': ['space', 'galaxy', 'black hole', 'mars', 'moon', 'star', 'astronaut', 'orbit'],
    'nature': ['nature', 'ocean', 'forest', 'animal', 'volcano', 'weather', 'river', 'mountain', 'climate'],
    'what-if': ['what happens if', 'what if', 'what would happen'],
    'mystery': ['mystery', 'unsolved', 'never solved', 'disappear', 'vanish', 'unexplained', 'cold case', 'strange case'],
    'true-crime': ['crime', 'murder', 'heist', 'hijack', 'serial killer', 'detective', 'suspect', 'fugitive', 'cooper'],
    'horror': ['horror', 'scary', 'haunted', 'creepy', 'ghost', 'paranormal', 'nightmare', 'demon', 'cursed'],
    'conspiracy': ['conspiracy', 'cover-up', 'classified', 'secret government'],
    'survival': ['survive', 'survival', 'blackout', 'power outage', 'earthquake', 'emergency', 'what would you do', 'lost in'],
    'life-hack': ['life hack', 'hack', 'tips', 'trick to', 'save money on'],
    'how-to': ['how to', 'step by step', 'tutorial', 'guide to', 'steps'],
    'history': ['history', 'ancient', 'empire', 'medieval', 'century', 'revolution', 'dynasty', 'in 17', 'in 18', 'in 19', 'war of', 'great fire', 'roman', 'viking', 'colonial'],
    'war': ['war', 'battle', 'invasion', 'siege', 'army'],
    'geography': ['map', 'country', 'border', 'island', 'capital city', 'route', 'trade route'],
    'biography': ['biography', 'life of', 'born in', 'inventor', 'pioneer'],
    'funny-story': ['funny', 'hilarious', 'prank', 'ridiculous', 'loophole', 'tricked', 'con artist', 'scam', 'mailed', 'absurd', 'banned'],
    'true-story': ['true story', 'actually happened', 'real story'],
    'kids-story': ['bedtime', 'fairy tale', 'children', 'kids story', 'little bunny', 'once upon a time', 'for kids', 'toddler', 'nursery', 'moral story'],
    'fable': ['fable', 'moral', 'folk tale', 'folktale', 'legend of', 'parable'],
    'business': ['business', 'startup', 'saas', 'b2b', 'marketing', 'sales', 'revenue', 'customers', 'brand', 'company', 'product launch', 'investor'],
    'finance': ['finance', 'invest', 'stock', 'crypto', 'budget', 'inflation', 'tax', 'money', 'compound interest', 'bank'],
    'tech': ['software', 'app ', 'ai ', 'artificial intelligence', 'internet', 'algorithm', 'cloud', 'api', 'programming', 'robot', 'chip'],
    'data': ['statistics', 'data', 'percent', 'chart', 'ranking', 'comparison of', 'top 10', 'survey'],
    'news': ['news', 'breaking', 'announcement', 'report says', 'update'],
    'education': ['explain', 'explainer', 'lesson', 'learn', 'concept', 'how does', 'why do', 'what is', 'teach'],
    'motivation': ['motivat', 'inspir', 'discipline', 'mindset', 'success', 'never give up', 'hustle', 'grind', 'believe in yourself', 'comeback'],
    'quotes': ['quote', 'speech', 'poem', 'poetry', 'lyrics', 'affirmation'],
    'psychology': ['psychology', 'habit', 'anxiety', 'emotion', 'procrastinat', 'personality', 'cognitive'],
    'food': ['food', 'recipe', 'cooking', 'coffee', 'chocolate', 'pizza', 'gum', 'candy', 'meal'],
    'gaming': ['game', 'gaming', 'retro', '8-bit', 'arcade', 'minecraft'],
    'superhero': ['superhero', 'villain', 'comic', 'hero origin'],
    'fantasy': ['fantasy', 'dragon', 'wizard', 'magic', 'kingdom', 'quest'],
    'sci-fi': ['sci-fi', 'cyberpunk', 'dystopia', 'time travel', 'alien', 'android'],
    'travel': ['travel', 'journey', 'trip to', 'destination', 'wanderlust', 'road trip'],
    'memoir': ['memoir', 'my story', 'childhood memory', 'my grandmother'],
    'art': ['art ', 'abstract', 'painting', 'artist', 'experimental'],
    'satisfying': ['satisfying', 'oddly satisfying', 'hypnotic', 'asmr', 'seamless loop', 'looping'],
    'product': ['product demo', 'unboxing', 'feature', 'launch'],
    'process': ['process', 'workflow', 'supply chain', 'pipeline', 'how it is made', 'how its made', 'how it works'],
    'comedy': ['comedy', 'joke', 'sketch', 'parody', 'meme', 'roast'],
    'action': ['action', 'fight', 'chase', 'explosion', 'ninja', 'samurai'],
    'school': ['school', 'classroom', 'student life', 'exam'],
    'sports': ['football', 'soccer', 'basketball', 'cricket', 'athlete', 'match', 'olympic'],
    'animals': ['dog', 'cat', 'puppy', 'bird', 'penguin', 'elephant', 'animals'],
    'crafts': ['craft', 'handmade', 'diy', 'knitting', 'origami'],
    'architecture': ['building', 'skyscraper', 'bridge', 'architecture', 'city planning'],
    'engineering': ['engine', 'engineering', 'machine', 'mechanism', 'turbine', 'reactor'],
    'medicine': ['surgery', 'anatomy', 'drug', 'clinical', 'vaccine', 'pathogen', 'virus'],
    'politics': ['election', 'parliament', 'government', 'policy', 'treaty', 'senate', 'constitution'],
    'economics': ['economy', 'economics', 'recession', 'trade', 'tariff', 'gdp'],
    'culture': ['culture', 'tradition', 'festival', 'ritual', 'folklore', 'myth'],
    'trailer': ['trailer', 'teaser', 'coming soon'],
    'drama': ['drama', 'tragedy', 'heartbreak', 'love story', 'loss'],
    'adventure': ['adventure', 'expedition', 'treasure', 'explore'],
    'brand': ['brand film', 'brand story', 'our mission'],
    'everyday': ['everyday', 'daily life', 'office', 'commute', 'roommate'],
    'unsolved': ['never solved', 'still unsolved', 'no one knows', 'unsolved'],
}
MOOD_WORDS = {
    'dark': ['dark', 'creepy', 'eerie', 'disturbing', 'haunted', 'sinister'], 'eerie': ['eerie', 'spooky', 'uncanny'],
    'tense': ['tense', 'suspense', 'thriller', 'edge of your seat'], 'dramatic': ['dramatic', 'intense', 'high stakes'],
    'funny': ['funny', 'hilarious', 'comedic', 'lol', 'absurd', 'humor', 'humour'], 'light': ['light', 'lighthearted', 'quick fun'],
    'upbeat': ['upbeat', 'energetic', 'bouncy', 'cheerful'], 'warm': ['warm', 'heartwarming', 'cozy', 'wholesome'],
    'gentle': ['gentle', 'soothing', 'bedtime', 'calm bedtime'], 'calm': ['calm', 'relaxing', 'peaceful', 'chill'],
    'emotional': ['emotional', 'tearjerker', 'moving', 'touching', 'sad'], 'epic': ['epic', 'grand', 'legendary', 'sweeping'],
    'inspiring': ['inspiring', 'uplifting', 'motivational'], 'serious': ['serious', 'solemn', 'documentary', 'sober'],
    'clean': ['clean', 'minimal', 'corporate', 'professional'], 'modern': ['modern', 'sleek', 'techy'],
    'curious': ['curious', 'mind-blowing', 'fascinating', 'weird facts'], 'playful': ['playful', 'whimsical', 'quirky', 'silly'],
    'nostalgic': ['nostalgic', 'retro', 'vintage', 'old-school'], 'punchy': ['punchy', 'fast', 'snappy'],
    'awe': ['awe', 'wonder', 'majestic', 'breathtaking'], 'confident': ['investor', 'enterprise', 'b2b', 'executive', 'pitch deck'], 'practical': ['practical', 'useful', 'actionable'],
}
AUD_WORDS = {'kids': ['kids', 'children', 'toddler', 'preschool', 'ages 3', 'ages 5', 'ages 8', 'bedtime'],
             'teens': ['teen', 'gen z', 'students'], 'adults': ['adult', 'professional', 'executives', 'founders', 'investors', 'b2b']}
STORY_WORDS = ['story', 'tale', 'once', 'the man who', 'the girl who', 'the woman who', 'character', 'journey', 'happened',
               'legend', 'fable', 'narrative', 'bedtime', 'this guy', 'she ', 'he ']
NO_CHAR_TOPICS = {'data', 'finance', 'business', 'tech', 'news', 'quotes', 'satisfying', 'product', 'process'}


_RX = {}


def _rx(w):
    """Keyword -> regex. Short words (<=4 letters) and words ending in a space must match whole words,
    longer words match as a prefix ('motivat' matches 'motivational'). Stops 'war' firing on 'software'."""
    if w not in _RX:
        core = re.escape(w.strip())
        tail = r'\b' if (len(w.strip()) <= 4 or w.endswith(' ')) else ''
        _RX[w] = re.compile(r'(?<![a-z0-9])' + core + tail)
    return _RX[w]


def has(text, words):
    return any(_rx(w).search(text) for w in words)


def analyse(brief):
    text = ' ' + (brief.get('text') or '').lower() + ' ' + ' '.join(brief.get('keywords', [])).lower() + ' '
    topics = {t for t, ws in TOPIC_WORDS.items() if has(text, ws)} | set(brief.get('topics', []))
    moods = {m for m, ws in MOOD_WORDS.items() if has(text, ws)} | set(brief.get('moods', []))
    aud = brief.get('audience')
    if not aud:
        aud = next((a for a, ws in AUD_WORDS.items() if has(text, ws)), 'general')
    story = has(text, STORY_WORDS) or bool(topics & {'funny-story', 'true-story', 'kids-story', 'fable', 'biography', 'memoir', 'drama', 'history', 'mystery', 'true-crime', 'horror'})
    plat = brief.get('platform') or 'shorts'
    if plat not in PLAT:
        plat = 'shorts'
    dur = brief.get('duration') or (PLAT[plat].get('sweet_spot_s') or [30, 40])[0] + 5
    res = set(brief.get('resources', []))
    return dict(topics=sorted(topics), moods=sorted(moods), audience=aud, story=story, platform=plat,
                aspect=brief.get('aspect') or PLAT[plat]['aspect'], duration=dur, resources=sorted(res),
                gpu='gpu' in res, wants_ai_prompts=bool(brief.get('wants_ai_prompts')) or has(text, ['midjourney', 'runway', 'sora', 'veo', 'kling', 'pika', 'ai video', 'prompt pack']),
                prefer=brief.get('prefer_style'))


def score(s, a):
    sc, why, blocks = 0.0, [], []
    tt = set(s['topics'])
    hit = tt & set(a['topics'])
    if 'any' in tt:
        sc += 1; why.append('generic: fits any topic')
    elif hit:
        sc += 4 * sum(rarity(h) for h in hit) ** 0.8; why.append('topic fit: ' + ', '.join(sorted(hit)))
    mh = set(s['moods']) & set(a['moods'])
    if mh:
        sc += 2 * sum(rarity(m) for m in mh) ** 0.8; why.append('mood fit: ' + ', '.join(sorted(mh)))
    # audience
    if a['audience'] in s['audiences']:
        sc += 2
    else:
        sc -= 6; blocks.append(f"not suited to {a['audience']} audience")
    if a['audience'] == 'kids' and 'kids' in s['audiences']:
        sc += 2; why.append('built for children')
    # characters
    only_abstract = a['topics'] and set(a['topics']) <= NO_CHAR_TOPICS
    if a['story'] and s['character_need'] >= 2:
        sc += 1.5; why.append('character storytelling needed and style supports it')
    if a['story'] and s['character_need'] == 0:
        sc -= 3
    if only_abstract and s['character_need'] >= 3:
        sc -= 2
    if only_abstract and s['character_need'] == 0:
        sc += 1.5
    # complexity vs duration/hardware
    cx = s['complexity']
    if s['family'] in ('3d',) or s['engine'] in ('deep-dive', 'night-file', 'tall-tale'):
        if not a['gpu'] and a['duration'] > 45 and cx >= 4:
            sc -= 3; blocks.append('3D at this length without a GPU renders ~2-3 s per frame (plan hours, not minutes)')
        elif not a['gpu'] and cx >= 4:
            sc -= 0.8; why.append('note: no GPU, expect slow 3D render (use SOFTWARE_GL settings)')
    if a['duration'] > 60 and cx >= 4:
        sc -= 1.5
    # verification preference
    if s['status'] == 'native':
        sc += 1.5; why.append('verified native engine + example')
    elif s['status'] == 'adapted':
        why.append('adapted recipe (unverified until rendered)')
    elif s['status'] == 'prompt-pack':
        if a['wants_ai_prompts']:
            sc += 8; why.append('user asked for AI-tool prompts')
        else:
            sc -= 10; blocks.append('only produced on explicit request')
    # aspect support
    if a['aspect'] != '9:16' and s['status'] != 'prompt-pack':
        sc -= 1; blocks.append(f"engines are 1080x1920; {a['aspect']} needs recomposition (reference/platforms.md)")
    if a['prefer'] == s['id']:
        sc += 20; why.append('user explicitly asked for this style')
    return round(sc, 2), why, blocks


def hybrid_for(ranked, a):
    p = ranked[0]
    for g in HY['good_pairs']:
        if g['primary'] == p[0]['id'] and g.get('accent'):
            ac = BY_ID.get(g['accent'])
            if ac and (set(ac['topics']) & set(a['topics']) or set(ac['moods']) & set(a['moods']) or any(r[0]['id'] == g['accent'] for r in ranked[1:6])):
                return g
    return None


def pair_check(x, y):
    for a, b, why in HY['bad_pairs']:
        if {a, b} == {x, y}:
            return False, why
    for g in HY['good_pairs']:
        if g['primary'] == x and g.get('accent') == y:
            return True, f"recommended: accent supplies {g['layers']}. {g['note']}"
        if g['primary'] == y and g.get('accent') == x:
            return True, f"recommended with roles swapped: primary {y}, accent {x}. {g['note']}"
    sx, sy = BY_ID[x], BY_ID[y]
    if sx['family'] == sy['family']:
        return True, 'same family: usually safe; apply the palette/line/light locks in library/hybrids.json'
    return None, 'untested pair: allowed only with a test frame check against the locks in library/hybrids.json'


def decide(brief):
    a = analyse(brief)
    ranked = []
    for s in LIB:
        sc, why, bl = score(s, a)
        ranked.append((s, sc, why, bl))
    ranked.sort(key=lambda r: -r[1])
    top = ranked[0][1]
    conf = 0.0 if not a['topics'] and not a['moods'] else min(1.0, 0.25 + 0.04 * max(top, 0))
    out = dict(analysis=a, confidence=round(conf, 2),
               picks=[dict(id=r[0]['id'], name=r[0]['name'], score=r[1], status=r[0]['status'], engine=r[0]['engine'],
                           why=r[2], warnings=r[3], recipe=r[0]['recipe']) for r in ranked[:5]])
    h = hybrid_for(ranked, a)
    if h:
        out['hybrid_suggestion'] = h
    if conf < 0.25:
        out['needs_clarification'] = 'No topic or mood could be recognised from the brief. Ask ONE question: what is the video about and who is it for?'
    return out


def show(out):
    a = out['analysis']
    print(f"brief: topics={a['topics'] or '-'} moods={a['moods'] or '-'} audience={a['audience']} story={a['story']} "
          f"platform={a['platform']} {a['aspect']} {a['duration']}s gpu={a['gpu']}")
    if 'needs_clarification' in out:
        print('CLARIFY:', out['needs_clarification'])
    for i, p in enumerate(out['picks']):
        print(f"{'>' if i == 0 else ' '} {i+1}. {p['id']:<22} {p['score']:>6}  [{p['status']}] engine={p['engine']}")
        for w in p['why'][:4]:
            print('       +', w)
        for w in p['warnings']:
            print('       !', w)
    if 'hybrid_suggestion' in out:
        h = out['hybrid_suggestion']
        print(f"hybrid option: {h['primary']} + {h['accent']} ({h['layers']}): {h['note']}")
    print(f"confidence {out['confidence']}")


def self_test():
    cases = json.loads((ROOT / 'tests/concepts.json').read_text())
    bad = 0
    for c in cases:
        out = decide(c['brief'])
        top = '__needs_clarification__' if 'needs_clarification' in out else out['picks'][0]['id']
        ok = top in c['expect']
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {c['name']:<42} -> {top:<22} (expected one of {c['expect']})")
    # structural checks on the library
    ids = [s['id'] for s in LIB]
    assert len(ids) == len(set(ids)), 'duplicate style ids'
    for s in LIB:
        if s['status'] == 'native':
            assert (ROOT / 'styles' / s['id'] / 'STYLE.md').exists(), f"missing STYLE.md for native {s['id']}"
        elif s['status'] == 'adapted':
            assert (ROOT / 'styles' / s['engine'] / 'STYLE.md').exists(), f"{s['id']} points to missing engine {s['engine']}"
    for g in HY['good_pairs']:
        assert g['primary'] in BY_ID and (g['accent'] is None or g['accent'] in BY_ID), f'bad hybrid {g}'
    print(f"library: {len(LIB)} styles, {sum(s['status']=='native' for s in LIB)} native, "
          f"{sum(s['status']=='adapted' for s in LIB)} adapted, {sum(s['status']=='prompt-pack' for s in LIB)} prompt-pack")
    print('SELECTOR TESTS PASSED' if not bad else f'SELECTOR TESTS FAILED ({bad})')
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('text', nargs='?', help='the idea, topic or script (free text)')
    ap.add_argument('--brief-file')
    ap.add_argument('--platform', choices=list(PLAT))
    ap.add_argument('--duration', type=float)
    ap.add_argument('--audience', choices=['kids', 'teens', 'adults', 'general'])
    ap.add_argument('--mood', action='append', default=[])
    ap.add_argument('--resources', default='', help='comma list: gpu,blender,... (default none = CPU only)')
    ap.add_argument('--prefer', help='style id the user asked for')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--family')
    ap.add_argument('--hybrid', nargs=2, metavar=('A', 'B'))
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        sys.exit(self_test())
    if a.list:
        for s in LIB:
            if not a.family or s['family'] == a.family:
                print(f"{s['id']:<24} {s['family']:<12} {s['status']:<12} {s['name']}")
        return
    if a.hybrid:
        for x in a.hybrid:
            if x not in BY_ID:
                sys.exit(f'unknown style {x}')
        ok, msg = pair_check(*a.hybrid)
        print({True: 'OK', False: 'AVOID', None: 'UNTESTED'}[ok], '-', msg)
        return
    brief = json.loads(Path(a.brief_file).read_text()) if a.brief_file else {}
    if a.text:
        brief['text'] = (brief.get('text', '') + ' ' + a.text).strip()
    if not brief.get('text') and not brief.get('topics'):
        ap.error('give the idea as text or --brief-file')
    for k in ('platform', 'duration', 'audience'):
        if getattr(a, k):
            brief[k] = getattr(a, k)
    if a.mood:
        brief['moods'] = brief.get('moods', []) + a.mood
    if a.resources:
        brief['resources'] = [r.strip() for r in a.resources.split(',')]
    if a.prefer:
        brief['prefer_style'] = a.prefer
    out = decide(brief)
    print(json.dumps(out, indent=1)) if a.json else show(out)


if __name__ == '__main__':
    main()
