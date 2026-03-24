import subprocess
import pandas as pd
import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Tuple

ARCHIVES_DIR = "Archives"

CONCORD_PATH = "gc_concordance.csv"
ORGINFO_PATH = "gc_org_info.csv"

OUT_CONCORD = os.path.join(ARCHIVES_DIR, "concordance_events.csv")
OUT_ORGINFO = os.path.join(ARCHIVES_DIR, "org_info_events.csv")
OUT_SKIPPED = os.path.join(ARCHIVES_DIR, "archive_skipped_commits.csv")


# ------------------ git helpers ------------------
def run_git(args: List[str]) -> str:
    out = subprocess.check_output(["git"] + args)
    return out.decode("utf-8", errors="replace")


def git_show(commit: str, path: str) -> Optional[str]:
    """Return file content at commit, or None if file doesn't exist there."""
    try:
        return run_git(["show", f"{commit}:{path}"])
    except subprocess.CalledProcessError:
        return None


def first_parent(commit: str) -> Optional[str]:
    """Return first parent commit, or None for root commits."""
    try:
        parts = run_git(["rev-list", "--parents", "-n", "1", commit]).strip().split()
        return parts[1] if len(parts) > 1 else None
    except subprocess.CalledProcessError:
        return None


def list_commits_touching(path: str) -> List[str]:
    """Commits (newest->oldest) that touched path."""
    try:
        out = run_git(["log", "--format=%H", "--", path]).strip()
        return out.splitlines() if out else []
    except subprocess.CalledProcessError:
        return []


def git_commit_date(commit: str) -> str:
    """Commit date string in %ci format: 'YYYY-MM-DD HH:MM:SS +/-ZZZZ'."""
    return run_git(["show", "-s", "--format=%ci", commit]).strip()


def parse_commit_dt(commit_date_str: str) -> Optional[datetime]:
    """Parse %ci format; return aware datetime."""
    try:
        return datetime.strptime(commit_date_str, "%Y-%m-%d %H:%M:%S %z")
    except Exception:
        return None


def utc_day_key(dt: datetime) -> str:
    """UTC calendar day key (YYYY-MM-DD)."""
    # Convert aware dt to UTC by using timestamp then fromtimestamp with tz=UTC is overkill;
    # simplest: dt.astimezone(datetime.timezone.utc) requires timezone import.
    # We'll do a manual parse: datetime supports astimezone without explicit UTC tz in Py 3.11 via timezone.utc.
    from datetime import timezone
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


# ------------------ csv helpers ------------------
def read_csv_text(csv_text: str) -> pd.DataFrame:
    """Read CSV from text robustly as strings (preserve blanks)."""
    from io import StringIO
    return pd.read_csv(
        StringIO(csv_text),
        dtype=str,
        keep_default_na=False,
        encoding_errors="replace"
    )


def has_duplicate_columns(df: pd.DataFrame) -> bool:
    return bool(df.columns.duplicated().any())


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize values/columns for stable comparisons."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].astype(str).map(lambda x: x.strip() if isinstance(x, str) else x)
        df.loc[df[c].str.lower() == "nan", c] = ""
    # stable col order
    df = df.reindex(sorted(df.columns), axis=1)
    return df


def choose_key_columns(df: pd.DataFrame, file_kind: str) -> List[str]:
    cols = list(df.columns)

    if file_kind == "org_info":
        for c in ["gc_orgID", "gc_orgId", "GCOrgID", "id", "ID"]:
            if c in cols:
                return [c]

    if file_kind == "concordance":
        candidates = [
            ["gc_orgID", "source", "source_orgID"],
            ["gc_orgID", "Source", "source_orgID"],
            ["gc_orgID", "dataset", "source_orgID"],
            ["gc_orgID", "source_orgID"],
            ["gc_orgID", "source_id"],
            ["gc_orgID"],
        ]
        for key_cols in candidates:
            if all(k in cols for k in key_cols) and not df.duplicated(subset=key_cols).any():
                return key_cols
        if "gc_orgID" in cols:
            return ["gc_orgID"]

    return []


