# 05 — EDITORIAL AND METADATA QC

## Fixed: channel-specific relevance

Before: `score = 0.55·relevance + 0.30·freshness + 0.15·quality` against a short niche string. A Nature
astronomy story reached **0.62** and topped Academic Biohacker.

After: each channel declares `focus_terms`, matched as case-insensitive prefixes against the headline and
summary. No match → `score = 0.0`, reason `off-niche: none of this channel's focus terms appear in the
headline or summary`. A match adds `on-niche: <terms>`.

Measured with the live feeds on 2026-11-22:

| Channel | Before | After |
| --- | --- | --- |
| academic-biohacker | astronomy story at 0.62 was the top candidate | 3 can
