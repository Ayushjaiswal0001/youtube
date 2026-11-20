#!/bin/bash
# Proves the pipeline on this computer (~2-4 min): voice + Whisper on a 2-line script, then every style's example:
# voice -> words -> check -> cues -> mix -> contact sheet -> a 4 s clip with sound. Prints SELFTEST PASSED.
#   bash selftest.sh              all styles
#   bash selftest.sh --no-voice   skip Kokoro/Whisper (estimated timing), e.g. before setup.sh has finished
#   bash selftest.sh --logic      only the no-Chrome checks: style selector, library, pre-production, QC (seconds, no downloads)
# The logic stage always runs first; the render stage needs Node 22 + ffmpeg + Chrome (+ voice models unless --no-voice).
set -u
SKILL="$(cd "$(dirname "$0")/.." && pwd)"; PY="$SKILL/scripts/py"
T="$HOME/faceless-shorts/_selftest"; rm -rf "$T"; mkdir -p "$T"; LOG="$T/selftest.log"; : > "$LOG"
VOICE=1; [ "${1:-}" = "--no-voice" ] && VOICE=0
# ---- logic stage: style selector + library + pre-production + QC (pure Python, no Chrome)
echo "== logic"
"$PY" "$SKILL/scripts/select_style.py" --self-test | tail -3 || { echo "SELFTEST FAILED (selector)"; exit 1; }
L="$T/_logic"; mkdir -p "$L"
bash "$SKILL/scripts/new_video.sh" inside-out logic --dir "$L" >> "$LOG" 2>&1 || { echo "SELFTEST FAILED (new_video)"; exit 1; }
"$PY" "$SKILL/scripts/estimate.py" "$L/logic" >> "$LOG" 2>&1 || { echo "SELFTEST FAILED (estimate)"; exit 1; }
"$PY" "$SKILL/scripts/preproduction.py" "$L/logic" --brief "what happens if you swallow gum" --prompts >> "$LOG" 2>&1 || { echo "SELFTEST FAILED (preproduction)"; exit 1; }
[ -f "$L/logic/preproduction/storyboard.json" ] || { echo "SELFTEST FAILED (no storyboard)"; exit 1; }
"$PY" "$SKILL/scripts/qc.py" "$L/logic" --json > "$L/qc.json" 2>> "$LOG"; [ -s "$L/qc.json" ] || { echo "SELFTEST FAILED (qc produced no output)"; exit 1; }
echo "logic stage ok (pre-production + QC ran on a fresh project)"
[ "${1:-}" = "--logic" ] && { echo "SELFTEST PASSED (logic only: renders were NOT tested)"; exit 0; }
fail=0; note() { printf '%-22s %s\n' "$1" "$2"; }
for d in "$SKILL"/styles/*/; do
  s=$(basename "$d"); P="$T/$s"; t1=$(date +%s)
  bash "$SKILL/scripts/new_video.sh" "$s" "$s" --dir "$T" >> "$LOG" 2>&1 || { note "$s" "FAILED to create (see $LOG)"; fail=1; continue; }
  (
    cd "$P" || exit 1; echo "== $s"
    if [ $VOICE = 1 ]; then "$PY" "$SKILL/scripts/voice.py" . && "$PY" "$SKILL/scripts/words.py" . || exit 1
    else "$PY" "$SKILL/scripts/estimate.py" . || exit 1; fi
    node tools/capture.mjs check | tee review/check.txt; grep -q "CHECK OK" review/check.txt || exit 1
    node tools/capture.mjs cues && "$PY" tools/mix.py . || exit 1
    node tools/capture.mjs sheet review/all.jpg 1 8 || exit 1
    node tools/capture.mjs video renders/selftest.mp4 2 6 --draft || exit 1
  ) >> "$LOG" 2>&1
  M="$P/renders/selftest.mp4"
  if [ -f "$M" ]; then
    A=$(ffmpeg -v info -i "$M" -af volumedetect -vn -f null - 2>&1 | awk '/mean_volume/ {printf "%d", $5}')
    if [ "${A:--99}" -gt -50 ]; then note "$s" "ok, $(( $(date +%s) - t1 )) s · sheet: $P/review/all.jpg · clip: $M"; else note "$s" "FAILED: clip is silent ($A dB)"; fail=1; fi
  else note "$s" "FAILED (see $LOG)"; fail=1; fi
done
[ $fail = 0 ] && echo "SELFTEST PASSED" || { echo "SELFTEST FAILED. Full log: $LOG"; exit 1; }
