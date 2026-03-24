# Archives

Archives are **historical lookup tables** generated from git history. They are designed to answer:

- “What used to map to `gc_orgID = X`?”
- “When did a mapping change?”
- “What changed last week/month?”

Archives are not used as current truth and should not be merged back into `gc_concordance.csv` / `gc_org_info.csv`.

## Files
- `archive_events.csv`  
  Canonical event log containing added/removed/modified events for:
  - `gc_concordance.csv`
  - `gc_org_info.csv`

- `concordance_archive_by_date.csv`  
- `concordance_archive_by_ID.csv`  
- `org_info_archive_by_date.csv`  
- `org_info_archive_by_ID.csv`  

These are “views” of the event log sorted for easy filtering.

## Columns
Each row represents a change event with:
- `commit_hash`
- `commit_date`
- `change_type` (`added`, `removed`, `modified`)
- `gc_orgID` (when available)
- `row_before_json` / `row_after_json` snapshots

## How to use
### Lookup by org
Filter `*_by_ID.csv` on `gc_orgID`.

### Lookup by time range
Use `*_by_date.csv` and filter by `commit_date`.

### Reconstruct a prior row
Use the JSON snapshot columns (`row_before_json` / `row_after_json`).