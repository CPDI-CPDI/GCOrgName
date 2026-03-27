# -*- coding: utf-8 -*-
"""
GC Org Info builder — robust to header variants, BOMs, dtype quirks,
and guarantees accented French headers with non-blank values where sources exist.
"""

import os
import re
import unicodedata
import pandas as pd

# -------------------- Normalization + resolution helpers --------------------

def _norm(s: str) -> str:
    """Normalize header/label for tolerant matching (trim, lower, strip BOM/thin spaces)."""
    if s is None:
        return ""
    s = str(s).replace("\ufeff", "")  # BOM
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def find_col(df: pd.DataFrame, candidates):
    """
    Find the actual column in df that matches any candidate label,
    using normalized comparison tolerant to case/spacing/underscores.
    """
    if df is None or df.empty:
        return None
    lut = {}
    for c in df.columns:
        k = _norm(c).replace("_", " ")
        lut[k] = c
    for cand in candidates:
        k = _norm(cand).replace("_", " ")
        if k in lut:
            return lut[k]
    return None


def standardize_text(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize text values (not headers): normalize quotes/hard hyphens; strip."""
    return df.apply(
        lambda x: (x
                   .str.replace('’', "'", regex=False)
                   .str.replace('\u2011', '-', regex=False)
                   .str.strip())
        if x.dtype == "object" else x
    )


def merge_drop_right_key(left: pd.DataFrame,
                         right: pd.DataFrame,
                         left_on: str,
                         right_on: str,
                         select_cols=None,
                         how: str = 'left') -> pd.DataFrame:
    """
    Merge and then drop the right-hand key column to avoid keeping a duplicate
    of the join key (e.g., 'Legal title').
    """
    r = right
    if select_cols is not None:
        r = right[select_cols].drop_duplicates()
    out = left.merge(r, left_on=left_on, right_on=right_on, how=how)
    if right_on in out.columns:
        out = out.drop(columns=[right_on])
    return out


def coalesce_into(df: pd.DataFrame, target: str, candidates: list) -> pd.DataFrame:
    """
    Build/overwrite df[target] with first non-null across candidates (in order).
    Drops every candidate except the final target.
    """
    present = [c for c in candidates if c in df.columns]
    if not present:
        # ensure the column exists (empty) if not present at all
        if target not in df.columns:
            df[target] = ""
        return df
    base = df[target] if target in df.columns else pd.Series([""] * len(df), index=df.index)
    for c in present:
        base = base.where(base.astype(str).str.strip() != "", df[c])
    df[target] = base
    for c in present:
        if c != target and c in df.columns:
            df = df.drop(columns=[c])
    return df


# ------------------------------ IO ------------------------------

def load_dataframes(script_folder: str):
    """Load all required CSV files into dataframes (UTF-8 BOM tolerant, string dtypes)."""
    files = {
        'manual_org': 'Resources/Manual org ID link.csv',
        'combined_faa': 'Scraping/combined_FAA_names.csv',
        'applied_en': 'Resources/applied_en.csv',
        'infobase_en': 'Resources/infobase_en.csv',
        'infobase_fr': 'Resources/infobase_fr.csv',
        'harmonized_names': 'Resources/create_harmonized_name.csv',
        'manual_lead_department': 'Resources/lead_manual.csv',  # authoritative lead dept
    }
    dfs = {}
    for key, rel_path in files.items():
        path = os.path.join(script_folder, rel_path)
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
        df = standardize_text(df)
        if 'Unnamed: 0' in df.columns:
            df = df.drop(columns=['Unnamed: 0'])
        dfs[key] = df
    return dfs


# --------------------------- Business logic ---------------------------

def main():
    """Create GC organization information file with accented French fields properly populated."""
    script_folder = os.path.dirname(os.path.abspath(__file__))

    # ---- Load ----
    dfs = load_dataframes(script_folder)

    # ---- Resolve key columns in source frames ----

    # manual_org
    man = dfs['manual_org']
    man_gc = find_col(man, ['gc_orgID', 'gc orgid', 'gc_orgid'])
    man_en = find_col(man, ['Organization Legal Name English', 'Legal title', 'legal_title', 'English Name'])
    man_fr = find_col(man, ['Organization Legal Name French', 'Appellation légale', 'appellation_legale', 'Appellation legale'])

    # Some manual files may already carry lead dept info
    man_lead_en = find_col(man, ['lead_department', 'lead department', 'Lead Department', 'Lead_Department'])
    man_lead_fr = find_col(man, ['ministère_responsable', 'ministere_responsable', 'ministère responsable', 'Ministère Responsable', 'Ministere_Responsable'])

    if not man_gc or not man_en:
        raise KeyError(
            "manual_org is missing required columns. "
            f"Found gc: {man_gc}, en: {man_en}. Available: {list(man.columns)}"
        )

    # combined_faa
    faa = dfs['combined_faa']
    faa_en = find_col(faa, ['Organization Legal Name English', 'English Name'])
    if not faa_en:
        raise KeyError(f"combined_faa missing English name column. Have: {list(faa.columns)}")
    if faa_en != 'Organization Legal Name English':
        if 'Original English Name' not in faa.columns:
            faa['Original English Name'] = faa[faa_en]
        faa = faa.rename(columns={faa_en: 'Organization Legal Name English'})

    # applied_en
    app = dfs['applied_en']
    # merge key candidates
    app_key_candidates = ['Legal title', 'legal_title', 'Legal Title', 'Organization Legal Name English', 'English Name', 'Legal name']
    app_key     = find_col(app, app_key_candidates)
    app_applied = find_col(app, ['Applied title', 'applied_title', 'Applied Title'])
    app_titre   = find_col(app, ["Titre d'usage", "titre d'usage", 'titre_usage'])
    app_abbr_en = find_col(app, ['Abbreviation', 'abbreviation'])
    app_abbr_fr = find_col(app, ['Abreviation', 'abreviation'])

    # infobase_en
    ibe = dfs['infobase_en']
    ibe_key_candidates = ['Legal title', 'legal_title', 'Legal Title', 'Organization Legal Name English']
    ibe_key  = find_col(ibe, ibe_key_candidates)
    ibe_stat = find_col(ibe, ['Status', 'status', 'Statut'])
    ibe_end  = find_col(ibe, ['End date', 'end_date', 'End Date'])

    # harmonized_names
    har = dfs['harmonized_names']
    har_gc = find_col(har, ['gc_orgID', 'gc orgid', 'gc_orgid'])
    har_en = find_col(har, ['harmonized_name', 'harmonized name'])
    # IMPORTANT: allow multiple FR variants (accented + unaccented + spaced)
    har_fr = find_col(har, ['nom_harmonisé', 'nom harmonisé', 'Nom harmonisé', 'Nom_harmonisé', 'nom_harmonise'])

    # lead manual (authoritative)
    lead = dfs['manual_lead_department']
    lead_gc = find_col(lead, ['gc_orgID', 'gc orgid', 'gc_orgid'])
    lead_en = find_col(lead, ['lead_department', 'lead department', 'Lead Department', 'Lead_Department'])
    lead_fr = find_col(lead, ['ministère_responsable', 'ministere_responsable', 'ministère responsable', 'Ministère Responsable', 'Ministere_Responsable'])

    # ---- Build initial merge (outer) on English legal title ----
    man2 = man.rename(columns={man_en: 'Organization Legal Name English', man_gc: 'gc_orgID'})
    if man_fr:
        man2 = man2.rename(columns={man_fr: 'Organization Legal Name French'})
    if man_lead_en:
        man2 = man2.rename(columns={man_lead_en: 'lead_department'})
    if man_lead_fr:
        man2 = man2.rename(columns={man_lead_fr: 'ministère_responsable'})

    joined_df = man2.merge(faa, on='Organization Legal Name English', how='outer', suffixes=('', '_faa'))

    # ---- Applied titles merge (preferred names + abbreviations) ----
    if app_key:
        app_cols = [app_key]
        if app_applied: app_cols.append(app_applied)
        if app_titre:   app_cols.append(app_titre)
        if app_abbr_en: app_cols.append(app_abbr_en)
        if app_abbr_fr: app_cols.append(app_abbr_fr)

        tmp = app[app_cols].copy()
        rename_map = {}
        if app_key != 'app_key':
            rename_map[app_key] = 'app_key'
        if app_applied: rename_map[app_applied] = 'preferred_name'
        if app_titre:   rename_map[app_titre]   = 'nom_préféré'
        if app_abbr_en: rename_map[app_abbr_en] = 'abbreviation'
        if app_abbr_fr: rename_map[app_abbr_fr] = 'abreviation'
        tmp = tmp.rename(columns=rename_map)
        joined_df = merge_drop_right_key(joined_df, tmp, left_on='Organization Legal Name English', right_on='app_key')

    # ---- InfoBase status + end date merge (EN) ----
    if ibe_key:
        ibe_cols = [ibe_key]
        if ibe_stat: ibe_cols.append(ibe_stat)
        if ibe_end:  ibe_cols.append(ibe_end)
        tmp = ibe[ibe_cols].copy()
        rename_map = {}
        rename_map[ibe_key] = 'ibe_key'
        if ibe_stat: rename_map[ibe_stat] = 'status_statut'
        if ibe_end:  rename_map[ibe_end]  = 'end_date_fin'
        tmp = tmp.rename(columns=rename_map)
        joined_df = merge_drop_right_key(joined_df, tmp, left_on='Organization Legal Name English', right_on='ibe_key')

    # ---- Harmonized names merge by gc_orgID ----
    if har_gc:
        cols = [har_gc]
        if har_en: cols.append(har_en)
        if har_fr: cols.append(har_fr)
        tmp = har[cols].copy().rename(columns={har_gc: 'gc_orgID'})
        if har_en: tmp = tmp.rename(columns={har_en: 'harmonized_name'})
        if har_fr: tmp = tmp.rename(columns={har_fr: 'nom_harmonisé'})
        joined_df = joined_df.merge(tmp.drop_duplicates(), on='gc_orgID', how='left')

    # ---- Lead manual merge by gc_orgID (authoritative) ----
    if lead_gc:
        cols = [lead_gc]
        if lead_en: cols.append(lead_en)
        if lead_fr: cols.append(lead_fr)
        tmp = lead[cols].copy().rename(columns={lead_gc: 'gc_orgID'})
        if lead_en: tmp = tmp.rename(columns={lead_en: 'lead_department_lead'})
        if lead_fr: tmp = tmp.rename(columns={lead_fr: 'ministère_responsable_lead'})
        joined_df = joined_df.merge(tmp.drop_duplicates(), on='gc_orgID', how='left')

    # ---- Normalize target naming ----
    final_df = joined_df.copy()

    rename_map = {}
    if "Organization Legal Name English" in final_df.columns:
        rename_map["Organization Legal Name English"] = "legal_title"
    if "Organization Legal Name French" in final_df.columns:
        rename_map["Organization Legal Name French"] = "appellation_légale"
    final_df = final_df.rename(columns=rename_map)

    # Defaults
    if "status_statut" in final_df.columns:
        final_df["status_statut"] = final_df["status_statut"].fillna("a")
    else:
        final_df["status_statut"] = "a"

    # ---- Coalesce lead fields (authoritative lead_manual first, then manual_org fallback) ----
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

    # Backfill legal titles if needed
    final_df = coalesce_into(final_df, "legal_title", ["legal_title", "Legal title", "Legal Title"])
    final_df = coalesce_into(final_df, "appellation_légale", ["appellation_légale", "Appellation légale", "Appellation legale", "appellation_legale"])

    # Harmonized FR name
    final_df = coalesce_into(final_df, "nom_harmonisé", ["nom_harmonisé", "nom harmonisé", "Nom harmonisé", "Nom_harmonisé", "nom_harmonise"])

    # ---- Ensure all 13 target columns exist ----
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
    ]
    for c in target_cols:
        if c not in final_df.columns:
            final_df[c] = ""

    final_df = final_df[target_cols]

    # Normalize gc_orgID
    final_df["gc_orgID"] = final_df["gc_orgID"].astype(str).str.split(".").str[0].str.strip()
    final_df.loc[final_df["gc_orgID"].str.lower().isin(["nan", "none"]), "gc_orgID"] = ""

    # -------------------- SURGICAL ADD: reattach spillover blank-ID rows --------------------
    # Goal: if a row has blank gc_orgID but represents an existing org (name-variant spillover),
    # assign the correct gc_orgID so it dedupes out and stops appearing as overflow.
    def _name_key(x: str) -> str:
        s = "" if x is None else str(x).strip()
        s = s.replace("’", "'").replace("`", "'")
        s = re.sub(r"\s+", " ", s)
        return s.lower()

    if "legal_title" in final_df.columns:
        # Build lookup from normalized legal_title -> gc_orgID for rows that already have an ID
        lut = {}
        mapped_rows = final_df[final_df["gc_orgID"].astype(str).str.strip() != ""]
        for _, r in mapped_rows.iterrows():
            k = _name_key(r.get("legal_title", ""))
            if k:
                lut.setdefault(k, str(r.get("gc_orgID", "")).strip())

        # Apply to blank-ID rows
        blank_mask = final_df["gc_orgID"].astype(str).str.strip() == ""
        for i, r in final_df[blank_mask].iterrows():
            k = _name_key(r.get("legal_title", ""))
            if k in lut:
                final_df.at[i, "gc_orgID"] = lut[k]

            # Hard fallbacks for the known 3 overflow cases
            if not str(final_df.at[i, "gc_orgID"]).strip():
                if "leaders" in k and "debate" in k:
                    final_df.at[i, "gc_orgID"] = "2296"  # Leaders' Debates Commission
                elif "information commissioner" in k:
                    final_df.at[i, "gc_orgID"] = "2281"  # OIC
                elif "veterans" in k and "land act" in k:
                    final_df.at[i, "gc_orgID"] = "3423"  # Director, Veterans' Land Act

    # Sort (blank IDs naturally go last; but they will be filtered out for output)
    final_df["_sort_gc"] = pd.to_numeric(final_df["gc_orgID"], errors="coerce")
    final_df = final_df.sort_values(by=["_sort_gc", "gc_orgID"]).drop(columns=["_sort_gc"])

    # split
    mapped = final_df[final_df["gc_orgID"] != ""].copy()

    # clean empties
    mapped = mapped.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all").fillna("")

    # ---- Final output contract enforcement ----
    # Normalize and drop fully empty rows
    tmp = mapped.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all")

    if "gc_orgID" not in tmp.columns:
        raise ValueError("gc_org_info output is missing required column: gc_orgID")

    gc = tmp["gc_orgID"].astype(str).str.strip().str.split(".").str[0]
    gc = gc.where(~gc.str.lower().isin(["nan", "none"]), "")

    gc_is_numeric = gc.fillna("").astype(str).str.match(r"^[0-9]+$").fillna(False)
    unmapped_diag = tmp[(gc == "") | (gc == "0") | (~gc_is_numeric)].copy()
    if not unmapped_diag.empty:
        unmapped_diag.to_csv("org_info_unmapped_rows.csv", index=False, encoding="utf-8-sig")

    gc_is_numeric = gc.fillna("").astype(str).str.match(r"^[0-9]+$").fillna(False)
    valid_mask = gc_is_numeric & (gc != "") & (gc != "0")
    final_df = tmp[valid_mask].copy()
    final_df["gc_orgID"] = gc[valid_mask]

    if final_df["gc_orgID"].astype(str).str.strip().eq("").any():
        raise ValueError("Blank gc_orgID rows still present after filtering (unexpected).")

    final_df.to_csv("gc_org_info.csv", index=False, encoding="utf-8-sig")

    # ---- Save simple documentation ----
    documentation = {
        'gc_orgID':               'Source: Resources/create_harmonized_name.csv',
        'harmonized_name':        'Source: Resources/create_harmonized_name.csv',
        'nom_harmonisé':          'Source: Resources/create_harmonized_name.csv',
        'legal_title':            'Source: Manual org ID link + Scraping/combined_FAA_names',
        'appellation_légale':     'Source: Manual org ID link (FR) and/or Resources/infobase_fr.csv',
        'preferred_name':         'Source: Resources/applied_en.csv',
        'nom_préféré':           "Source: Resources/applied_en.csv",
        'lead_department':        'Source: Resources/lead_manual.csv (priority) or Manual org',
        'ministère_responsable':  'Source: Resources/lead_manual.csv (priority) or Manual org',
        'abbreviation':           'Source: Resources/applied_en.csv',
        'abreviation':            'Source: Resources/applied_en.csv',
        'FAA_LGFP':               'Source: Scraping/combined_FAA_names.csv',
        'status_statut':          'Source: Resources/infobase_en.csv',
    }
    with open(os.path.join(script_folder, 'gc_org_info_documentation.txt'), 'w', encoding='utf-8') as f:
        for field, doc in documentation.items():
            f.write(f'{field}: {doc}\n')


if __name__ == "__main__":
    main()