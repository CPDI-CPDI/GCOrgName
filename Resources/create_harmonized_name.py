# -*- coding: utf-8 -*-
"""
Create harmonized English/French organization names.

Inputs:
- Resources/Manual org ID link.csv
- Resources/applied_en.csv
- Resources/Infobase/infobase_en.csv
- Resources/Infobase/infobase_fr.csv

Output:
- Resources/create_harmonized_name.csv

Purpose:
- Use Applied Titles where available.
- Fall back to Manual org legal titles.
- Keep gc_orgID stable and clean.
"""

import os
import re
import unicodedata
from typing import Optional, List

import pandas as pd


# --------------------
# Helpers
# --------------------

def _norm(s: str) -> str:
    """Normalize headers/labels for tolerant matching."""
    if s is None:
        return ""
    s = str(s).replace("\ufeff", "")
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """Find a dataframe column using normalized case/spacing/underscore-insensitive matching."""
    if df is None or df.empty:
        return None

    lookup = {}
    for col in df.columns:
        lookup[_norm(col).replace("_", " ")] = col

    for candidate in candidates:
        key = _norm(candidate).replace("_", " ")
        if key in lookup:
            return lookup[key]

    return None


def read_csv(path: str) -> pd.DataFrame:
    """Read CSV robustly as strings."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing required file: {path}")

    return pd.read_csv(
        path,
        encoding="utf-8-sig",
        dtype=str,
        keep_default_na=False
    )


def standardize_text(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize text values without changing headers."""
    df = df.copy()

    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = (
                df[col]
                .astype(str)
                .str.replace("’", "'", regex=False)
                .str.replace("‘", "'", regex=False)
                .str.replace("\u2011", "-", regex=False)
                .str.replace("\u00a0", " ", regex=False)
                .str.strip()
            )
            df.loc[df[col].str.lower().isin(["nan", "none"]), col] = ""

    return df


def clean_gc_orgid(series: pd.Series) -> pd.Series:
    """Normalize gc_orgID values without manufacturing IDs."""
    return (
        series
        .fillna("")
        .astype(str)
        .str.strip()
        .str.split(".")
        .str[0]
    )


def first_non_blank(*values) -> str:
    """Return first non-blank value from values."""
    for value in values:
        value = "" if value is None else str(value).strip()
        if value and value.lower() not in {"nan", "none"}:
            return value
    return ""


# --------------------
# Main
# --------------------

