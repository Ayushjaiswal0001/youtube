# FINAL VERDICT — X100 directive 07

Starting SHA `510be8f` → ending SHA is the commit that adds this directory, reported in the final message.
Branch `feat/landscape-16x9`, working tree clean after that commit. `main` untouched at `567e63c`.

## Classification

| Item | Status | Evidence |
| --- | --- | --- |
| English frozen-card defect reproduced by a test | **VERIFIED** | 6 s of one repeated frame measured `[]` before the detector fix, >= 4.5 s after |
| Detector bug: a freeze to EOF was discarded | **VERIFIED, FIXED** | `test_the_detector_still_calls_a_repeated_frame_a_freeze` |
| Renderer root cause identified and measured | **VERIFIED** | `RENDERER_ROOT_CAUSE.md`, four failed attempts each with a number |
| Motion beat implemented | **VERIFIED** | push-in, two counter-rotating rings, two-phase light sweep |
| Motion is genuine, bounded and smooth | **VERIFIED** | per-frame diffs, 4 grey-level ceiling, no zero-velocity window |
| Type stays legible while moving | **VERIFIED** | headline pixel mass and contrast tests, frames inspected |
| Deterministic output for identical input | **VERIFIED** | byte-identical frames |
| Nexus Node portrait QC | **VERIFIED PASS** | 39.966 s, 0 failed checks, `8f60cf7f…` |
| Academic Biohacker portrait QC | **VERIFIED PASS** | 38.233 s, 0 failed checks, `c703817c…` |
| Natkhat Toons portrait QC | **VERIFIED PASS** | 32.135 s, `8d724eae…` |
| Natkhat Toons landscape QC | **VERIFIED PASS** | 64.501 s, 27/27, `c31d8d18…` |
| Full regression suite | **VERIFIED** | 811 passed |
| Golden frames unchanged | **VERIFIED** | 78 / 0 / 0 |
| Security and emergency-stop controls | **VERIFIED (unchanged)** | `SECURITY_AND_REGRESSION.md` |
| CI on the final commit | exact run IDs in the final message | — |
| Academic research "0 candidates" | **VERIFIED TRANSIENT** | re-run: 3 candidates, 0 errors |
| Research relevance floor for Academic | **FAILED (open defect)** | a Nature astronomy story tops a learning-science channel at 0.62 |
| Cloud rendering, OAuth, publishing, schedules | **BLOCKED / NOT IMPLEMENTED** | needs PR #3 merged, nine secrets, owner approval |

## Remaining defects

1. **Relevance floor.** Academic Biohacker accepted a Nature astronomy item at 0.62. The fix is a
   channel-specific term requirement, not a lower threshold.
2. **Natkhat portrait hash drift.** The portrait artifact is `8d724eae…` this pass against `1c695bf8…` and
   `07d07da2…` earlier, although the Hindi renderer was not modified. Not investigated; the audio bed or TTS
   path is the likely source. Claiming determinism there without measuring it would be wrong.
3. **Hand-off body overlap** (inherited).
4. **No coherent 10-minute episode** (inherited).

## Owner actions

Unchanged: merge PR #3, add the nine `YT_*` secrets, approve one `upload=false` cloud run, then enable
schedules; the two secret-scanning toggles and code scanning need the Settings UI.

## Verdict

**THREE-CHANNEL LOCAL ACCEPTANCE PASSED**

Three channels, four artifacts, zero failed checks, goldens intact, stop and security controls unregressed.
This proves local rendering and QC only. No cloud run, OAuth flow, upload or schedule was executed, so
nothing here is evidence of cloud production readiness.