def add_row_hash_key(df: pd.DataFrame) -> pd.DataFrame:
    """Fallback unique key based on full row JSON."""
    df = df.copy()
    row_json = df.apply(lambda r: json.dumps(r.to_dict(), ensure_ascii=False, sort_keys=True), axis=1)
    df["_row_hash_key"] = pd.util.hash_pandas_object(row_json, index=False).astype(str)
    return df


def compute_events(
    parent_df: pd.DataFrame,
    curr_df: pd.DataFrame,
    file_path: str,
    file_kind: str,
    commit_hash: str,
    commit_date: str
) -> pd.DataFrame:
    parent_df = normalize_df(parent_df)
    curr_df = normalize_df(curr_df)

    key_cols = choose_key_columns(curr_df, file_kind)
    use_row_hash = (not key_cols) or curr_df.duplicated(subset=key_cols).any() or parent_df.duplicated(subset=key_cols).any()

    if use_row_hash:
        parent_df = add_row_hash_key(parent_df)
        curr_df = add_row_hash_key(curr_df)
        key_cols = ["_row_hash_key"]

    parent_idx = parent_df.set_index(key_cols, drop=False)
    curr_idx = curr_df.set_index(key_cols, drop=False)

    parent_keys = set(parent_idx.index)
    curr_keys = set(curr_idx.index)

    removed_keys = parent_keys - curr_keys
    added_keys = curr_keys - parent_keys
    common_keys = parent_keys & curr_keys

    def row_to_json(row: pd.Series) -> str:
        return json.dumps(row.to_dict(), ensure_ascii=False, sort_keys=True)

    def key_to_str(row: pd.Series) -> str:
        return "|".join([str(row[c]) for c in key_cols])

    events = []

    # Removed
    for k in removed_keys:
        row = parent_idx.loc[k]
        if isinstance(row, pd.DataFrame):
            for _, r in row.iterrows():
                events.append({
                    "file": file_path,
                    "file_kind": file_kind,
                    "commit_hash": commit_hash,
                    "commit_date": commit_date,
                    "change_type": "removed",
                    "key": key_to_str(r),
                    "gc_orgID": r.get("gc_orgID", ""),
                    "row_before_json": row_to_json(r),
                    "row_after_json": ""
                })
        else:
            events.append({
                "file": file_path,
                "file_kind": file_kind,
                "commit_hash": commit_hash,
                "commit_date": commit_date,
                "change_type": "removed",
                "key": key_to_str(row),
                "gc_orgID": row.get("gc_orgID", ""),
                "row_before_json": row_to_json(row),
                "row_after_json": ""
            })

    # Added
    for k in added_keys:
        row = curr_idx.loc[k]
        if isinstance(row, pd.DataFrame):
            for _, r in row.iterrows():
                events.append({
                    "file": file_path,
                    "file_kind": file_kind,
                    "commit_hash": commit_hash,
                    "commit_date": commit_date,
                    "change_type": "added",
                    "key": key_to_str(r),
                    "gc_orgID": r.get("gc_orgID", ""),
                    "row_before_json": "",
                    "row_after_json": row_to_json(r)
                })
        else:
            events.append({
                "file": file_path,
                "file_kind": file_kind,
                "commit_hash": commit_hash,
                "commit_date": commit_date,
                "change_type": "added",
                "key": key_to_str(row),
                "gc_orgID": row.get("gc_orgID", ""),
                "row_before_json": "",
                "row_after_json": row_to_json(row)
            })

    # Modified
    for k in common_keys:
        p = parent_idx.loc[k]
        c = curr_idx.loc[k]
        if isinstance(p, pd.DataFrame) or isinstance(c, pd.DataFrame):
            # if duplicates under key, row-hash mode should have been used;
            # but if we still get here, skip "modified" detection.
            continue
        pj = row_to_json(p)
        cj = row_to_json(c)
        if pj != cj:
            events.append({
                "file": file_path,
                "file_kind": file_kind,
                "commit_hash": commit_hash,
                "commit_date": commit_date,
                "change_type": "modified",
                "key": key_to_str(c),
                "gc_orgID": c.get("gc_orgID", "") or p.get("gc_orgID", ""),
                "row_before_json": pj,
                "row_after_json": cj
            })

    cols = [
        "file", "file_kind", "commit_hash", "commit_date", "change_type",
        "key", "gc_orgID", "row_before_json", "row_after_json"
    ]
    return pd.DataFrame(events, columns=cols)


