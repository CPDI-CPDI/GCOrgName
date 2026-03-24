# Scraping

This folder contains scripts and intermediate outputs for sources that require scraping or non-trivial collection (e.g., FAA).

## What runs automatically
The daily update workflow runs:

- `scrapeAllFAA.py`  
  Retrieves FAA-related data.
- `combine_FAA_names.py`  
  Standardizes/combines FAA outputs into:
  - `combined_FAA_names.csv`

That combined FAA file is then merged into the concordance/org-info build.

## Outputs
- `combined_FAA_names.csv` is the main “product” of this folder.
Other files here may be intermediate and should be treated as generated artifacts unless explicitly documented.