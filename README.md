# GCOrgName

This repository produces the **current, best-available** concordance and organization info tables for Government of Canada organizations by integrating multiple public datasets plus curated manual mappings.

**Primary outputs (repo root):**
- `gc_concordance.csv` — “crosswalk” table (GC org ID + harmonized names + key source IDs/links)
- `gc_org_info.csv` — current organization info table (GC org ID + attributes)

**Historical lookups** (e.g., old RG numbers, past mappings) are handled in the `Archives/` outputs and are not kept in the “current truth” tables.

---

## How it runs

### Daily automation
Two GitHub Actions workflows maintain the repo:

- **`daily-update`**
  - downloads/refreshes source datasets
  - regenerates RG matching artifacts
  - rebuilds `gc_concordance.csv` and `gc_org_info.csv`
  - produces QA reports in `Tools/`

- **`daily-archive`**
  - runs after a successful `daily-update`
  - generates clean, searchable archival CSVs under `Archives/`

Schedule: Weekdays at **12:00 UTC** (7:00 AM EST / 8:00 AM EDT).

---

## Receiver General (RG) matching workflow (important)

RG matching is intentionally **human-in-the-loop**.

### Files
- `Resources/rg_matched.csv`  
  Machine-generated candidate match for each RG row (includes `MatchScore` and `CandidateCollision` flags).
- `Resources/rg_review_queue.csv`  
  Rows requiring human review (low confidence, missing IDs, collisions, etc.).
- `Resources/rg_fixed.csv`  
  **Manual-authoritative** reviewed resolutions for items in the current review queue.
- `Resources/rg_final.csv`  
  Resolved RG mapping used downstream. Built as:
  - all matched rows with **no issues**, plus
  - reviewed replacement rows from `rg_fixed.csv` for queued items.

### Operational rule
`rg_fixed.csv` is **not a historical dumping ground**. It is a reviewer-maintained response to the current `rg_review_queue.csv`.  
Historical RG lookups belong in `Archives/`.

### Review reminders
A separate workflow can open/update an issue when `rg_review_queue.csv` changes so reviewers know when `rg_fixed.csv` needs attention.

---

## Unmatched records

Some source records cannot be mapped to a GC org ID (e.g., a source dataset contains an org not represented in the manual mapping).

- `unmatched_org_IDs.csv` captures rows that are missing `gc_orgID` after merges.
- These rows are **not** included in `gc_concordance.csv`.

---

## Local run (optional)

From repo root:

```bash
pip install -r requirements.txt
python create_concordance.py
python create_gc_org_info.py