# X100 OPERATIONS GUIDE

## Daily

```bash
env -u GITHUB_TOKEN gh workflow run production.yml --ref main \
  -f channel=natkhat-toons -f mode=render+validate -f upload=false
env -u GITHUB_TOKEN gh run list --workflow=production.yml --limit 5
python -m factory.cli ops --channel natkhat-toons        # jobs, artifacts, uploads, blockers
python -m factory.cli status --channel natkhat-toons     # per-plan state
```

## Pause — channel or everything

```bash
python -m factory.cli pause --channel natkhat-toons       # flag file in the state directory
python -m factory.cli pause --resume --channel natkhat-toons
python -m factory.cli pause                                # global stop

# In GitHub, without a checkout: set repository variables
#   FACTORY_PAUSED=1                (all channels)
#   FACTORY_PAUSED_CHANNELS=nexus-node,academic-biohacker
```

Both levels are checked at the start of every production run and before any upload; a pause raises
`ProductionPaused` rather than returning a value a caller could ignore. Verified by test and by hand.

## Retry, recovery, resume

```bash
python -m factory.cli resume --channel natkhat-toons       # continue unfinished work
python -m factory.cli preflight                            # disk, memory, ffmpeg, cairo, fonts
python -m factory.cli gate --channel natkhat-toons         # 24 publishing checks
```
A scene that rendered successfully is never re-rendered: the scene cache is keyed by a deny-list
signature plus a probe, and finalisation is atomic (`video.partial.mp4` → `os.replace`).

## Notifications

```bash
python -m factory.cli notify --subject "test" --message "hello"   # exit 1 when unconfigured
```
Set `FACTORY_NOTIFY_WEBHOOK` to any endpoint accepting a JSON POST. Payloads carry job metadata only —
never tokens, never environment dumps. The workflow calls this on any failure.

## Uploads

```bash
python -m fa
