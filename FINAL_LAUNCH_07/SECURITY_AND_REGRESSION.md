# SECURITY AND REGRESSION

## Regression

| Check | Result |
| --- | --- |
| Full suite | **811 passed** (519 s) |
| New motion regression tests | 15 passed |
| Golden frames | **78 frames, 0 changed, 0 new** |
| Workflow audit | 7 workflows, 0 findings |
| Dependency audit | 0 unaccepted, 0 accepted |
| Emergency stop | unchanged, 8 tests green |
| Notifications | unchanged; silent without `FACTORY_NOTIFY_WEBHOOK` |

The renderer change is confined to `factory/media/english_renderer.py`, so the Hindi and character pipeline
is byte-identical and its goldens prove it.
`test_natkhat_toons_did_not_receive_the_english_camera_move` asserts the boundary explicitly.

## Security posture (unchanged this pass)

- No credential was added, printed, committed, or uploaded. The repository still holds 0 secrets.
- No workflow, permission, branch-protection rule, or publication flag was modified.
- No artifact, release, or schedule was created; publication gates remain `UPLOAD_ENABLED=false`,
  `SCHEDULED_PUBLISHING_ENABLED=false`, `PUBLICATION_APPROVAL_REQUIRED=true`.
- No new dependency was introduced; `numpy` and `Pillow` were already pinned.

## Deliberate strictness increase

`_freeze_events()` now also reports a freeze that runs to the end of the file, which the previous
implementation silently dropped. The gate can therefore only fail more often after this change, never less.
No threshold was raised: `freezedetect=n=-50dB:d=1.5` and the `frozen_frames` assertion are untouched, and
the -1.0 dBTP true-peak gate is untouched - the mix was fixed, not the gate.
