# X100 final activation handover

Date: 2026-11-26 (IST)

## A. Current repository state

- Repository: `Ayushjaiswal0001/youtube`, cloned in isolation to `D:\X100-youtube` because `D:\animated` is an unrelated working tree with user changes.
- Current `main`: `01f3abd4078abca30eabbd6822139130121a72d7`, merge commit for PR #21.
- PR #21 is merged. Its checks were green before merge. A new CI run on the merge commit failed one factory test; the security workflow passed.
- Current focused branch: `codex/fix-publishing-policy-clock-test`; the original exhaustive local suite passed 1,451 tests (0 failures, 0 skips, 5 successful subtests) across six module batches. After adding three workflow-auditor regression checks, those targeted tests passed 3/3. The final 1,454-test branch CI run is pending.
- All three publishing workflows were freshly checked with `gh workflow list --all`: `nexus-node daily`, `academic-biohacker daily`, and `natkhat-toons daily` are `disabled_manually`.

## B. Defect and fix status

Merge-commit CI run `45655992920` failed only `test_publish_looks_up_the_release_for_its_own_plan`. The test used a fixed release date but did not freeze the resolver clock, making it fail after the 90-minute late grace. The resolver behaved safely and refused the missed release. The focused test now pins the resolver to before the configured release. Local Windows testing also found and fixed the `os.kill(pid, 0)` lock-check bug, which generated Ctrl+C on Windows, and stabilized a second publishing test around the IST midnight boundary. Security review also found a high-confidence shell injection path from manual `plan_id` input into the credential-bearing upload command. The branch normalizes plan IDs before writing step outputs, removes raw input serialization, and passes step outputs through environment variables. The workflow auditor now checks multiline `run:` scripts; its new 3-test module passes. Full branch CI remains pending.

## C. Fresh channel/config preflight

| Channel | Configured policy | Cron UTC → IST start | Configured release IST | Live workflow |
| --- | --- | --- | --- | --- |
| Nexus Node | scheduled; scheduled upload; shift; 90-minute grace; 15-minute minimum lead | `30 12 * * *` → 18:00 | 20:00 | disabled_manually |
| Academic Biohacker | scheduled; scheduled upload; shift; 90-minute grace; 15-minute minimum lead | `30 4 * * *` → 10:00 | 12:00 | disabled_manually |
| Natkhat Toons | scheduled; scheduled upload; shift; 90-minute minimum lead; made-for-kids forced true | `30 10 * * *` → 16:00 | 18:00 | disabled_manually |

Read-only plan commands found four unused topic entries each for Nexus and Academic, and six authored Natkhat Shorts across its three remaining Haveli episodes plus three Jungle episodes. The next Natkhat Short is `natkhat-haveli-e4`. There is one authored horizontal plan per channel. All six format/channel combinations report a plan available now. This is local repository state, not a promise that a plan is still available when the cron fires.

The read-only local pause check returned `paused: false`, scope `none`. The production runner's pause state, actual YouTube pending releases, live duplicate state, and OAuth capability were not independently inspected. No secrets were read. Prior reports' “not paused/no pending” statements remain historical until checked in an authorized runtime.

## D. Nexus next-run calculation

At the audit date of 2026-11-26, if any daily workflow is enabled, the next configured start is Academic Biohacker at **2026-11-26 10:00 IST**, followed by Natkhat at 16:00 and Nexus at 18:00. The Nexus release is **2026-11-26 20:00 IST**, requested as `publishAt=2026-11-26T14:30:00Z`. All three workflows are currently disabled, so these are configuration times, not live scheduled runs.

The workflow's Short and horizontal jobs run independently. Both should check availability, render/resume, pass QC, manifest and publishing gate, then upload privately. `verify_schedule()` must read back the actual `publishAt` and only report success on a matching value. There has not yet been a production scheduled-release activation proving YouTube honors this request.

## E. Owner activation boundary

Do not enable or dispatch a workflow while the merge-commit CI failure remains unresolved, the current PR checks are pending, or the focused changes are unreviewed. After the branch checks are green and the owner reviews and merges the PR, verify main contains the fixes, Nexus remains disabled, and current runtime state/content are clear. Only then—after explicit owner approval—enable Nexus alone:

```powershell
gh workflow enable "nexus-node daily" --repo Ayushjaiswal0001/youtube
```

This task did not enable, dispatch, upload, or schedule anything. Do not activate Academic Biohacker or Natkhat automatically.

## F. Emergency stop

```powershell
gh workflow disable "nexus-node daily" --repo Ayushjaiswal0001/youtube
python -m factory.cli pause
```

The first stops future Nexus triggers; the second creates the global pause flag. `pause --channel all --reason ...` is not valid: this CLI has no `--reason`, and `--channel all` is not the global pause. Disabling a workflow does not stop a running job or cancel a YouTube schedule that already exists. Use run cancellation and YouTube Studio for those states.

## G. First-run evidence to require

In Actions: schedule trigger only; both format jobs; expected channel and plans; availability true; render, QC, manifest, gate, and package pass; private uploads and channel identity checks pass; `schedule_verified=true`; no duplicate or unexpected immediate publication.

In YouTube metadata/Studio: inspect both video IDs on the intended channel, confirm `privacyStatus=private` before release and the exact `publishAt=2026-11-26T14:30:00Z`. Preserve Actions and metadata evidence. Mark Nexus validated only after YouTube confirms the scheduled state. A mismatch is a stop-and-investigate event; keep the video private.

## H. Owner actions

1. Review the publishing-policy, Windows lock portability, shell-injection, and content-source fixes; wait for final branch CI.
2. Merge the focused PR only after review and green checks; no merge has been requested or performed here.
3. Run a fresh runtime preflight for pause state, pending releases, duplicate plans, and content availability without exposing secret values.
4. Decide whether to accept the thumbnail, caption, schedule-modification, and finite-content limitations in [X100_KNOWN_LIMITATIONS.md](X100_KNOWN_LIMITATIONS.md).
5. Give explicit approval before the Nexus enable command.
6. Inspect and verify the first Nexus run before considering another channel.
