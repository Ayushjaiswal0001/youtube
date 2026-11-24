# X100 per-episode QC reports

Generated from the artifacts in the acceptance build directory. Values are read from `render.json`, `qc.json`, `creative.json` and `manifest.json`; nothing here is transcribed by hand.

## nexus-node / nexus-small-models

- build directory: `nexus-small-models`
- video: 37.654 s, 8021819 bytes
- technical QC: ok=True checks=25 failed=0
- creative QC: ok=True checks=21 not-ok=['dataviz_delivered']
  - `visual_diversity_pixels`: 6 distinct pictures over 6 plates (1.00, minimum 0.5)
  - `no_repeated_composition_runs`: longest run of the same composition: 1
  - `figure_is_stated`: every number on screen is stated in the narration
  - `provenance_recorded`: every scene records asset id, source, licence and entities
  - `attribution_present`: attribution recorded wherever the licence requires it
- manifest: 10 artifacts, root ``

## nexus-node / nexus-robot-video

- build directory: `nexus-robot-video`
- video: 38.722 s, 8433016 bytes
- technical QC: ok=True checks=25 failed=0
- creative QC: ok=True checks=21 not-ok=['dataviz_delivered']
  - `visual_diversity_pixels`: 9 distinct pictures over 9 plates (1.00, minimum 0.5)
  - `no_repeated_composition_runs`: longest run of the same composition: 2
  - `figure_is_stated`: every number on screen is stated in the narration
  - `provenance_recorded`: every scene records asset id, source, licence and entities
  - `attribution_present`: attribution recorded wherever the licence requires it
- manifest: 10 artifacts, root ``

## academic-biohacker / academic-morning-light

- build directory: `academic-morning-light`
- video: 38.446 s, 8252342 bytes
- technical QC: ok=True checks=25 failed=0
- creative QC: ok=True checks=21 not-ok=[]
  - `visual_diversity_pixels`: 7 distinct pictures over 7 plates (1.00, minimum 0.5)
  - `no_repeated_composition_runs`: longest run of the same composition: 2
  - `figure_is_stated`: every number on screen is stated in the narration
  - `provenance_recorded`: every scene records asset id, source, licence and entities
  - `attribution_present`: attribution recorded wherever the licence requires it
- manifest: 10 artifacts, root ``

## academic-biohacker / academic-slow-breathing

- build directory: `academic-slow-breathing`
- video: 39.922 s, 8918985 bytes
- technical QC: ok=True checks=25 failed=0
- creative QC: ok=True checks=21 not-ok=['dataviz_delivered']
  - `visual_diversity_pixels`: 10 distinct pictures over 10 plates (1.00, minimum 0.5)
  - `no_repeated_composition_runs`: longest run of the same composition: 1
  - `figure_is_stated`: every number on screen is stated in the narration
  - `provenance_recorded`: every scene records asset id, source, licence and entities
  - `attribution_present`: attribution recorded wherever the licence requires it
- manifest: 10 artifacts, root ``

## natkhat-toons / natkhat-haveli-e1

- build directory: `natkhat-toons_natkhat-haveli-e1`
- video: 32.135 s, 5006448 bytes
- technical QC: ok=True checks=25 failed=0
- creative QC: not run (no scene plan for this engine)
- manifest: 8 artifacts, root ``

## nexus-node / long-nexus-power-grid (16:9)

- build directory: `long-nexus-power-grid`
- video: 223.078 s, 47431356 bytes
- technical QC: ok=True checks=25 failed=0
- creative QC: not run (no scene plan for this engine)
- manifest: 8 artifacts, root ``

