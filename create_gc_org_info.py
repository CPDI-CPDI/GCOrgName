# -*- coding: utf-8 -*-
"""
GC Org Info builder.

Purpose:
- Build gc_org_info.csv from the governed GCOrgName manual spine plus linked sources.
- Keep exactly one output row per valid gc_orgID.
- Populate InfoBase-derived fields by ID, not by brittle legal-title matching:
    gc_orgID -> gc_concordance.infobaseID -> Resources/Infobase/infobase_en.csv.org_id
- Do not default missing InfoBase status to "a"; blank means no confirmed InfoBase linkage.
"""

import os
import re
import unicodedata
from typing import Optional

import pandas as pd

def org_name_key(value: str) -> str:
    """
    Normalize organization names for source matching.

    Handles:
    - curly vs straight apostrophes
    - punctuation
    - common filler words
    - suffix differences like 'of Canada'
    """
    s = "" if value is None else str(value)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    stopwords = {
        "the",
        "of",
        "du",
        "de",
        "des",
        "la",
        "le",
        "les",
        "canada",
    }

    tokens = [t for t in s.split() if t not in stopwords]
    return " ".join(sorted(tokens))

def _norm(s: str) -> str:
    """Normalize header/label for tolerant matching."""
    if s is None:
        return ""
    s = str(s).replace("\ufeff", "")
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    """Find a column in df matching any candidate label."""
    if df is None or df.empty:
        return None

    lookup = {}
    for c in df.columns:
        key = _norm(c).replace("_", " ")
        lookup[key] = c

    for cand in candidates:
        key = _norm(cand).replace("_", " ")
        if key in lookup:
            return lookup[key]

    return None


