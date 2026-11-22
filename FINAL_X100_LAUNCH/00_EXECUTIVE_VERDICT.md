# 00 — EXECUTIVE VERDICT

Commit at start of this directive: `01d72cc`. Ending commit: the one that adds this directory.
Branch `feat/landscape-16x9`; `main` untouched at `567e63c`.

| Milestone | Status |
| --- | --- |
| LOCAL FACTORY COMPLETE | **YES** — three channels render and pass QC (directive 07), 820 tests, 78 goldens |
| CLOUD FACTORY COMPLETE | **NO — BLOCKED** — `production.yml` is 404 on `main`; GitHub cannot dispatch it |
| THREE-CHANNEL PRIVATE PUBLISHING COMPLETE | **NO — BLOCKED** — 0 repository secrets, no OAuth consent, no upload attempted |
| AUTONOMOUS OPERATIONS ACTIVE | **NO** — 3 crons `disabled_manually`, owner-gated; notifications unconfigured |

Two defects were fixed in this pass and are verified locally:

1. **Research relevance.** A generic relevance score let a Nature astronomy story top the learning-science
   channel at 0.62. Channels now declare `focus_terms`, and an item that matches none of them scores 0 with
   the reason `off-niche`. Measured: academic-biohacker's top 3 candidates are now brain/immune/microbiome
   items, and the astronomy story is rejected.
2. **Publish had no pause check.** The global and per-channel pause guarded `render` but not `publish`.
   A paused channel now refuses at the first line of `cmd_publish`, before any artifact or credential is
   read — verified by hand: `error: ProductionPaused: publish is paused for channel natkhat-toons`.

One inherited defect is now explained rather than merely noted: the **Natkhat hash drift** is
non-determinism in the neural TTS (`edge-tts`, `gTTS` fallback). Two renders of one plan produce
same-size, different-byte narration MP3s, and the energy-driven mouth shapes then differ on some frames.
Detail and severity in `08_FAILURE_RECOVERY_AND_CONTROLS.md`.

Nothing was uploaded, scheduled, published, or merged. No credential exists in the repository.
