#!/bin/bash
# Start a new video from a style's working example (engine + shots + script), so it renders straight away.
#   bash new_video.sh <style> <short-name> [--dir <parent>]     → ~/faceless-shorts/<short-name>/
#   bash new_video.sh --list                                    the styles
set -eu
SKILL="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${1:-}" = "--list" ]; then for d in "$SKILL"/styles/*/; do echo "$(basename "$d")"; done; exit 0; fi
USAGE="usage: new_video.sh <style> <short-name> [--dir <parent>]   (styles: $(ls "$SKILL/styles" | tr '\n' ' '))"
STYLE="${1:?$USAGE}"; NAME="${2:?$USAGE}"; shift 2
PARENT="$HOME/faceless-shorts"
while [ $# -gt 0 ]; do case "$1" in --dir) PARENT="${2:?}"; shift 2 ;; *) echo "unknown option $1" >&2; exit 2 ;; esac; done
# A style id from library/styles.json that has no folder of its own (an "adapted" style) builds on its engine's example.
RECIPE=""
if [ ! -d "$SKILL/styles/$STYLE" ] && [ -f "$SKILL/library/styles.json" ]; then
  R="$("$SKILL/scripts/py" -c "
import json,sys
d={s['id']:s for s in json.load(open('$SKILL/library/styles.json'))['styles']}
s=d.get(sys.argv[1])
if s and s.get('engine'): print(s['engine']+'|'+s['recipe'])
" "$STYLE" 2>/dev/null || true)"
  if [ -n "$R" ]; then RECIPE="${R#*|}"; echo "style '$STYLE' is an adapted recipe on the '${R%%|*}' engine (not render-verified)." >&2; STYLE="${R%%|*}"; fi
fi
SRC="$SKILL/styles/$STYLE/example"
[ -d "$SRC" ] || { echo "no style '$STYLE' ($USAGE)" >&2; exit 2; }
DST="$PARENT/$NAME"
[ -e "$DST" ] && { echo "$DST already exists: pick another name" >&2; exit 2; }
mkdir -p "$PARENT"; cp -R "$SRC" "$DST"; mkdir -p "$DST/renders" "$DST/review"
rm -f "$DST/data/narration.wav" "$DST/data/mix.wav"
echo "$DST"
echo "engine: $STYLE. Read $SKILL/styles/$STYLE/STYLE.md, then rewrite script.json + src/shots.js"
[ -n "$RECIPE" ] && { echo "recipe to apply on top of the engine: $RECIPE"; echo "$RECIPE" > "$DST/RECIPE.txt"; }
true
