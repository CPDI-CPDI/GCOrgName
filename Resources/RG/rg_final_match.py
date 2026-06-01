import os
import pandas as pd


def _read_csv(path: str) -> pd.DataFrame:
    """Read CSV robustly as strings (preserve leading zeros, avoid NaN coercion)."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def _norm_str(s: str) -> str:
    if s is None:
        return ""
    return str(s).strip()


def _strip_trailing_dot_zero(s: str) -> str:
    """
    Normalize values like '123.0' -> '123' without converting to numeric.
    Useful for gc_orgID coming from Excel-ish sources.
    """
    s = _norm_str(s)
    if s.endswith(".0") and s.replace(".0", "").isdigit():
        return s[:-2]
    return s


def _ensure_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df


def main():
    repo_root = os.getcwd()

    matched_path = os.path.join(repo_root, "Resources", "RG", "rg_matched.csv")
    reviewq_path = os.path.join(repo_root, "Resources", "RG", "rg_review_queue.csv")
    fixed_path = os.path.join(repo_root, "Resources", "RG", "rg_fixed.csv")

    out_final_path = os.path.join(repo_root, "Resources", "RG", "rg_final.csv")
    out_missing_fixes_path = os.path.join(repo_root, "Resources", "RG", "rg_final_missing_fixes.csv")

    # --- Load inputs ---
    if not os.path.exists(matched_path):
        raise FileNotFoundError(f"Missing required file: {matched_path}")

    matched_df = _read_csv(matched_path)

    # Review queue is optional; if missing, treat as empty (no issue rows)
    if os.path.exists(reviewq_path):
        review_df = _read_csv(reviewq_path)
    else:
        review_df = pd.DataFrame(columns=["RGOriginalName"])

    # Fixed is optional but normally present; if missing, treat as empty fixes
    if os.path.exists(fixed_path):
        fixed_df = _read_csv(fixed_path)
    else:
        fixed_df = pd.DataFrame(columns=["RGOriginalName"])

    # --- Normalize key column ---
    matched_df = _ensure_cols(matched_df, ["RGOriginalName"])
    review_df = _ensure_cols(review_df, ["RGOriginalName"])
    fixed_df = _ensure_cols(fixed_df, ["RGOriginalName"])

    matched_df["RGOriginalName"] = matched_df["RGOriginalName"].map(_norm_str)
    review_df["RGOriginalName"] = review_df["RGOriginalName"].map(_norm_str)
    fixed_df["RGOriginalName"] = fixed_df["RGOriginalName"].map(_norm_str)

    # Remove empty-name rows from key sets
    issue_names = set(n for n in review_df["RGOriginalName"].tolist() if n)

    # --- Base set: matched rows NOT in review queue ---
    base_df = matched_df[~matched_df["RGOriginalName"].isin(issue_names)].copy()

    # --- Reviewed set: fixed rows IN review queue ---
    reviewed_df = fixed_df[fixed_df["RGOriginalName"].isin(issue_names)].copy()

    # Normalize IDs/fields without turning blanks into 0 or losing leading zeros
    for df in (base_df, reviewed_df):
        if "gc_orgID" in df.columns:
            df["gc_orgID"] = df["gc_orgID"].map(_strip_trailing_dot_zero)
        if "rgnumber" in df.columns:
            df["rgnumber"] = df["rgnumber"].map(_strip_trailing_dot_zero)

    # Ensure CandidateCollision exists for both (helpful for downstream visibility)
    base_df = _ensure_cols(base_df, ["CandidateCollision"])
    reviewed_df = _ensure_cols(reviewed_df, ["CandidateCollision"])

    # For reviewed rows, collision flag is not meaningful unless reviewer sets it; default blank
    reviewed_df["CandidateCollision"] = reviewed_df["CandidateCollision"].map(_norm_str)

    # --- Validate coverage: queue items missing fixes ---
    fixed_name_set = set(n for n in reviewed_df["RGOriginalName"].tolist() if n)
    missing = sorted(list(issue_names - fixed_name_set))

    if missing:
        # Include a compact diagnostic with queue context
        diag_cols = []
        for c in ["RGOriginalName", "rgnumber", "MatchedName", "MatchScore", "gc_orgID", "CandidateCollision", "ReviewReasons"]:
            if c in review_df.columns:
                diag_cols.append(c)
        if not diag_cols:
            diag_cols = ["RGOriginalName"]

        missing_df = review_df[review_df["RGOriginalName"].isin(missing)].copy()
        missing_df = missing_df[diag_cols]
        missing_df.to_csv(out_missing_fixes_path, index=False, encoding="utf-8-sig")
    else:
        # If previously existed, remove stale diagnostic
        if os.path.exists(out_missing_fixes_path):
            os.remove(out_missing_fixes_path)

    # --- Final union ---
    final_df = pd.concat([base_df, reviewed_df], ignore_index=True)

    # As a safety: never manufacture gc_orgID=0
    if "gc_orgID" in final_df.columns:
        final_df["gc_orgID"] = final_df["gc_orgID"].map(_strip_trailing_dot_zero)
        # If someone literally has "0" in source, keep it (we won't rewrite),
        # but we won't create it.

    # Keep a stable, sensible column order (preserve any extra columns at end)
    preferred_order = [
        "RGOriginalName",
        "rgnumber",
        "MatchedName",
        "MatchScore",
        "Organization Legal Name English",
        "gc_orgID",
        "CandidateCollision",
    ]
    existing = [c for c in preferred_order if c in final_df.columns]
    extras = [c for c in final_df.columns if c not in existing]
    final_df = final_df[existing + extras]

    final_df.to_csv(out_final_path, index=False, encoding="utf-8-sig")

    print(f"RG final written: {out_final_path}")
    if missing:
        print(f"WARNING: Missing fixes for {len(missing)} queue items. See: {out_missing_fixes_path}")
    else:
        print("All queue items have reviewed fixes (or queue is empty).")


if __name__ == "__main__":
    main()