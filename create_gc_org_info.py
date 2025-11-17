# -*- coding: utf-8 -*-
"""
GC Org Info builder — robust to header variants, BOMs, dtype quirks,
and avoids duplicate 'legal_title' / 'lead_department' columns.
"""

import os
import re
import unicodedata
import pandas as pd


# ---------- Normalization + resolution helpers ----------

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
                   .str.replace('\\u2011', '-', regex=False)
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
    Merge and then drop the right-hand key column to avoid creating a duplicate
    of the join key (e.g., 'Legal title').
    """
    if select_cols is not None:
        right = right[select_cols].drop_duplicates()
    out = left.merge(right, left_on=left_on, right_on=right_on, how=how)
    # Drop the right key if present (pandas keeps it when using left_on/right_on)
    if right_on in out.columns:
        out = out.drop(columns=[right_on])
    return out


def coalesce_columns(df: pd.DataFrame, target: str, candidates: list) -> pd.DataFrame:
    """
    Create/overwrite df[target] with the first non-null among candidates that exist.
    Then drop any duplicate candidate columns (if they differ from target).
    """
    present = [c for c in candidates if c in df.columns]
    if not present:
        return df
    if target not in df.columns:
        df[target] = None
    for c in present:
        df[target] = df[target].where(df[target].notna(), df[c])
    # Drop all present duplicates except the chosen target
    for c in present:
        if c != target and c in df.columns:
            df = df.drop(columns=[c])
    return df


# ---------- IO ----------

def load_dataframes(script_folder: str):
    """Load all required CSV files into dataframes (UTF-8 BOM tolerant, string dtypes)."""
    files = {
        'manual_org':             'Resources/Manual org ID link.csv',
        'combined_faa':           'Scraping/combined_FAA_names.csv',
        'applied_en':             'Resources/applied_en.csv',
        'infobase_en':            'Resources/infobase_en.csv',
        'harmonized_names':       'Resources/create_harmonized_name.csv',
        'manual_lead_department': 'Resources/lead_manual.csv',  # changed in your version
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


# ---------- Business logic ----------

def apply_overrides(df: pd.DataFrame) -> pd.DataFrame:
    """Apply manual overrides to specific organizations."""
    overrides = {
        '2287': {'abbreviation': 'SCC', 'abreviation': 'CSC'},
        # add more gc_orgID overrides here as needed
    }
    if 'gc_orgID' not in df.columns:
        return df
    for org_id, values in overrides.items():
        for field, value in values.items():
            df.loc[df['gc_orgID'] == org_id, field] = value
    return df


def main():
    """Create GC organization information file, robust to header changes and duplicates."""
    script_folder = os.path.dirname(os.path.abspath(__file__))

    # ---- Load ----
    dfs = load_dataframes(script_folder)

    # ---- Resolve key columns in source frames ----

    # manual_org
    man = dfs['manual_org']
    man_gc = find_col(man, ['gc_orgID', 'gc orgid', 'gc_orgid'])
    man_en = find_col(man, ['Organization Legal Name English', 'Legal title', 'legal_title', 'English Name'])
    man_fr = find_col(man, ['Organization Legal Name French', 'Appellation légale', 'appellation_legale'])
    # Some manual files may already carry lead dept info
    man_lead_en = find_col(man, ['lead_department', 'lead department'])
    man_lead_fr = find_col(man, ['ministère_responsable', 'ministere_responsable', 'ministère responsable'])

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
    app_key    = find_col(app, ['Legal title', 'legal_title', 'Legal Title'])
    app_applied = find_col(app, ['Applied title', 'applied_title'])
    app_titre   = find_col(app, ["Titre d'usage", "titre d'usage", 'titre_usage'])
    app_abbr_en = find_col(app, ['Abbreviation', 'abbreviation'])
    app_abbr_fr = find_col(app, ['Abreviation', 'abreviation'])

    # infobase_en
    ibe = dfs['infobase_en']
    ibe_key  = find_col(ibe, ['Legal title', 'legal_title', 'Legal Title'])
    ibe_stat = find_col(ibe, ['Status', 'status', 'Statut'])
    ibe_end  = find_col(ibe, ['End date', 'end_date', 'End Date'])

    # harmonized_names
    har = dfs['harmonized_names']
    har_gc = find_col(har, ['gc_orgID', 'gc orgid', 'gc_orgid'])
    har_en = find_col(har, ['harmonized_name', 'harmonized name'])
    har_fr = find_col(har, ['nom_harmonisé', 'nom harmonisé', 'nom_harmonise'])

    # lead manual
    lead = dfs['manual_lead_department']
    lead_gc = find_col(lead, ['gc_orgID', 'gc orgid', 'gc_orgid'])
    lead_en = find_col(lead, ['lead_department', 'lead department'])
    lead_fr = find_col(lead, ['ministère_responsable', 'ministere_responsable', 'ministère responsable'])

    # ---- Build initial merge (outer) on English legal title ----
    man2 = man.rename(columns={man_en: 'Organization Legal Name English', man_gc: 'gc_orgID'})
    if man_fr:
        man2 = man2.rename(columns={man_fr: 'Organization Legal Name French'})
    # Keep any lead columns in manual_org under unique names to avoid collision later
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

    # Flag matches vs unmatched
    joined_df['Names Match'] = joined_df.apply(
        lambda row: 0 if pd.notna(row['Organization Legal Name English']) else 1,
        axis=1
    )
    unmatched_values = joined_df[joined_df['Names Match'] == 1].copy()
    joined_df = joined_df[joined_df['Names Match'] == 0].copy()

    # ---- Enrich from Applied EN (drop right key post-merge to avoid a second 'Legal title') ----
    if app_key:
        app_cols = [c for c in [app_key, app_applied, app_titre, app_abbr_en, app_abbr_fr] if c]
        joined_df = merge_drop_right_key(
            joined_df, app,
            left_on='Organization Legal Name English',
            right_on=app_key,
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

    # ---- Enrich from Harmonized Names (gc_orgID); drop duplicate right key if same name) ----
    if har_gc:
        har_cols = [c for c in [har_gc, har_en, har_fr] if c]
        # If har_gc equals 'gc_orgID', standard merge on 'gc_orgID' and no right_on needed
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

    # ---- Clean & rename to your canonical output headers ----
    # Ensure gc_orgID string without decimal artifacts
    if 'gc_orgID' in joined_df.columns:
        joined_df['gc_orgID'] = joined_df['gc_orgID'].astype(str).str.split('.').str[0]

    rename_map = {}
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
    if ibe_end:  rename_map[ibe_end]  = 'end_date_fin'
    # Harmonized names
    if har_en: rename_map[har_en] = 'harmonized_name'
    if har_fr: rename_map[har_fr] = 'nom_harmonisé'
    # Manual_org lead columns (if present under temporary names)
    if 'man_lead_department' in joined_df.columns:
        rename_map['man_lead_department'] = 'lead_department'
    if 'man_ministère_responsable' in joined_df.columns:
        rename_map['man_ministère_responsable'] = 'ministère_responsable'

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

    # ---- Merge lead department (gc_orgID) and coalesce duplicates ----
    if lead_gc:
        lead2 = dfs['manual_lead_department'].copy()
        lead2[lead_gc] = lead2[lead_gc].astype(str)
        lead_map = {lead_gc: 'gc_orgID'}
        if lead_en: lead_map[lead_en] = 'lead_department'
        if lead_fr: lead_map[lead_fr] = 'ministère_responsable'
        lead2 = lead2.rename(columns=lead_map)

        keep = [c for c in ['gc_orgID', 'lead_department', 'ministère_responsable'] if c in lead2.columns]
        final_df = final_df.merge(lead2[keep].drop_duplicates(), on='gc_orgID', how='left')

        # Coalesce duplicates if the base file already had these fields
        # Handle variants produced by pandas ('_x'/'_y') or from earlier sources.
        # lead_department
        candidates_lead_en = [c for c in [
            'lead_department_x', 'lead_department_y',
            'lead department', 'lead_department'
        ] if c in final_df.columns] + [c for c in final_df.columns if c.startswith('lead_department_')]
        final_df = coalesce_columns(final_df, 'lead_department', candidates_lead_en)

        # ministère_responsable
        candidates_lead_fr = [c for c in [
            'ministère_responsable_x', 'ministère_responsable_y',
            'ministere_responsable', 'ministère responsable', 'ministère_responsable'
        ] if c in final_df.columns] + [c for c in final_df.columns if c.startswith('ministère_responsable_')]
        final_df = coalesce_columns(final_df, 'ministère_responsable', candidates_lead_fr)

    # ---- Ensure there is only one 'legal_title' ----
    # (If any variant/suffixed columns slipped through, coalesce and drop extras.)
    legal_dupes = [c for c in final_df.columns if c != 'legal_title' and _norm(c) in {'legal title', 'legal_title'}]
    legal_dupes += [c for c in final_df.columns if c.startswith('legal_title_')]
    legal_dupes = list(dict.fromkeys(legal_dupes))  # unique
    if legal_dupes:
        final_df = coalesce_columns(final_df, 'legal_title', ['legal_title'] + legal_dupes)

    # ---- Apply overrides ----
    final_df = apply_overrides(final_df)

    # ---- Reorder/output columns (keep extras at end for transparency) ----
    ordered_fields = [
        'gc_orgID', 'harmonized_name', 'nom_harmonisé', 'legal_title',
        'appellation_légale', 'preferred_name', 'nom_préféré', 'lead_department',
        'ministère_responsable', 'abbreviation', 'abreviation', 'FAA_LGFP',
        'status_statut', 'end_date_fin'
    ]
    cols_in_df = [c for c in ordered_fields if c in final_df.columns]
    extras = [c for c in final_df.columns if c not in cols_in_df]
    if 'gc_orgID' in final_df.columns:
        sort_key = 'gc_orgID'
    elif cols_in_df:
        sort_key = cols_in_df[0]
    else:
        sort_key = final_df.columns[0]
    final_df = final_df[cols_in_df + extras].sort_values(by=sort_key)

    
    # Final cleanup: ensure only one 'lead_department'
    if 'lead_department_x' in final_df.columns or 'lead_department_y' in final_df.columns:
    final_df['lead_department'] = final_df.get('lead_department_x').combine_first(final_df.get('lead_department_y'))
    final_df = final_df.drop(columns=[c for c in ['lead_department_x', 'lead_department_y'] if c in final_df.columns])


    # ---- Save outputs ----
    final_df.to_csv(os.path.join(script_folder, 'gc_org_info.csv'), index=False, encoding='utf-8-sig')
    unmatched_values.to_csv(os.path.join(script_folder, 'unmatched_org_IDs.csv'), index=False, encoding='utf-8-sig')

    # ---- Save simple documentation ----
    documentation = {
        'gc_orgID':              'Source: Resources/create_harmonized_name.csv',
        'harmonized_name':       'Source: Resources/create_harmonized_name.csv',
        'nom_harmonisé':         'Source: Resources/create_harmonized_name.csv',
        'legal_title':           'Source: Manual org ID link + Scraping/combined_FAA_names',
        'appellation_légale':    'Source: Manual org ID link (if column exists)',
        'preferred_name':        'Source: Resources/applied_en.csv',
        'nom_préféré':          'Source: Resources/applied_en.csv',
        'lead_department':       'Source: Resources/lead_manual.csv (coalesced if present in manual_org)',
        'ministère_responsable': 'Source: Resources/lead_manual.csv (coalesced if present in manual_org)',
        'abbreviation':          'Source: Resources/applied_en.csv',
        'abreviation':           'Source: Resources/applied_en.csv',
        'FAA_LGFP':              'Source: Scraping/combined_FAA_names.csv',
        'status_statut':         'Source: Resources/infobase_en.csv',
        'end_date_fin':          'Source: Resources/infobase_en.csv'
    }
    with open(os.path.join(script_folder, 'gc_org_info_documentation.txt'), 'w', encoding='utf-8') as f:
        for field, doc in documentation.items():
            f.write(f'{field}: {doc}\n')


if __name__ == "__main__":
    main()
