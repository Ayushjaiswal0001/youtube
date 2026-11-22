# X100 CHANNEL ACCEPTANCE

Measured 2026-11-22. A channel is accepted only with its own research, its own render and a passing QC
report. Two of the three do not meet that bar.

| Requirement | Nexus Node | Academic Biohacker | Natkhat Toons |
| --- | --- | --- | --- |
| Config, identity, expected channel ID | PASS | PASS | PASS |
| Independent credential prefix | PASS (schema) | PASS (schema) | PASS (schema) |
| Research: sources reachable | 4 sources, 0 errors | 2 sources, 1 error | 0 feeds by design |
| Research: candidates surfaced | **3** | **0** | series bible, not feeds |
| Portrait Short rendered | 39.97 s | 38.23 s | 32.135 s |
| QC | **FAIL - frozen 1.5 s at 18.3 s** | **FAIL - frozen 2.2 s at 6.2 s** | **PASS** |
| Landscape long-form | not rendered | not rendered | **PASS** 64.501 s, 27/27, sha `bf93b056…` |
| Cloud render | blocked (PR #3) | blocked | blocked |
| Upload | no credentials | no credentials | no credentials |

## Root cause of the two failures

The English card renderer holds a static card while narration runs. `frozen_frames` allows 1.0 s; the
measured stillness is 1.5 s (Nexus) and 2.2 s (Academic). The fix is a motion beat on any card held longer
than a second - a type reveal, an animated diagram element, or a slow push-in. The threshold was left
exactly as it was: a gate that is relaxed to pass is no longer a gate.

## Research gaps

- Academic Biohacker produced zero candidates: one of its two feeds errored and the surviving items
  scored below the relevance floor. arXiv `q-bio` is a weak match for study technique; a learning-science
  source with explicit terms would serve it better.
- Natkhat Toons has no feed, deliberately: original Hindi stories are not discovered in the news. Its
  research basis is the series bible plus an originality/continuity record. The engine should report that
  explicitly instead of "0 sources" - outstanding work, not a missing configuration.
