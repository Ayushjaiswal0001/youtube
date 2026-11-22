# Incident recovery

## A render was killed mid-episode

Nothing to undo. Scene state is written after each scene encodes and is verified by probe on reuse:

    python -m factory.cli status --channel X --format long     # shows missing / stale scenes
    python -m factory.cli resume --channel X --plan-id Y

Measured: deleting `video.mp4`, `qc.json` and one scene from a 12-scene episode and running `resume`
re-rendered exactly one scene in 59 s and produced a byte-identical episode.

## A lock was left behind

Locks carry pid, host, acquisition time and a heartbeat. A lock whose process is gone, or whose
heartbeat is older than 900 s, is taken over by the next run automatically. To clear one by hand:

    rm pipeline_state/locks/<channel>_<plan>.lock

Only do that when no production run is active: deleting a live lock allows a duplicate render.

## An upload's status is unknown

The ledger records `uploading` / `unknown` states, and `ops` reports them as a blocker. Do **not**
retry blindly. Investigate first:

    python -m uploader.cli verify --channel X     # which channel the credentials belong to
    python -m factory.cli ops --channel X         # ledger entries and video ids

If the video exists on the channel, record it rather than re-uploading (the ledger's duplicate guard
already refuses an `uploaded`, `uploading` or `unknown` hash).

## A finished artifact was deleted

Re-render. `sweep_disposable` only ever deletes `*.partial.mp4` and `*.tmp`, never `video.mp4`,
`qc.json`, `manifest.json` or anything else a package needs, so a deleted artifact was deleted by
something else - find that before re-rendering.

## The deployment itself

No cloud deployment exists yet, so there is nothing to roll back. If a cloud run fails, the local
factory is unaffected: state lives under `pipeline_state/` and `build/`, both per machine.
