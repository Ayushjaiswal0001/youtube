# 06 — SCHEDULING AND AUTOMATION

**Status: NOT ACTIVE.** Three scheduled workflows exist and all are `disabled_manually`:
`produce-nexus-node.yml`, `produce-academic-biohacker.yml`, `produce-natkhat-toons.yml`.

They were not enabled, and they must not be until all of the following hold: cloud render passes, all three
channel identities authenticate, all three private uploads verify, notifications deliver, the emergency stop
is exercised against a real run, and the owner approves activation.

## Capacity for the proposed schedule (measured locally, not on a runner)

| Channel | 3 Shorts + 1 long-form per week | Wall |
| --- | --- | --- |
| Nexus Node | 3 x 186 s + ~300 s | about 16 min |
| Academic Biohacker | 3 x 202 s + ~300 s | about 19 min |
| Natkhat Toons | 3 x 150 s + 287 s | about 15 min |

About 50 minutes of runner time per week, peak RSS below 120 MB, output below 12 MB per Short. That fits a
hosted runner comfortably. The open risk is not capacity but the TTS network dependency (`edge-tts`) at
render time.

Timezone for the intended schedules: `Asia/Kolkata`, staggered so the three channels never publish at once.
The per-channel publish times are already configured: 20:00, 12:00 and 18:00 IST.
