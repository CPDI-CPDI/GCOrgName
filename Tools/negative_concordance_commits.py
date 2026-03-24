import subprocess
import pandas as pd
import json
import os
from datetime import datetime
from typing import List, Optional, Tuple

ARCHIVES_DIR = "Archives"

CONCORD_PATH = "gc_concordance.csv"
ORGINFO_PATH = "gc_org_info.csv"

# Output files (same names as today, but cleaner contents)
CONCORD_BY_DATE = os.path.join(ARCHIVES_DIR, "concordance_archive_by_date.csv")
CONCORD_BY_ID = os.path.join(ARCHIVES_DIR, "concordance_archive_by_ID.csv")
ORGINFO_BY_DATE = os.path.join(ARCHIVES_DIR, "org_info_archive_by_date.csv")
ORGINFO_BY_ID = os.path.join(ARCHIVES_DIR, "org_info_archive_by_ID.csv")

# Canonical event log (new, but very useful)
EVENT_LOG = os.path.join(ARCHIVES_DIR, "archive_events.csv")


def run_git(args: List[str]) -> str:
    out = subprocess.check_output(["git"] + args)
    return out.decode("utf-8", errors="replace")


def git_show(commit: str, path: str) -> Optional[str]:
    try:
        return run_git(["show", f"{commit}:{path}"])
    except subprocess.CalledProcessError:
        return None


def git_commit_date(commit: str) -> str:
    # Example: 2026-03-23 15:10:00 -0400
    return run_git(["show", "-s", "--format=%ci", commit]).strip()


def list_commits_touching(path: str) -> List[str]:
    try:
        out = run_git(["log", "--format=%H", "--", path]).strip()
        return out.splitlines() if out else []
    except subprocess.CalledProcessError:
        return []


def first_parent(commit: str) -> Optional[str]:
    try:
        parts = run_git(["rev-list", "--parents", "-n", "1", commit]).strip().split()
        return parts[1] if len(parts) > 1 else None
    except subprocess.CalledProcessError:
        return None


def read_csv_text(csv_text: str) -> pd.DataFrame:
    from io import StringIO
    return pd.read_csv(StringIO(csv_text), dtype=str, keep_default_na=False, encoding_errors="replace")


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].astype(str).map(lambda x: x.strip() if isinstance(x, str) else x)
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
            if all(k in cols for k in key_cols):
                if not df.duplicated(subset=key_cols).any():
                    return key_cols
        if "gc_orgID" in cols:
            return ["gc_orgID"]

    return []


def add_row_hash_key(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    row_json = df.apply(lambda r: json.dumps(r.to_dict(), ensure_ascii=False, sort_keys=True), axis=1)
    df["_row_hash_key"] = pd.util.hash_pandas_object(row_json, index=False).astype(str)
    return df


def compute_events(parent_df: pd.DataFrame, curr_df: pd.DataFrame, file_path: str, file_kind: str, commit: str) -> pd.DataFrame:
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

    events = []
    commit_date = git_commit_date(commit)

    def row_to_json(row: pd.Series) -> str:
        return json.dumps(row.to_dict(), ensure_ascii=False, sort_keys=True)

    def key_to_str(row: pd.Series) -> str:
        return "|".join([str(row[c]) for c in key_cols])

    # Removed
    for k in removed_keys:
        row = parent_idx.loc[k]
        if isinstance(row, pd.DataFrame):
            for _, r in row.iterrows():
                events.append({
                    "file": file_path,
                    "file_kind": file_kind,
                    "commit_hash": commit,
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
                "commit_hash": commit,
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
                    "commit_hash": commit,
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
                "commit_hash": commit,
                "commit_date": commit_date,
                "change_type": "added",
                "key": key_to_str(row),
                "gc_orgID": row.get("gc_orgID", ""),
                "row_before_json": "",
                "row_after_json": row_to_json(row)
            })

    # Modified (same key, different row)
    for k in common_keys:
        p = parent_idx.loc[k]
        c = curr_idx.loc[k]
        if isinstance(p, pd.DataFrame) or isinstance(c, pd.DataFrame):
            continue
        pj = row_to_json(p)
        cj = row_to_json(c)
        if pj != cj:
            events.append({
                "file": file_path,
                "file_kind": file_kind,
                "commit_hash": commit,
                "commit_date": commit_date,
                "change_type": "modified",
                "key": key_to_str(c),
                "gc_orgID": c.get("gc_orgID", "") or p.get("gc_orgID", ""),
                "row_before_json": pj,
                "row_after_json": cj
            })

    cols = ["file","file_kind","commit_hash","commit_date","change_type","key","gc_orgID","row_before_json","row_after_json"]
    return pd.DataFrame(events, columns=cols)


def build_archive_for_file(file_path: str, file_kind: str) -> pd.DataFrame:
    commits = list_commits_touching(file_path)
    commits = list(reversed(commits))  # chronological

    all_events = []
    for commit in commits:
        parent = first_parent(commit)
        if not parent:
            continue
        curr_text = git_show(commit, file_path)
        parent_text = git_show(parent, file_path)
        if curr_text is None or parent_text is None:
            continue
        try:
            curr_df = read_csv_text(curr_text)
            parent_df = read_csv_text(parent_text)
        except Exception:
            continue
        events = compute_events(parent_df, curr_df, file_path, file_kind, commit)
        if not events.empty:
            all_events.append(events)

    if not all_events:
        return pd.DataFrame(columns=["file","file_kind","commit_hash","commit_date","change_type","key","gc_orgID","row_before_json","row_after_json"])

    return pd.concat(all_events, ignore_index=True)


def write_views(events_df: pd.DataFrame, by_date_path: str, by_id_path: str):
    if events_df.empty:
        events_df.to_csv(by_date_path, index=False, encoding="utf-8-sig")
        events_df.to_csv(by_id_path, index=False, encoding="utf-8-sig")
        return

    def parse_dt(s: str) -> Tuple[int, str]:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
            return (0, dt.isoformat())
        except Exception:
            return (1, s)

    tmp = events_df.copy()
    tmp["_dt_sort_key"] = tmp["commit_date"].map(parse_dt)
    by_date = tmp.sort_values(by="_dt_sort_key", ascending=False).drop(columns=["_dt_sort_key"])

    tmp2 = events_df.copy()
    tmp2["_dt_sort_key"] = tmp2["commit_date"].map(parse_dt)
    by_id = tmp2.sort_values(by=["gc_orgID", "_dt_sort_key"], ascending=[True, False]).drop(columns=["_dt_sort_key"])

    by_date.to_csv(by_date_path, index=False, encoding="utf-8-sig")
    by_id.to_csv(by_id_path, index=False, encoding="utf-8-sig")


def main():
    os.makedirs(ARCHIVES_DIR, exist_ok=True)

    concord_events = build_archive_for_file(CONCORD_PATH, "concordance")
    orginfo_events = build_archive_for_file(ORGINFO_PATH, "org_info")

    all_events = pd.concat([concord_events, orginfo_events], ignore_index=True)
    all_events.to_csv(EVENT_LOG, index=False, encoding="utf-8-sig")

    write_views(concord_events, CONCORD_BY_DATE, CONCORD_BY_ID)
    write_views(orginfo_events, ORGINFO_BY_DATE, ORGINFO_BY_ID)

    print("Archive generation complete.")
    print(f"- {EVENT_LOG}")
    print(f"- {CONCORD_BY_DATE}")
    print(f"- {CONCORD_BY_ID}")
    print(f"- {ORGINFO_BY_DATE}")
    print(f"- {ORGINFO_BY_ID}")


if __name__ == "__main__":
    main()