def main() -> None:
    script_folder = os.path.dirname(os.path.abspath(__file__))

    manual_org_file = os.path.join(script_folder, "Manual org ID link.csv")
    applied_en_file = os.path.join(script_folder, "applied_en.csv")
    infobase_en_file = os.path.join(script_folder, "Infobase", "infobase_en.csv")
    infobase_fr_file = os.path.join(script_folder, "Infobase", "infobase_fr.csv")

    output_file = os.path.join(script_folder, "create_harmonized_name.csv")

    # ---- Load ----
    manual_org_df = standardize_text(read_csv(manual_org_file))
    applied_en_df = standardize_text(read_csv(applied_en_file))
    infobase_en_df = standardize_text(read_csv(infobase_en_file))
    infobase_fr_df = standardize_text(read_csv(infobase_fr_file))

    # ---- Resolve Manual Org columns ----
    man_gc = find_col(manual_org_df, ["gc_orgID", "gc orgid", "gc_orgid"])
    man_en = find_col(
        manual_org_df,
        ["Organization Legal Name English", "legal_title", "Legal title", "English Name"]
    )
    man_fr = find_col(
        manual_org_df,
        ["Organization Legal Name French", "appellation_légale", "Appellation légale", "Appellation legale", "French Name"]
    )

    if not man_gc or not man_en:
        raise KeyError(
            "Manual org file must contain gc_orgID and Organization Legal Name English. "
            f"Found gc={man_gc}, en={man_en}. Columns: {list(manual_org_df.columns)}"
        )

    manual = manual_org_df.copy()
    manual = manual.rename(columns={man_gc: "gc_orgID", man_en: "Organization Legal Name English"})
    if man_fr and man_fr != "Organization Legal Name French":
        manual = manual.rename(columns={man_fr: "Organization Legal Name French"})
    elif "Organization Legal Name French" not in manual.columns:
        manual["Organization Legal Name French"] = ""

    manual["gc_orgID"] = clean_gc_orgid(manual["gc_orgID"])

    # ---- Resolve Applied Titles columns ----
    app_key = find_col(
        applied_en_df,
        ["Legal title", "legal_title", "Legal Title", "Organization Legal Name English"]
    )
    app_en = find_col(
        applied_en_df,
        ["Applied title", "applied_title", "Applied Title"]
    )
    app_fr = find_col(
        applied_en_df,
        ["Titre d'usage", "titre d'usage", "titre_usage"]
    )

    applied = pd.DataFrame()
    if app_key:
        keep_cols = [app_key]
        if app_en:
            keep_cols.append(app_en)
        if app_fr:
            keep_cols.append(app_fr)

        applied = applied_en_df[keep_cols].copy()
        rename_map = {app_key: "applied_key"}
        if app_en:
            rename_map[app_en] = "Applied title"
        if app_fr:
            rename_map[app_fr] = "Titre d'usage"

        applied = applied.rename(columns=rename_map).drop_duplicates(subset=["applied_key"])
    else:
        applied = pd.DataFrame(columns=["applied_key", "Applied title", "Titre d'usage"])

    # ---- Resolve InfoBase EN columns, currently used only as optional fallback context ----
    ibe_key = find_col(
        infobase_en_df,
        ["legal_title", "Legal title", "Legal Title", "Organization Legal Name English"]
    )
    ibe_applied = find_col(
        infobase_en_df,
        ["applied_title", "Applied title", "titre_applique", "title_applied"]
    )

    ibe = pd.DataFrame()
    if ibe_key:
        keep_cols = [ibe_key]
        if ibe_applied:
            keep_cols.append(ibe_applied)

        ibe = infobase_en_df[keep_cols].copy()
        rename_map = {ibe_key: "infobase_en_key"}
        if ibe_applied:
            rename_map[ibe_applied] = "infobase_applied_title"
        ibe = ibe.rename(columns=rename_map).drop_duplicates(subset=["infobase_en_key"])
    else:
        ibe = pd.DataFrame(columns=["infobase_en_key", "infobase_applied_title"])

    # ---- Resolve InfoBase FR columns for French fallback ----
    ibf_legal = find_col(
        infobase_fr_df,
        ["appellation_legale", "Appellation legale", "Appellation légale", "legal_title", "titre_legal"]
    )
    ibf_applied = find_col(
        infobase_fr_df,
        ["titre_applique", "Titre applique", "Titre appliqué", "titre d'usage", "Titre d'usage"]
    )

    ibf = pd.DataFrame()
    if ibf_legal:
        keep_cols = [ibf_legal]
        if ibf_applied:
            keep_cols.append(ibf_applied)

        ibf = infobase_fr_df[keep_cols].copy()
        rename_map = {ibf_legal: "infobase_fr_key"}
        if ibf_applied:
            rename_map[ibf_applied] = "infobase_titre_applique"
        ibf = ibf.rename(columns=rename_map).drop_duplicates(subset=["infobase_fr_key"])
    elif ibf_applied:
        # Fallback for older behavior where French manual title was compared directly to titre_applique.
        ibf = infobase_fr_df[[ibf_applied]].copy()
        ibf = ibf.rename(columns={ibf_applied: "infobase_titre_applique"})
        ibf["infobase_fr_key"] = ibf["infobase_titre_applique"]
        ibf = ibf.drop_duplicates(subset=["infobase_fr_key"])
    else:
        ibf = pd.DataFrame(columns=["infobase_fr_key", "infobase_titre_applique"])

    # ---- Merge sources ----
    joined_df = manual.merge(
        applied,
        left_on="Organization Legal Name English",
        right_on="applied_key",
        how="left"
    )

    joined_df = joined_df.merge(
        ibe,
        left_on="Organization Legal Name English",
        right_on="infobase_en_key",
        how="left"
    )

    joined_df = joined_df.merge(
        ibf,
        left_on="Organization Legal Name French",
        right_on="infobase_fr_key",
        how="left"
    )

    # ---- Build harmonized fields ----
    joined_df["harmonized_name"] = joined_df.apply(
        lambda row: first_non_blank(
            row.get("Applied title", ""),
            row.get("infobase_applied_title", ""),
            row.get("Organization Legal Name English", "")
        ),
        axis=1
    )

    joined_df["nom_harmonisé"] = joined_df.apply(
        lambda row: first_non_blank(
            row.get("Titre d'usage", ""),
            row.get("infobase_titre_applique", ""),
            row.get("Organization Legal Name French", "")
        ),
        axis=1
    )

    # ---- Manual changes / overrides ----
    manual_changes = {
        "2271": {
            "harmonized_name": "Elections Canada",
            "nom_harmonisé": "Élections Canada"
        }
    }

    for gc_orgid, changes in manual_changes.items():
        mask = joined_df["gc_orgID"] == str(gc_orgid)
        for field, value in changes.items():
            joined_df.loc[mask, field] = value

    # ---- Clean helper columns from merges ----
    helper_cols = [
        "applied_key",
        "infobase_en_key",
        "infobase_fr_key",
        "infobase_applied_title",
        "infobase_titre_applique"
    ]
    joined_df = joined_df.drop(columns=[c for c in helper_cols if c in joined_df.columns], errors="ignore")

    # ---- Ensure key output columns exist ----
    for col in ["gc_orgID", "harmonized_name", "nom_harmonisé"]:
        if col not in joined_df.columns:
            joined_df[col] = ""

    # ---- Sort output ----
    joined_df["_sort_gc"] = pd.to_numeric(joined_df["gc_orgID"], errors="coerce")
    joined_df = joined_df.sort_values(by=["_sort_gc", "gc_orgID"]).drop(columns=["_sort_gc"])

    # ---- Save ----
    joined_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"The final joined DataFrame has been saved to {output_file}")
    print(f"Rows written: {len(joined_df)}")


if __name__ == "__main__":
    main()