def standardize_text(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize text values without changing headers."""
    df = df.copy()

    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = (
                df[col]
                .astype("string")
                .fillna("")
                .str.replace("’", "'", regex=False)
                .str.replace("‘", "'", regex=False)
                .str.replace("`", "'", regex=False)
                .str.replace("\u2011", "-", regex=False)
                .str.replace("\u00a0", " ", regex=False)
                .str.strip()
            )
            df.loc[df[col].str.lower().isin(["nan", "none", "<na>"]), col] = ""

    return df


def clean_id_series(series: pd.Series) -> pd.Series:
    """Clean ID-like series safely as strings without manufacturing IDs."""
    return (
        series
        .astype("string")
        .fillna("")
        .str.strip()
        .str.split(".").str[0]
        .replace({"nan": "", "None": "", "<NA>": "", "none": ""})
    )


def merge_drop_right_key(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_on: str,
    right_on: str,
    select_cols=None,
    how: str = "left",
) -> pd.DataFrame:
    """Merge and then drop the right-hand join key column."""
    r = right
    if select_cols is not None:
        r = right[select_cols].drop_duplicates()

    out = left.merge(r, left_on=left_on, right_on=right_on, how=how)

    if right_on in out.columns:
        out = out.drop(columns=[right_on])

    return out


def coalesce_into(df: pd.DataFrame, target: str, candidates: list[str]) -> pd.DataFrame:
    """Build/overwrite df[target] with the first non-blank value across candidate columns."""
    df = df.copy()
    present = [c for c in candidates if c in df.columns]

    if target not in df.columns:
        df[target] = ""

    if not present:
        return df

    base = df[target].astype("string").fillna("")

    for c in present:
        candidate = df[c].astype("string").fillna("")
        base = base.where(base.str.strip() != "", candidate)

    df[target] = base

    for c in present:
        if c != target and c in df.columns:
            df = df.drop(columns=[c])

    return df


def load_dataframes(script_folder: str) -> dict[str, pd.DataFrame]:
    """Load required CSV files into dataframes."""
    files = {
        "manual_org": "Resources/Manual org ID link.csv",
        "combined_faa": "Scraping/combined_FAA_names.csv",
        "applied_en": "Resources/applied_en.csv",
        "infobase_en": "Resources/Infobase/infobase_en.csv",
        "infobase_fr": "Resources/Infobase/infobase_fr.csv",
        "concordance": "gc_concordance.csv",
        "harmonized_names": "Resources/create_harmonized_name.csv",
        "manual_lead_department": "Resources/lead_manual.csv",
    }

    dfs = {}

    for key, rel_path in files.items():
        path = os.path.join(script_folder, rel_path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing required input for {key}: {path}")

        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        df = standardize_text(df)

        if "Unnamed: 0" in df.columns:
            df = df.drop(columns=["Unnamed: 0"])

        dfs[key] = df

    return dfs


def apply_infobase_fields_by_id(final_df: pd.DataFrame, dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Populate InfoBase-derived fields by gc_orgID -> concordance.infobaseID -> infobase_en.org_id."""
    out = final_df.copy()

    if "concordance" not in dfs or "infobase_en" not in dfs:
        return out

    concordance = dfs["concordance"].copy()
    infobase_en = dfs["infobase_en"].copy()

    if concordance.empty or infobase_en.empty:
        return out

    conc_gc = find_col(concordance, ["gc_orgID", "gc orgid", "gc_orgid"])
    conc_ib = find_col(concordance, ["infobaseID", "infobase id", "org_id", "OrgID"])
    ibe_id = find_col(infobase_en, ["org_id", "OrgID", "org id"])
    ibe_status = find_col(infobase_en, ["status", "Status", "statut", "status_statut"])
    ibe_end = find_col(
        infobase_en,
        ["end_fin", "End_fin", "END_FIN", "end_date", "End date", "End Date"],
    )

    if not conc_gc or not conc_ib or not ibe_id:
        return out

    conc_map = concordance[[conc_gc, conc_ib]].copy()
    conc_map = conc_map.rename(columns={conc_gc: "gc_orgID", conc_ib: "infobaseID"})
    conc_map["gc_orgID"] = clean_id_series(conc_map["gc_orgID"])
    conc_map["infobaseID"] = clean_id_series(conc_map["infobaseID"])
    conc_map = conc_map[
        (conc_map["gc_orgID"] != "")
        & (conc_map["infobaseID"] != "")
        & (conc_map["infobaseID"] != "0")
    ].drop_duplicates(subset=["gc_orgID"], keep="last")

    ibe_cols = [ibe_id]
    if ibe_status:
        ibe_cols.append(ibe_status)
    if ibe_end:
        ibe_cols.append(ibe_end)

    ibe_map = infobase_en[ibe_cols].copy()
    rename_map = {ibe_id: "infobaseID"}
    if ibe_status:
        rename_map[ibe_status] = "status_statut_ib"
    if ibe_end:
        rename_map[ibe_end] = "end_date_fin_ib"

    ibe_map = ibe_map.rename(columns=rename_map)
    ibe_map["infobaseID"] = clean_id_series(ibe_map["infobaseID"])
    ibe_map = ibe_map.drop_duplicates(subset=["infobaseID"], keep="last")

    if "gc_orgID" not in out.columns:
        return out

    out["gc_orgID"] = clean_id_series(out["gc_orgID"])
    out = out.merge(conc_map, on="gc_orgID", how="left")
    out = out.merge(ibe_map, on="infobaseID", how="left")

    if "status_statut" not in out.columns:
        out["status_statut"] = ""
    if "end_date_fin" not in out.columns:
        out["end_date_fin"] = ""

    if "status_statut_ib" in out.columns:
        out["status_statut"] = out["status_statut_ib"].astype("string").fillna("").str.strip()
    if "end_date_fin_ib" in out.columns:
        out["end_date_fin"] = out["end_date_fin_ib"].astype("string").fillna("").str.strip()

    out = out.drop(
        columns=[c for c in ["infobaseID", "status_statut_ib", "end_date_fin_ib"] if c in out.columns]
    )

    return out


def apply_manual_changes(df: pd.DataFrame) -> pd.DataFrame:
    """Apply preserved manual changes to specific entries."""
    df = df.copy()

    manual_changes = {
        "2296": {"abbreviation": "LDC", "abreviation": "LDC"},
        "2281": {"abbreviation": "OIC", "abreviation": "CI"},
        "2282": {"abbreviation": "OPC", "abreviation": "CPVP"},
        "2287": {"abbreviation": "SCC", "abreviation": "CSC"},
    }

    if "gc_orgID" not in df.columns:
        print("apply_manual_changes: 'gc_orgID' not found; skipping manual changes")
        return df

    df["gc_orgID"] = clean_id_series(df["gc_orgID"])

    for gc_orgid, changes in manual_changes.items():
        for field, value in changes.items():
            if field not in df.columns:
                df[field] = ""
            df.loc[df["gc_orgID"] == gc_orgid, field] = value

    return df


def reattach_known_spillover_rows(final_df: pd.DataFrame) -> pd.DataFrame:
    """Assign known blank-ID spillover rows to existing gc_orgID values before dedupe."""
    final_df = final_df.copy()

    if "gc_orgID" not in final_df.columns or "legal_title" not in final_df.columns:
        return final_df

    def name_key(value: str) -> str:
        s = "" if value is None else str(value).strip()
        s = s.replace("’", "'").replace("`", "'")
        s = re.sub(r"\s+", " ", s)
        return s.lower()

    final_df["gc_orgID"] = clean_id_series(final_df["gc_orgID"])

    lookup = {}
    mapped_rows = final_df[final_df["gc_orgID"].astype("string").fillna("").str.strip() != ""]

    for _, row in mapped_rows.iterrows():
        k = name_key(row.get("legal_title", ""))
        if k:
            lookup.setdefault(k, str(row.get("gc_orgID", "")).strip())

    blank_mask = final_df["gc_orgID"].astype("string").fillna("").str.strip() == ""

    for i, row in final_df[blank_mask].iterrows():
        k = name_key(row.get("legal_title", ""))

        if k in lookup:
            final_df.at[i, "gc_orgID"] = lookup[k]

        if not str(final_df.at[i, "gc_orgID"]).strip():
            if "leaders" in k and "debate" in k:
                final_df.at[i, "gc_orgID"] = "2296"
            elif "information commissioner" in k:
                final_df.at[i, "gc_orgID"] = "2281"
            elif "veterans" in k and "land act" in k:
                final_df.at[i, "gc_orgID"] = "3423"

    return final_df


def enforce_valid_gc_orgids(final_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return valid rows and invalid rows based on gc_orgID."""
    tmp = final_df.copy()
    tmp = tmp.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all")

    if "gc_orgID" not in tmp.columns:
        raise ValueError("gc_org_info output is missing required column: gc_orgID")

    gc = clean_id_series(tmp["gc_orgID"])
    gc_is_numeric = gc.astype("string").fillna("").str.match(r"^[0-9]+$").fillna(False)

    invalid_mask = (gc == "") | (gc == "0") | (~gc_is_numeric)
    invalid = tmp[invalid_mask].copy()

    valid_mask = gc_is_numeric & (gc != "") & (gc != "0")
    valid = tmp[valid_mask].copy()
    valid["gc_orgID"] = gc[valid_mask]

    if valid["gc_orgID"].astype("string").fillna("").str.strip().eq("").any():
        raise ValueError("Blank gc_orgID rows still present after filtering.")

    return valid, invalid


def final_one_row_per_gc_orgid(final_df: pd.DataFrame) -> pd.DataFrame:
    """
    Enforce one row per gc_orgID by coalescing duplicate rows.

    This is better than simply keeping the most complete row because some
    source-only rows may carry important fields like FAA_LGFP while the
    manual row carries legal title, lead department, and status.
    """
    final_df = final_df.copy()

    def clean_value(value) -> str:
        if pd.isna(value):
            return ""
        s = str(value).strip()
        if s.lower() in {"", "nan", "none", "<na>"}:
            return ""
        return s

    def coalesce_group(group: pd.DataFrame) -> pd.Series:
        result = {}

        for col in group.columns:
            if col == "gc_orgID":
                result[col] = clean_value(group[col].iloc[0])
                continue

            values = [clean_value(v) for v in group[col].tolist()]
            nonblank = [v for v in values if v]

            result[col] = nonblank[0] if nonblank else ""

        return pd.Series(result)

    final_df["gc_orgID"] = clean_id_series(final_df["gc_orgID"])

    collapsed = (
        final_df
        .groupby("gc_orgID", as_index=False, sort=False)
        .apply(coalesce_group, include_groups=False)
        .reset_index(drop=True)
    )

    # groupby/apply with include_groups=False may drop gc_orgID depending on pandas version,
    # so restore defensively if needed.
    if "gc_orgID" not in collapsed.columns:
        collapsed["gc_orgID"] = final_df["gc_orgID"].drop_duplicates().tolist()

    collapsed["_sort_gc"] = pd.to_numeric(collapsed["gc_orgID"], errors="coerce")
    collapsed = collapsed.sort_values(
        by=["_sort_gc", "gc_orgID"],
        kind="mergesort"
    ).drop(columns=["_sort_gc"])

    return collapsed

def main() -> None:
    """Create gc_org_info.csv."""
    script_folder = os.path.dirname(os.path.abspath(__file__))
    dfs = load_dataframes(script_folder)

    manual = dfs["manual_org"]
    man_gc = find_col(manual, ["gc_orgID", "gc orgid", "gc_orgid"])
    man_en = find_col(manual, ["Organization Legal Name English", "Legal title", "legal_title", "English Name"])
    man_fr = find_col(
        manual,
        ["Organization Legal Name French", "Appellation légale", "appellation_legale", "Appellation legale"],
    )
    man_lead_en = find_col(manual, ["lead_department", "lead department", "Lead Department", "Lead_Department"])
    man_lead_fr = find_col(
        manual,
        ["ministère_responsable", "ministere_responsable", "ministère responsable", "Ministère Responsable", "Ministere_Responsable"],
    )

    if not man_gc or not man_en:
        raise KeyError(
            "manual_org is missing required columns. "
            f"Found gc={man_gc}, en={man_en}. Available: {list(manual.columns)}"
        )

    faa = dfs["combined_faa"].copy()
    faa_en = find_col(faa, ["Organization Legal Name English", "English Name"])
    if not faa_en:
        raise KeyError(f"combined_faa missing English name column. Have: {list(faa.columns)}")

    if faa_en != "Organization Legal Name English":
        if "Original English Name" not in faa.columns:
            faa["Original English Name"] = faa[faa_en]
        faa = faa.rename(columns={faa_en: "Organization Legal Name English"})

    faa_sched = find_col(faa, ["FAA_LGFP", "FAA LGFP", "FAA", "LGFP", "Schedule", "FAA Schedule", "LGFP / FAA", "FAA (LGFP)"])
    if faa_sched and faa_sched != "FAA_LGFP":
        faa = faa.rename(columns={faa_sched: "FAA_LGFP"})

    applied = dfs["applied_en"]
    app_key = find_col(applied, ["Legal title", "legal_title", "Legal Title", "Organization Legal Name English", "English Name", "Legal name"])
    app_applied = find_col(applied, ["Applied title", "applied_title", "Applied Title"])
    app_titre = find_col(applied, ["Titre d'usage", "titre d'usage", "titre_usage"])
    app_abbr_en = find_col(applied, ["Abbreviation", "abbreviation"])
    app_abbr_fr = find_col(applied, ["Abreviation", "abreviation"])

    harmonized = dfs["harmonized_names"]
    har_gc = find_col(harmonized, ["gc_orgID", "gc orgid", "gc_orgid"])
    har_en = find_col(harmonized, ["harmonized_name", "harmonized name"])
    har_fr = find_col(harmonized, ["nom_harmonisé", "nom harmonisé", "Nom harmonisé", "Nom_harmonisé", "nom_harmonise"])

    lead = dfs["manual_lead_department"]
    lead_gc = find_col(lead, ["gc_orgID", "gc orgid", "gc_orgid"])
    lead_en = find_col(lead, ["lead_department", "lead department", "Lead Department", "Lead_Department"])
    lead_fr = find_col(
        lead,
        ["ministère_responsable", "ministere_responsable", "ministère responsable", "Ministère Responsable", "Ministere_Responsable"],
    )

    manual2 = manual.copy()
    manual2 = manual2.rename(columns={man_gc: "gc_orgID", man_en: "Organization Legal Name English"})
    if man_fr:
        manual2 = manual2.rename(columns={man_fr: "Organization Legal Name French"})
    if man_lead_en:
        manual2 = manual2.rename(columns={man_lead_en: "lead_department"})
    if man_lead_fr:
        manual2 = manual2.rename(columns={man_lead_fr: "ministère_responsable"})

    manual2["gc_orgID"] = clean_id_series(manual2["gc_orgID"])

    manual2["_faa_match_key"] = manual2["Organization Legal Name English"].map(org_name_key)
    faa["_faa_match_key"] = faa["Organization Legal Name English"].map(org_name_key)

    # Avoid multiplying rows if FAA has repeated/variant names with the same normalized key.
    faa = (
        faa
        .sort_values(
            by=["_faa_match_key"],
            kind="mergesort"
        )
        .drop_duplicates(subset=["_faa_match_key"], keep="first")
    )

    joined_df = manual2.merge(
        faa.drop(columns=["Organization Legal Name English"], errors="ignore"),
        on="_faa_match_key",
        how="left",
        suffixes=("", "_faa"),
    )

    joined_df = joined_df.drop(columns=["_faa_match_key"], errors="ignore")

    if app_key:
        app_cols = [app_key]
        if app_applied:
            app_cols.append(app_applied)
        if app_titre:
            app_cols.append(app_titre)
        if app_abbr_en:
            app_cols.append(app_abbr_en)
        if app_abbr_fr:
            app_cols.append(app_abbr_fr)

        tmp = applied[app_cols].copy()
        rename_map = {app_key: "app_key"}
        if app_applied:
            rename_map[app_applied] = "preferred_name"
        if app_titre:
            rename_map[app_titre] = "nom_préféré"
        if app_abbr_en:
            rename_map[app_abbr_en] = "abbreviation"
        if app_abbr_fr:
            rename_map[app_abbr_fr] = "abreviation"

        tmp = tmp.rename(columns=rename_map).drop_duplicates(subset=["app_key"])
        joined_df = merge_drop_right_key(joined_df, tmp, left_on="Organization Legal Name English", right_on="app_key")

    if har_gc:
        cols = [har_gc]
        if har_en:
            cols.append(har_en)
        if har_fr:
            cols.append(har_fr)

        tmp = harmonized[cols].copy().rename(columns={har_gc: "gc_orgID"})
        tmp["gc_orgID"] = clean_id_series(tmp["gc_orgID"])
        if har_en:
            tmp = tmp.rename(columns={har_en: "harmonized_name"})
        if har_fr:
            tmp = tmp.rename(columns={har_fr: "nom_harmonisé"})
        tmp = tmp.drop_duplicates(subset=["gc_orgID"])
        joined_df = joined_df.merge(tmp, on="gc_orgID", how="left")

    if lead_gc:
        cols = [lead_gc]
        if lead_en:
            cols.append(lead_en)
        if lead_fr:
            cols.append(lead_fr)

        tmp = lead[cols].copy().rename(columns={lead_gc: "gc_orgID"})
        tmp["gc_orgID"] = clean_id_series(tmp["gc_orgID"])
        if lead_en:
            tmp = tmp.rename(columns={lead_en: "lead_department_lead"})
        if lead_fr:
            tmp = tmp.rename(columns={lead_fr: "ministère_responsable_lead"})
        tmp = tmp.drop_duplicates(subset=["gc_orgID"])
        joined_df = joined_df.merge(tmp, on="gc_orgID", how="left")

    final_df = joined_df.copy()

    rename_map = {}
    if "Organization Legal Name English" in final_df.columns:
        rename_map["Organization Legal Name English"] = "legal_title"
    if "Organization Legal Name French" in final_df.columns:
        rename_map["Organization Legal Name French"] = "appellation_légale"
    final_df = final_df.rename(columns=rename_map)

    if "status_statut" not in final_df.columns:
        final_df["status_statut"] = ""
    if "end_date_fin" not in final_df.columns:
        final_df["end_date_fin"] = ""

    lead_candidates = [
        "lead_department_lead",
        "lead_department",
        "Lead Department",
        "Lead_Department",
        "lead department",
    ] + [c for c in final_df.columns if c.startswith("lead_department_") and c not in ("lead_department", "lead_department_lead")]
    final_df = coalesce_into(final_df, "lead_department", lead_candidates)

    lead_fr_candidates = [
        "ministère_responsable_lead",
        "ministère_responsable",
        "ministere_responsable",
        "Ministère Responsable",
        "Ministere_Responsable",
        "ministère responsable",
    ] + [c for c in final_df.columns if c.startswith("ministère_responsable_") and c not in ("ministère_responsable", "ministère_responsable_lead")]
    final_df = coalesce_into(final_df, "ministère_responsable", lead_fr_candidates)

    final_df = coalesce_into(final_df, "legal_title", ["legal_title", "Legal title", "Legal Title"])
    final_df = coalesce_into(
        final_df,
        "appellation_légale",
        ["appellation_légale", "Appellation légale", "Appellation legale", "appellation_legale"],
    )
    final_df = coalesce_into(
        final_df,
        "nom_harmonisé",
        ["nom_harmonisé", "nom harmonisé", "Nom harmonisé", "Nom_harmonisé", "nom_harmonise"],
    )

    final_df = apply_infobase_fields_by_id(final_df, dfs)

    target_cols = [
        "gc_orgID",
        "harmonized_name",
        "nom_harmonisé",
        "legal_title",
        "appellation_légale",
        "preferred_name",
        "nom_préféré",
        "lead_department",
        "ministère_responsable",
        "abbreviation",
        "abreviation",
        "FAA_LGFP",
        "status_statut",
        "end_date_fin",
    ]

    for c in target_cols:
        if c not in final_df.columns:
            final_df[c] = ""

    final_df = final_df[target_cols]
    final_df["gc_orgID"] = clean_id_series(final_df["gc_orgID"])

    final_df = reattach_known_spillover_rows(final_df)
    valid_df, invalid_df = enforce_valid_gc_orgids(final_df)

    if not invalid_df.empty:
        invalid_df.to_csv("org_info_unmapped_rows.csv", index=False, encoding="utf-8-sig")

    valid_df = apply_manual_changes(valid_df)
    valid_df = final_one_row_per_gc_orgid(valid_df)

    dupes = valid_df[valid_df["gc_orgID"].duplicated(keep=False)]
    if not dupes.empty:
        sample = dupes[["gc_orgID", "legal_title"]].head(20)
        raise ValueError(
            "Duplicate gc_orgID rows remain after final dedupe. "
            f"Sample:\n{sample.to_string(index=False)}"
        )

    valid_df.to_csv("gc_org_info.csv", index=False, encoding="utf-8-sig")

    documentation = {
        "gc_orgID": "Source: Resources/create_harmonized_name.csv / Manual org spine",
        "harmonized_name": "Source: Resources/create_harmonized_name.csv",
        "nom_harmonisé": "Source: Resources/create_harmonized_name.csv",
        "legal_title": "Source: Resources/Manual org ID link.csv + Scraping/combined_FAA_names.csv",
        "appellation_légale": "Source: Resources/Manual org ID link.csv",
        "preferred_name": "Source: Resources/applied_en.csv",
        "nom_préféré": "Source: Resources/applied_en.csv",
        "lead_department": "Source: Resources/lead_manual.csv priority, then Manual org",
        "ministère_responsable": "Source: Resources/lead_manual.csv priority, then Manual org",
        "abbreviation": "Source: Resources/applied_en.csv + manual overrides",
        "abreviation": "Source: Resources/applied_en.csv + manual overrides",
        "FAA_LGFP": "Source: Scraping/combined_FAA_names.csv",
        "status_statut": "Source: Resources/Infobase/infobase_en.csv via gc_concordance.infobaseID",
        "end_date_fin": "Source: Resources/Infobase/infobase_en.csv via gc_concordance.infobaseID",
    }

    with open(os.path.join(script_folder, "gc_org_info_documentation.txt"), "w", encoding="utf-8") as f:
        for field, doc in documentation.items():
            f.write(f"{field}: {doc}\n")

    print(f"gc_org_info.csv written with {len(valid_df)} rows")
    print(f"org_info_unmapped_rows.csv written with {len(invalid_df)} rows")


if __name__ == "__main__":
    main()
