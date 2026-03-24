# Tools

This folder contains operational QA tools used by the automated workflows.

## Operational (used by workflows)
- `compare_manuals.py`  
  Generates QA outputs:
  - `gc_org_info_report.csv`
  - `missing_gc_org_ids.txt`
- `compare_org_concord.py`  
  Consistency checks between `gc_org_info.csv` and `gc_concordance.csv`.
- `negative_concordance_commits.py`  
  Generates clean archive outputs under `Archives/` (run by `daily-archive`).

## Committed reports
These outputs are committed intentionally for quick review:
- `gc_org_info_report.csv`
- `missing_gc_org_ids.txt`

## Removed / not operational
PDF generators, broken validators, and other one-off tools are intentionally not maintained in the automated pipeline.