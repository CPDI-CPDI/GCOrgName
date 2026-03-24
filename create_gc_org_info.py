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
    # keep base-file lead columns under distinct names; DO NOT rename to lead_department here
    if man_lead_en and man_lead_en != 'man_lead_department':
        man2 = man2.rename(columns={man_lead_en: 'man_lead_department'})
    if man_lead_fr and man_lead_fr != 'man_ministère_responsable':
        man2 = man2.rename(columns={man_lead_fr: 'man_ministère_responsable'})

    joined_df = pd.merge(
        man2,
        faa,  # already has 'Organization Legal Name English'
        on='Organization Legal Name English',
        how='outer'
    )

    # ---- Enrich from Applied EN (drop right key post-merge) ----
    if app_key:
        app_cols = [c for c in [app_key, app_applied, app_titre, app_abbr_en, app_abbr_fr] if c]
        joined_df = merge_drop_right_key(
            joined_df, app,
            left_on='Organization Legal Name English',
            right_on=app_key,
            select_cols=app_cols,
            how='left'
        )
    else:
        # Soft fallback: if app has 'Organization Legal Name English' but we couldn't resolve app_key
        fallback_key = find_col(app, ['Organization Legal Name English'])
        if fallback_key:
            app_cols = [c for c in [fallback_key, app_applied, app_titre, app_abbr_en, app_abbr_fr] if c]
            joined_df = merge_drop_right_key(
                joined_df, app,
                left_on='Organization Legal Name English',
                right_on=fallback_key,
                select_cols=app_cols,
                how='left'
            )

    # ---- Enrich from InfoBase EN (also drop right key) ----
    if ibe_key:
        ibe_cols = [c for c in [ibe_key, ibe_stat, ibe_end] if c]
        joined_df = merge_drop_right_key(
            joined_df, ibe,
            left_on='Organization Legal Name English',
            right_on=ibe_key,
            select_cols=ibe_cols,
            how='left'
        )

    # ---- Enrich from Harmonized Names (gc_orgID) ----
    if har_gc:
        har_cols = [c for c in [har_gc, har_en, har_fr] if c]
        # prefer joining on gc_orgID
        if har_gc == 'gc_orgID':
            joined_df = joined_df.merge(har[har_cols].drop_duplicates(), on='gc_orgID', how='left')
        else:
            joined_df = merge_drop_right_key(
                joined_df, har,
                left_on='gc_orgID',
                right_on=har_gc,
                select_cols=har_cols,
                how='left'
            )

    # ---- Clean & rename to canonical output headers ----
    if 'gc_orgID' in joined_df.columns:
        joined_df['gc_orgID'] = joined_df['gc_orgID'].astype(str).str.split('.').str[0]

    rename_map = {}
    # Legal titles
    rename_map['Organization Legal Name English'] = 'legal_title'
    if 'Organization Legal Name French' in joined_df.columns:
        rename_map['Organization Legal Name French'] = 'appellation_légale'

    # FAA -> FAA_LGFP if present
    faa_col = find_col(joined_df, ['FAA', 'FAA_LGFP', 'FAA-LGFP'])
    if faa_col:
        rename_map[faa_col] = 'FAA_LGFP'

    # Applied EN to preferred_name / nom_préféré
    if app_applied: rename_map[app_applied] = 'preferred_name'
    if app_titre:   rename_map[app_titre]   = 'nom_préféré'

    # Abbreviations
    if app_abbr_en: rename_map[app_abbr_en] = 'abbreviation'
    if app_abbr_fr: rename_map[app_abbr_fr] = 'abreviation'

    # Status / End date
    if ibe_stat: rename_map[ibe_stat] = 'status_statut'
    if ibe_end:  rename_map[ibe_end]  = 'end_date_fin'  # we won't include it in the final 13

    # Harmonized names (FR kept accented)
    if har_en: rename_map[har_en] = 'harmonized_name'
    if har_fr: rename_map[har_fr] = 'nom_harmonisé'

    final_df = joined_df.rename(columns=rename_map)

    # ---- Defaults & coercions ----
    if 'status_statut' in final_df.columns:
        final_df['status_statut'] = final_df['status_statut'].fillna('a')

    if 'end_date_fin' in final_df.columns:
        def _coerce_end(x):
            if pd.isna(x) or str(x).strip() == '':
                return ''
            try:
                return str(int(float(str(x).strip())))  # tolerate "2024.0"
            except Exception:
                return str(x).strip()
        final_df['end_date_fin'] = final_df['end_date_fin'].apply(_coerce_end)

    # ---- Merge lead department (gc_orgID) with SAFE column names ----
    if lead_gc:
        lead2 = dfs['manual_lead_department'].copy()
        lead2[lead_gc] = lead2[lead_gc].astype(str)

        # Rename to *_lead names BEFORE merge to forbid _x/_y creation
        rename_lead = {lead_gc: 'gc_orgID'}
        if lead_en: rename_lead[lead_en] = 'lead_department_lead'
        if lead_fr: rename_lead[lead_fr] = 'ministère_responsable_lead'
        lead2 = lead2.rename(columns=rename_lead)

        keep = [c for c in ['gc_orgID', 'lead_department_lead', 'ministère_responsable_lead'] if c in lead2.columns]
        final_df = final_df.merge(lead2[keep].drop_duplicates(), on='gc_orgID', how='left')

    # ---- FINAL: coalesce and DROP ALL lead department duplicates ----
    # Build single 'lead_department' with strict priority
    lead_candidates = [
        'lead_department_lead',          # authoritative (lead manual)
        'man_lead_department',           # fallback (manual_org, if present)
        'lead_department',               # any pre-existing normalized field
        'lead department',               # spacing variant
        'Lead Department', 'Lead_Department',
        'lead_department_x', 'lead_department_y'
    ] + [c for c in final_df.columns if c.startswith('lead_department_') and c not in ('lead_department', 'lead_department_lead')]

    final_df = coalesce_into(final_df, 'lead_department', lead_candidates)

    # Same for French
    lead_fr_candidates = [
        'ministère_responsable_lead',    # authoritative
        'man_ministère_responsable',     # fallback
        'ministère_responsable',
        'ministere_responsable', 'ministère responsable',
        'Ministère Responsable', 'Ministere_Responsable',
        'ministère_responsable_x', 'ministère_responsable_y'
    ] + [c for c in final_df.columns if c.startswith('ministère_responsable_') and c not in ('ministère_responsable', 'ministère_responsable_lead')]

    final_df = coalesce_into(final_df, 'ministère_responsable', lead_fr_candidates)

    # ---- Backfill legal titles (EN/FR) in case rename/merge missed variants ----
    legal_en_candidates = [
        'legal_title',                         # expected final
        'Organization Legal Name English',     # original column
        'Legal title', 'Legal Title'           # variant headers
    ]
    final_df = coalesce_into(final_df, 'legal_title', legal_en_candidates)

    legal_fr_candidates = [
        'appellation_légale',                  # expected final
        'Organization Legal Name French',      # original column
        'Appellation légale', 'Appellation legale', 'appellation_legale'
    ]
    final_df = coalesce_into(final_df, 'appellation_légale', legal_fr_candidates)

    # ---- Ensure there is only one 'legal_title' (safety) ----
    legal_dupes = [c for c in final_df.columns if c != 'legal_title' and _norm(c) in {'legal title', 'legal_title'}]
    legal_dupes += [c for c in final_df.columns if c.startswith('legal_title_')]
    legal_dupes = list(dict.fromkeys(legal_dupes))
    for c in legal_dupes:
        if c in final_df.columns:
            final_df = final_df.drop(columns=[c])

    # ---- Ensure harmonized French name is present (coalesce across variants if needed) ----
    # Some upstream drops keep "French Name" or other variants; try to harvest them.
    fr_harm_candidates = [
        'nom_harmonisé',
        'nom harmonisé',
        'Nom harmonisé',
        'Nom_harmonisé',
        'nom_harmonise',          # unaccented backup if present
        'French Name'             # occasional upstream field
    ]
    final_df = coalesce_into(final_df, 'nom_harmonisé', fr_harm_candidates)

    # ---- Apply any hard overrides (optional, example only) ----
    overrides = {
        '2287': {'abbreviation': 'SCC', 'abreviation': 'CSC'},  # Supreme Court of Canada example
    }
    if 'gc_orgID' in final_df.columns:
        for org_id, values in overrides.items():
            for field, value in values.items():
                final_df.loc[final_df['gc_orgID'] == org_id, field] = value

    # ---- Ensure all 13 target columns exist (create empty if missing) ----
    target_cols = [
        'gc_orgID',
        'harmonized_name',
        'nom_harmonisé',
        'legal_title',
        'appellation_légale',
        'preferred_name',
        'nom_préféré',
        'lead_department',
        'ministère_responsable',
        'abbreviation',
        'abreviation',
        'FAA_LGFP',
        'status_statut',
    ]
    for c in target_cols:
        if c not in final_df.columns:
            final_df[c] = ''

    # ---- Keep only these 13, in order ----
    final_df = final_df[target_cols]

    # ---- Sort by gc_orgID (numeric-friendly) ----
    final_df['gc_orgID'] = final_df['gc_orgID'].astype(str).str.split('.').str[0]
    final_df['_sort_gc'] = pd.to_numeric(final_df['gc_orgID'], errors='coerce')
    final_df = final_df.sort_values(by=['_sort_gc', 'gc_orgID']).drop(columns=['_sort_gc'])

    # normalize
    final_df["gc_orgID"] = final_df["gc_orgID"].astype(str).str.split(".").str[0].str.strip()
    final_df.loc[final_df["gc_orgID"].str.lower().isin(["nan", "none"]), "gc_orgID"] = ""

    # split
    mapped = final_df[final_df["gc_orgID"] != ""].copy()
    unmapped = final_df[final_df["gc_orgID"] == ""].copy()

    # clean empties
    mapped = mapped.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all").fillna("")
    unmapped = unmapped.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all").fillna("")

    # ---- Final output contract enforcement ----
    # Normalize and drop fully empty rows
    tmp = mapped.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all")

    # Separate unmapped diagnostics BEFORE enforcing (optional but useful)
    if "gc_orgID" not in tmp.columns:
        raise ValueError("gc_org_info output is missing required column: gc_orgID")

    gc = tmp["gc_orgID"].astype(str).str.strip().str.split(".").str[0]
    gc = gc.where(~gc.str.lower().isin(["nan", "none"]), "")

    unmapped = tmp[(gc == "") | (gc == "0") | (~gc.str.match(r"^[0-9]+$"))].copy()
    if not unmapped.empty:
        unmapped.to_csv("org_info_unmapped_rows.csv", index=False, encoding="utf-8-sig")

    # Enforce: ONLY valid gc_orgID rows make it into gc_org_info.csv
    valid_mask = gc.str.match(r"^[0-9]+$") & (gc != "") & (gc != "0")
    final_df = tmp[valid_mask].copy()
    final_df["gc_orgID"] = gc[valid_mask]

    # Fail hard if anything invalid remains (shouldn't)
    if final_df["gc_orgID"].astype(str).str.strip().eq("").any():
        raise ValueError("Blank gc_orgID rows still present after filtering (unexpected).")

    final_df.to_csv("gc_org_info.csv", index=False, encoding="utf-8-sig")

    # ---- Save simple documentation (aligned to final headers) ----
    documentation = {
        'gc_orgID':               'Source: Resources/create_harmonized_name.csv',
        'harmonized_name':        'Source: Resources/create_harmonized_name.csv',
        'nom_harmonisé':          'Source: Resources/create_harmonized_name.csv',
        'legal_title':            'Source: Manual org ID link + Scraping/combined_FAA_names',
        'appellation_légale':     'Source: Manual org ID link (FR) and/or Resources/infobase_fr.csv',
        'preferred_name':         'Source: Resources/applied_en.csv',
        'nom_préféré':           'Source: Resources/applied_en.csv',
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

