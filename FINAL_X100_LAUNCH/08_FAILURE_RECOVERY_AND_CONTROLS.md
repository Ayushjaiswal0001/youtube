# 08 — FAILURE RECOVERY AND CONTROLS

## Controls, verified by hand in this pass

| Control | Evidence |
| --- | --- |
| Per-channel pause blocks render | `render --channel natkhat-toons` gives `error: ProductionPaused: render is paused ...` |
| Per-channel pause blocks publish (new) | `publish --execute` gives `error: ProductionPaused: publish is paused for channel natkhat-toons`, raised before any artifact or credential is read |
| Resume clears the flag | `pause --resume` returns `{"removed": true}`, and the same command then proceeds to the gate |
| Global pause | `FACTORY_PAUSED=1` or a `PAUSED` file gives scope `global`; every channel is refused |
| The stop works without CI | the flag-file form needs no environment variable and no shell |
| Tests | 9 in `tests/factory/test_controls.py` |

## Notifications

`python -m factory.cli notify --message "..."` returns `{"notifier": "NullNotifier", "delivered": false}`
because no webhook is configured. Notifications are therefore `IMPLEMENTED BUT NOT VERIFIED`: the code path
exists, the workflow calls it on any failure, the payload carries job metadata only, and nothing has ever
been delivered.

## Determinism: the Natkhat hash drift is now explained

Two renders of one unchanged plan produced different files (`8d724eae...` and `6f801e1f...`, both 4.35 MB).

1. `script.json` and `story.json` differ only in timestamps and build paths, so the plan is deterministic.
2. The decoded video differs, and the difference is localised: at 10 s, 19 443 pixels differ in the character
   region; at 1 s, 25 s and 31 s the frames are byte-identical.
3. The narration MP3s are the same size and different bytes on every run.

Root cause: the TTS provider is a nondeterministic neural service (`edge_tts`, with a `gTTS` fallback). The
mouth and energy envelopes derive from it, so some frames change. Severity: **medium** - it affects neither
correctness nor QC nor publishing, but byte-level reproducibility cannot be claimed for voiced output.

Fixed en route: the SFX synthesiser used an unseeded `np.random.uniform` in
`studio/audio/sfx_library.py`; it is now seeded and the change is documented in the code.

Recommended future fix: cache TTS per text hash, and record a content hash (plan digest plus audio digest)
in the manifest instead of asserting byte identity.

## Recovery

Locking, atomic finalisation (`video.partial.mp4` then `os.replace`), the scene cache, the 11-state job
journal, resume and duplicate-upload reconciliation are implemented and unit-tested from earlier passes.
None of it has been exercised against a cancelled or interrupted GitHub run, because no cloud run exists.
Classification: `IMPLEMENTED BUT NOT VERIFIED` for cloud, `VERIFIED` for the local paths.
