# 04 — PRIVATE UPLOAD VERIFICATION

**Status: BLOCKED. No upload attempted, no video ID exists.**

Evidence that the gates are real rather than decorative, measured in this pass:

- `python -m factory.cli gate --channel natkhat-toons` → `gate=BLOCKED 19/22` for the plan with no artifacts
  in the current build directory, `16/23` for the empty ones. The gate reports its blockers by name
  (`loudness`, `framing`, `manifest`, `subtitles`, `thumbnail`, `qc_report`, `silence_policy`).
- `python -m factory.cli publish --channel natkhat-toons --plan-id natkhat-haveli-e1 --execute
  --confirm-channel natkhat-toons` → `error: PermissionError: publishing gate failed: loudness, framing,
  manifest`. There is no code path in which `--execute` proceeds on a failing gate.
- With the channel paused, the same command stops earlier: `error: ProductionPaused: publish is paused for
  channel natkhat-toons`. That guard was added in this pass; before it, `publish` ignored the pause.

Reproduction steps once secrets exist: dispatch `production.yml` with `upload=false` for each channel,
verify the artifacts, then run the publish step once per channel with `--execute` and confirm PRIVATE
privacy plus the returned video ID through the API.
