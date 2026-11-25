# X100 final quality audit

Audit window: 2026-11-25–26. Repository: `Ayushjaiswal0001/youtube`; base `main` `01f3abd4078abca30eabbd6822139130121a72d7`; fix branch `codex/fix-publishing-policy-clock-test`.

## Test and CI evidence

- Merge-commit CI run `45655992920` failed in `factory (plan + publish gates)` after 1,371 passed, 2 skipped, and 1 failed in that job. Six other merge-commit checks passed; the security run passed all four jobs.
- Failure: `test_publish_looks_up_the_release_for_its_own_plan` used the actual clock with a fixed November 25 20:00 IST release. CI reached it more than 90 minutes after that instant, so the production resolver correctly refused the late release and the test's expectation was invalid.
- The test is now isolated from wall-clock time by invoking the real resolver at a fixed time before its intended release. The focused test passed locally on Python 3.12.7 / Windows 11: `1 passed in 0.81s`.
- The same local regression run exposed `os.kill(pid, 0)` interrupting Windows when the lock check examined a live process. `factory/reliability.py` now checks a waitable Win32 process handle and treats uncertain access as live. `tests/factory/test_reliability.py`: 38 passed in 2.06s after the fix.
- A second publishing-policy test failed near midnight because it used the wall clock and represented the previous day's time as an ambiguous time-only value. It now pins the real resolver to 20:05 IST and passed with the full file: 36 passed in 3.01s.
- Original exhaustive local suite: 1,451 passed, 0 failed, 0 skipped, and 5 successful subtests across six disjoint module batches; cumulative runtime 1,009.88 seconds. After the workflow-audit regression tests were added, the new targeted module passed 3/3. Final branch collection and full CI remain pending; exact original commands and module groups are recorded in the closure report.

## Security workflow review

- Completed Standard review `809f271b-0654-454a-9ea3-c7579717dada` found one high-confidence CWE-78 in its pre-fix working-tree snapshot: manually supplied `plan_id` was emitted as a workflow step output and interpolated into Bash source in the credential-bearing upload step.
- The focused branch normalizes the ID with `slugify` before writing it as output, no longer writes the raw dispatch input to `GITHUB_OUTPUT`, and passes step outputs through environment variables instead of embedding them in shell source. The scanner was also fixed to inspect multiline `run:` scripts; three new regression tests pass.
- Current local checks: `python -m tools.workflow_audit` — 7 workflows, 0 findings; `python -m tools.secret_scan` — 0 findings; reusable workflow YAML parse — passed. The pre-fix scan is not a post-remediation scan, and branch CI/security checks are pending.
- The base security workflow passed run `45655992820`, though its previous audit missed this multiline shell interpolation. OAuth values were not inspected. Daybreak access was not granted, no independent reviewer was assigned, and pip-audit was not rerun locally.

## Production artifacts inspected

Downloaded GitHub Actions artifacts for a Short and a horizontal episode for each channel, plus a second Nexus Short. Probed with FFprobe 8.0.1, decoded through FFmpeg, sampled five frames across each video, and independently measured encoded audio using FFmpeg EBU R128.

| Channel / format | Representative artifact | Duration | Geometry / fps | Encoded loudness / true peak | Visual sample assessment |
| --- | --- | ---: | --- | --- | --- |
| Nexus Short | `nexus-data-wall` | 41.967 s | 1080×1920 / 30 | −14.2 LUFS / −2.5 dBTP | Distinct technical plates; title and timed captions remained inside the frame |
| Nexus horizontal | `long-nexus-power-grid` | 214.067 s | 1920×1080 / 30 | −14.1 LUFS / −2.3 dBTP | Clear chapter-card hierarchy, readable captions, varied diagrams |
| Academic Short | `academic-post-meal-walk` | 38.367 s | 1080×1920 / 30 | −14.2 LUFS / −2.3 dBTP | Evidence-paper palette and relevant chart/pictogram scenes; caption line breaks should be reviewed at handset scale |
| Academic horizontal | `long-academic-study-protocol` | 218.933 s | 1920×1080 / 30 | −14.3 LUFS / −2.1 dBTP | Clear card and diagram layouts; dense paragraphs in some cards are small at preview size |
| Natkhat Short | `natkhat-haveli-e1` | 32.100 s | 1080×1920 / 30 | −14.1 LUFS / −1.4 dBTP | Hindi captions and character identity visible; intentionally dark haunted setting, with adequate contrast in inspected frames |
| Natkhat horizontal | `natkhat-haveli-stage-e1` | 64.500 s | 1920×1080 / 30 | −14.1 LUFS / −1.4 dBTP | Character poses and Hindi subtitle band vary across scenes; repeated background is intentional but scene variety is limited |

FFmpeg reported no decode errors for the six inspected files. The bundled QC and publishing-gate JSONs for the artifacts also report passing checks; see the specific artifacts and job runs rather than inferring this from filenames. The loudness results above are measurements from the downloaded encoded AAC tracks, not source WAV files. True peaks are below the project −1 dBTP gate; Natkhat has the smallest headroom.

The images establish representative visual appearance, not full-resolution human review of every frame. The short Natkhat episode is a story sample, not a complete child-safety certification. Separate YouTube caption-track attachment is not demonstrated; local SRT and burned-in captions are separate capabilities.

## Content/editorial findings

- Sample scripts preserve distinct channel identities and their language settings. Natkhat dialogue is Hindi and child-appropriate in the inspected sample; no harmful content was found in that sample.
- Academic scripts use qualifying language, but some source fields are broad search or institution landing pages rather than direct study links. A reviewed health Short cites a PubMed search and WHO activity page; evidence traceability should be improved for future topics.
- Corrected the available Nexus evaluation Short on this branch: it now describes contamination as a risk (“can be misleading”), recommends held-out workload examples as a complement to public comparisons, and links directly to the primary contamination study at `https://arxiv.org/abs/2310.18018` plus Stanford HELM. The broader bank still contains some search and institution landing-page sources, so future plan claims need source-level review.
- Historical QC warnings (for example missing dataviz when scripts contain no quantitative claim) are warnings, not suppressed failures.

## Coverage limits

GitHub artifacts provide six independently inspectable channel/format samples, but do not prove every script, every frame, every future plan, or actual YouTube scheduled-public behavior. Manual full-resolution frame-by-frame review, long-run reliability over repeated daily releases, and real scheduled-release verification remain outside the evidence collected here.