# ------------------ dedupe commits per day ------------------
def keep_last_commit_per_utc_day(commits: List[str]) -> List[str]:
    """
    Given commits newest->oldest, return commits (chronological order)
    keeping only the last commit in each UTC day (i.e., newest commit for that UTC date).
    """
    by_day: Dict[str, Tuple[datetime, str]] = {}
    for sha in commits:
        cd = git_commit_date(sha)
        dt = parse_commit_dt(cd)
        if not dt:
            continue
        day = utc_day_key(dt)
        # keep the most recent commit in that day (largest dt)
        if day not in by_day or dt > by_day[day][0]:
            by_day[day] = (dt, sha)

    # return in chronological order
    kept = sorted(by_day.values(), key=lambda t: t[0])  # oldest->newest
    return [sha for _, sha in kept]


def build_events_for_file(file_path: str, file_kind: str, skipped: List[Dict[str, str]]) -> pd.DataFrame:
    commits_newest = list_commits_touching(file_path)
    # Dedupe commits to keep only last commit per UTC day
    commits = keep_last_commit_per_utc_day(commits_newest)

    all_events = []
    for sha in commits:
        parent = first_parent(sha)
        if not parent:
            continue

        commit_date = git_commit_date(sha)

        curr_text = git_show(sha, file_path)
        parent_text = git_show(parent, file_path)

        if curr_text is None or parent_text is None:
            skipped.append({
                "file_kind": file_kind,
                "file": file_path,
                "commit_hash": sha,
                "commit_date": commit_date,
                "reason": "missing_file_at_commit_or_parent"
            })
            continue

        try:
            curr_df = read_csv_text(curr_text)
            parent_df = read_csv_text(parent_text)
        except Exception as e:
            skipped.append({
                "file_kind": file_kind,
                "file": file_path,
                "commit_hash": sha,
                "commit_date": commit_date,
                "reason": f"parse_error: {type(e).__name__}"
            })
            continue

        # Duplicate column protection (your patch-day issue)
        if has_duplicate_columns(curr_df) or has_duplicate_columns(parent_df):
            skipped.append({
                "file_kind": file_kind,
                "file": file_path,
                "commit_hash": sha,
                "commit_date": commit_date,
                "reason": "duplicate_columns"
            })
            continue

        ev = compute_events(parent_df, curr_df, file_path, file_kind, sha, commit_date)
        if not ev.empty:
            all_events.append(ev)

    if not all_events:
        return pd.DataFrame(columns=[
            "file", "file_kind", "commit_hash", "commit_date", "change_type",
            "key", "gc_orgID", "row_before_json", "row_after_json"
        ])

    return pd.concat(all_events, ignore_index=True)


def main():
    os.makedirs(ARCHIVES_DIR, exist_ok=True)

    skipped: List[Dict[str, str]] = []

    concord_events = build_events_for_file(CONCORD_PATH, "concordance", skipped)
    orginfo_events = build_events_for_file(ORGINFO_PATH, "org_info", skipped)

    concord_events.to_csv(OUT_CONCORD, index=False, encoding="utf-8-sig")
    orginfo_events.to_csv(OUT_ORGINFO, index=False, encoding="utf-8-sig")

    skipped_df = pd.DataFrame(skipped, columns=["file_kind", "file", "commit_hash", "commit_date", "reason"])
    skipped_df.to_csv(OUT_SKIPPED, index=False, encoding="utf-8-sig")

    print("Archive generation complete.")
    print(f"- {OUT_CONCORD} ({len(concord_events)} events)")
    print(f"- {OUT_ORGINFO} ({len(orginfo_events)} events)")
    print(f"- {OUT_SKIPPED} ({len(skipped_df)} skipped snapshots)")


if __name__ == "__main__":
    main()