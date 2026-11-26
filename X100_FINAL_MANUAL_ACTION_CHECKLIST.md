# X100 final manual action checklist

Snapshot date: 2026-11-26 (Asia/Calcutta)
Repository: [Ayushjaiswal0001/youtube](https://github.com/Ayushjaiswal0001/youtube)
Open candidate: [PR #23](https://github.com/Ayushjaiswal0001/youtube/pull/23)
Branch: `codex/fix-joblock-ownership`

Complete these actions in order. No action below requires sharing a secret.

## 1. Obtain an independent review of PR #23

**Why this is manual:** The collaborator API currently returns only `Ayushjaiswal0001`, who authored PR #23. Branch protection currently requires zero approving reviews, so the platform does not enforce the independent review required by this handover.

**What is done:** The focused PR is open, the PR description requests independent review, and the final JobLock fix plus tests are published.

**What to do:** As repository owner, identify a separate qualified maintainer. If they do not already have appropriate review access, open the repository on GitHub → **Settings** → **Collaborators and teams** → **Add people** and grant the minimum access needed to submit an approving review. Then open PR #23 → **Reviewers** → select that maintainer. Ask them to review `factory/reliability.py`, `factory/orchestrator.py`, the lock regression tests, and the production publishing gates.

**Expected result:** A separate maintainer is listed as a requested reviewer and submits an approving review after examining the final head.

**Do not:** Self-approve, bypass a review, change branch protection to weaken checks, or merge before review.

**Blocks merge and activation:** Yes.

## 2. Wait for all checks on the latest PR head

**Why this needs owner follow-through:** GitHub Actions started final-head CI and security after commit `528ec22`; documentation updates trigger another run. Only the latest PR head is authoritative.

**Command:** In PowerShell, from any directory with GitHub CLI authenticated:

```powershell
gh pr checks 23 --repo Ayushjaiswal0001/youtube --watch
```

Also confirm the latest head SHA and review state:

```powershell
gh pr view 23 --repo Ayushjaiswal0001/youtube --json headRefOid,state,reviewDecision,reviewRequests,statusCheckRollup
```

**Expected result:** `factory (plan + publish gates)`, `uploader (py3.11)`, `uploader (py3.12)`, and all four security jobs pass on the same latest head. The Ubuntu factory job must include native POSIX `flock` and POSIX process-kill coverage. If any job fails, do not merge; inspect its run logs and fix the actual failure.

**Do not:** Treat CI from `c653cfa` or main as proof for a newer PR head, or cancel/skip required checks.

**Blocks merge and activation:** Yes.

## 3. Merge through the normal PR process

**What is done:** PR #23 targets `main`; the repository currently allows merge commit, squash, and rebase. No merge was performed.

**What to do:** After the independent approval and all latest-head checks pass, use PR #23's enabled normal merge control (Squash and merge is suitable for this focused change). Do not use an admin override. Then verify:

```powershell
gh pr view 23 --repo Ayushjaiswal0001/youtube --json state,mergedAt,mergeCommit
gh run list --repo Ayushjaiswal0001/youtube --branch main --limit 10
```

**Expected result:** PR #23 reports `MERGED`, a merge commit SHA is present, and CI/security pass on that resulting main SHA.

**Do not:** Push directly to `main`, force-push, bypass branch rules, or merge while checks/review are pending.

**Blocks production activation:** Yes.

## 4. Review only the corrected media derivatives

**What is done:** Both derivatives were re-probed, decoded, audio-measured, subtitle-checked, and contact-sheet sampled. Original media remains unchanged.

**What to review:** Open and watch/listen to these outputs in a local media player; inspect narration, captions, on-screen text, source qualification, music, and endings:

- `D:\X100-youtube\audit-artifacts\corrected-2026-11-26\build\academic-biohacker\academic-post-meal-walk\video.mp4`
- `D:\X100-youtube\audit-artifacts\corrected-2026-11-26\build\nexus-node\nexus-data-wall\video.mp4`

Compare the corrected wording to `content/topics/academic-biohacker.json`, `content/topics/nexus-node.json`, and `content/batch_2026-11-20.json` in the PR. Record editorial acceptance or request a specific correction.

**Expected result:** Owner/editor confirms the corrected claims and final narration are suitable, or requests a targeted correction and rerender.

**Do not:** Release the preserved old Academic or Nexus videos; they contain stale copy. Do not treat contact-sheet or numeric audio checks as subjective review.

**Blocks release of these two plans:** Yes.

## 5. Run a fresh owner-controlled, non-secret preflight

**Why this is manual:** This environment did not verify live YouTube identity, private pending releases, stored `publishAt`, or account-wide/channel-specific pause state. Repository Actions variables returned an empty list; that is not a YouTube status check.

**What to verify:** In GitHub Actions, confirm the three daily workflows remain disabled until activation is approved and the manual production workflow is idle. Using the owner's approved non-secret status procedure, verify global/channel pause, channel identity, available plan, duplicate reservations, upload ledger, channel policy, and pending YouTube releases. Confirm the intended video is private and that the stored `publishAt` equals the intended release time after any upload.

**Expected result:** A written, timestamped preflight record with channel identity and pending-release results, without secret values.

**Do not:** Read, paste, print, or change OAuth values or scopes. Do not infer an actual YouTube schedule from a calculated timestamp or local plan query.

**Blocks activation:** Yes.

## 6. Explicitly approve and activate Nexus only

**Owner approval required:** Send explicit approval for the first production activation after PR merge, green checks, independent review, media review, and fresh preflight. This handover does not provide that approval.

After that approval, the authorized owner may enable the Nexus daily workflow:

```powershell
gh workflow enable "nexus-node daily" --repo Ayushjaiswal0001/youtube
```

Observe the next scheduled run. Verify the workflow event, channel identity, Short and horizontal outputs, upload outcomes, video IDs, private status, `schedule_verified`, and YouTube-stored `publishAt`. If any check fails, keep the item private and disable the affected workflow while investigating. Do not dispatch a manual production job as a substitute for scheduled verification.

Only after Nexus is independently verified should the owner consider Academic. Consider Natkhat only after Academic is independently verified; retain its `madeForKids=true` policy. No automatic progression is authorized.

**Do not click or run:** workflow enable, workflow dispatch, upload, scheduling, policy changes, credential changes, or public release before the explicit owner approval.

**Blocks activation:** Yes.
