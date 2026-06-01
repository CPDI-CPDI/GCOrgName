import os
import pandas as pd

SCRIPT_FOLDER = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.dirname(SCRIPT_FOLDER)

MATCHED = os.path.join(RESOURCES, "Infobase", "infobase_matched.csv")
QUEUE = os.path.join(RESOURCES, "Infobase", "infobase_review_queue.csv")
FIXED = os.path.join(RESOURCES, "Infobase", "infobase_fixed.csv")

OUT_FINAL = os.path.join(RESOURCES, "Infobase", "infobase_final.csv")
OUT_MISSING = os.path.join(RESOURCES, "Infobase", "infobase_missing_fixes.csv")

def read_csv(path: str) -> pd.DataFrame:
    if os.path.exists(path):
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    return pd.DataFrame()

def main():
    matched = read_csv(MATCHED)
    queue = read_csv(QUEUE)
    fixed = read_csv(FIXED)

    if matched.empty:
        raise FileNotFoundError(f"Missing or empty: {MATCHED}")

    for df in (matched, queue, fixed):
        if "gc_orgID" in df.columns:
            df["gc_orgID"] = df["gc_orgID"].astype(str).str.split(".").str[0].str.strip()

    queue_ids = set(queue["gc_orgID"].tolist()) if ("gc_orgID" in queue.columns and not queue.empty) else set()

    # Base = matched rows not in queue
    base = matched[~matched["gc_orgID"].isin(queue_ids)].copy()

    # Fixed is reviewer response for queued items
    if not fixed.empty:
        # Expect at minimum: gc_orgID, infobaseID
        if "infobaseID" not in fixed.columns:
            # allow alternate column name from Candidate_infobaseID
            if "Candidate_infobaseID" in fixed.columns:
                fixed = fixed.rename(columns={"Candidate_infobaseID": "infobaseID"})
            else:
                raise ValueError("infobase_fixed.csv must contain column infobaseID")

        fixed_use = fixed[fixed["gc_orgID"].isin(queue_ids)].copy()
        fixed_use["infobaseID"] = fixed_use["infobaseID"].astype(str).str.split(".").str[0].str.strip()
    else:
        fixed_use = pd.DataFrame(columns=["gc_orgID", "infobaseID"])

    # Detect missing fixes
    fixed_set = set(fixed_use["gc_orgID"].tolist()) if not fixed_use.empty else set()
    missing = sorted(list(queue_ids - fixed_set))
    if missing:
        miss_df = queue[queue["gc_orgID"].isin(missing)].copy()
        miss_df.to_csv(OUT_MISSING, index=False, encoding="utf-8-sig")
    else:
        if os.path.exists(OUT_MISSING):
            os.remove(OUT_MISSING)

    # Produce final mapping table
    # Keep a concise schema for downstream use
    fixed_map = fixed_use[["gc_orgID", "infobaseID"]].copy() if not fixed_use.empty else pd.DataFrame(columns=["gc_orgID", "infobaseID"])

    # From base, carry Candidate_infobaseID as infobaseID
    base_map = base.copy()
    if "Candidate_infobaseID" in base_map.columns:
        base_map["infobaseID"] = base_map["Candidate_infobaseID"]
    elif "infobaseID" not in base_map.columns:
        raise ValueError("infobase_matched.csv missing Candidate_infobaseID")

    base_map = base_map[["gc_orgID", "infobaseID"]].copy()
    base_map["infobaseID"] = base_map["infobaseID"].astype(str).str.split(".").str[0].str.strip()

    final = pd.concat([base_map, fixed_map], ignore_index=True)
    final = final.drop_duplicates(subset=["gc_orgID"], keep="last").sort_values("gc_orgID")

    final.to_csv(OUT_FINAL, index=False, encoding="utf-8-sig")
    print(f"Wrote: {OUT_FINAL} ({len(final)} rows)")
    if missing:
        print(f"WARNING: missing fixes for {len(missing)} queued items → {OUT_MISSING}")

if __name__ == "__main__":
    main()