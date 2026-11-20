# Test and evidence plan

## Stage 1: offline unit tests

Command:

```powershell
python -m unittest discover -s tests -v
```

Required coverage:

- legacy label mapping and redacted credential parsing;
- secret store save/load and overwrite refusal;
- channel config validation;
- identity ID/title/handle/customUrl checks;
- metadata defaults, validation, public guard, Natkhat `madeForKids` requirement;
- ledger duplicate and unknown-state behavior;
- OAuth URL and scope validation;
- log redaction;
- resumable upload request construction and `308` resume;
- router dry-run, wrong-channel abort, duplicate abort, simulated upload, and unknown/failed ledger transitions.

Evidence to retain:

- command;
- Python version;
- test count;
- pass/fail result;
- commit or local tree identifier.

## Stage 2: live read-only identity verification

Precondition: all three channels re-consented with upload + readonly scopes.

Commands:

```powershell
python -m uploader.cli scope-check --channel all --json
python -m uploader.cli verify --channel all --json
```

Required evidence per channel:

- credential source;
- scopes;
- expected channel ID/title/handle;
- token channel ID/title;
- handle lookup channel ID/title/custom URL;
- verified boolean.

No `videos.insert` call is made in this stage.

## Stage 3: dry-run routing

Use an approved local MP4. Run one router dry-run per channel.

```powershell
python -m uploader.cli dry-run --channel nexus-node `
  --video "C:\path\to\approved.mp4" `
  --title "Dry-run only" `
  --made-for-kids false --json
```

For Natkhat Toons, explicitly pass `--made-for-kids true` or `--made-for-kids false` and retain the decision.

Required evidence per channel:

- `status = dry_run_ok`;
- `upload_performed = false`;
- verified identity;
- video SHA-256;
- metadata SHA-256;
- duplicate check;
- privacy status;
- `madeForKids` decision.

Stop point: after all three dry-runs, stop and produce the milestone report. Do not run `upload --execute`.

## Stage 4: real upload

Blocked until separate explicit approval. A real upload must use:

```powershell
python -m uploader.cli upload --channel <slug> `
  --video "C:\path\to\approved.mp4" `
  --execute --confirm-channel <slug>
```

Public upload additionally requires approval and a channel config change. Scheduled public publishing is blocked until separately approved.
