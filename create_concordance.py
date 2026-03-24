import os
import logging
from typing import Dict, Tuple, List, Optional

import pandas as pd
import unicodedata
import re

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------- small utilities ----------------------
def _norm(s: str) -> str:
    """Normalize a header: strip BOM/invisibles, collapse spaces, lower-case."""
    if s is None:
        return ""
    s = str(s).replace("\ufeff", "")
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()

def find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    """
    Return the actual column name in df that matches one of the candidate labels,
    using normalized, case-insensitive comparison (and tolerant to underscores).
    """
    if df is None or df.empty:
        return None

    lut = {}
    for c in df.columns:
        key = _norm(c).replace("_", " ")
        lut[key] = c

    for cand in candidates:
        k = _norm(cand).replace("_", " ")
        if k in lut:
            return lut[k]
    return None

def require_cols(df: pd.DataFrame, cols: List[str], name: str):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"{name} missing columns {missing}. Have: {list(df.columns)}")

def safe_to_int(series: pd.Series) -> pd.Series:
    """
    Coerce a column to nullable integer WITHOUT forcing NaN->0.
    This fixes the 'InfoBase id becomes 0' issue.
    """
    # dtype=str at load -> blanks become '' not NaN; coerce -> NaN
    return pd.to_numeric(series, errors='coerce').astype("Int64")

# ---------------------- original helpers with slight hardening ----------------------
def ensure_required_columns(df: pd.DataFrame, required_columns: List[str], df_name: str) -> None:
    """Ensure that a DataFrame has the required columns."""
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        error_msg = f"Missing required columns in {df_name}: {missing_columns}"
        logger.error(error_msg)
        raise ValueError(error_msg)

def setup_paths() -> Dict[str, str]:
    """Define and return important directory paths used in the script."""
    script_folder = os.path.dirname(os.path.abspath(__file__))
    return {
        'script': script_folder,
        'resources': os.path.join(script_folder, 'Resources'),
        'scraping': os.path.join(script_folder, 'Scraping')
    }

def load_dataframes(paths: Dict[str, str]) -> Dict[str, pd.DataFrame]:
    """
    Load all required CSV files into dataframes.
    Reads as UTF-8 with BOM tolerance, and string dtypes to avoid floaty IDs.
    """
    files = {
        'manual_org_df': os.path.join(paths['resources'], 'Manual org ID link.csv'),
        'combined_faa_df': os.path.join(paths['scraping'], 'combined_FAA_names.csv'),
        'applied_en_df': os.path.join(paths['resources'], 'applied_en.csv'),
        'infobase_en_df': os.path.join(paths['resources'], 'infobase_en.csv'),
        'infobase_fr_df': os.path.join(paths['resources'], 'infobase_fr.csv'),
        'final_rg_match_df': os.path.join(paths['resources'], 'rg_final.csv'),
        'manual_pop_phoenix_df': os.path.join(paths['resources'], 'manual pop phoenix.csv'),
        'harmonized_names_df': os.path.join(paths['resources'], 'create_harmonized_name.csv')
    }

    dfs: Dict[str, pd.DataFrame] = {}
    for name, path in files.items():
        try:
            dfs[name] = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
            logger.info("Successfully loaded %s from %s", name, path)
        except Exception as e:
            logger.error("Error loading %s from %s: %s", name, path, str(e))
            raise
    return dfs

def standardize_dataframes(dfs: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """
    Clean and standardize all dataframes (values).
    Column names will be resolved dynamically at merge time, so we don't force-rename headers here.
    """
    # Standardize text values in object columns
    for name, df in dfs.items():
        dfs[name] = df.apply(
            lambda x: (
                x
                .astype(str)
                .str.replace('’', "'", regex=False)
                .str.replace('\u2011', '-', regex=False)
                .str.strip()
            ) if x.dtype == "object" else x
        )
        # Convert literal 'nan' strings back to empty (because of astype(str))
        for c in dfs[name].columns:
            if dfs[name][c].dtype == "object":
                dfs[name].loc[dfs[name][c].str.lower() == "nan", c] = ""

    # Convert 'gc_orgID' to string where present
    for _, df in dfs.items():
        if 'gc_orgID' in df.columns:
            df['gc_orgID'] = df['gc_orgID'].astype(str)

    # Prepare 'combined_faa_df' join name
    if 'English Name' in dfs['combined_faa_df'].columns:
        dfs['combined_faa_df']['Original English Name'] = dfs['combined_faa_df']['English Name']
        dfs['combined_faa_df'] = dfs['combined_faa_df'].rename(
            columns={'English Name': 'Organization Legal Name English'}
        )

    return dfs

def create_initial_merge(dfs: Dict[str, pd.DataFrame]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Create the initial merge and identify unmatched values."""
    require_cols(dfs['manual_org_df'], ['Organization Legal Name English', 'gc_orgID'], "manual_org_df")
    require_cols(dfs['combined_faa_df'], ['Organization Legal Name English'], "combined_faa_df")

    final_joined_df = dfs['manual_org_df'].merge(
        dfs['combined_faa_df'],
        on='Organization Legal Name English',
        how='outer'
    )

    # Flag matched and unmatched rows
    final_joined_df['Names Match'] = final_joined_df.apply(
        lambda row: 0 if pd.notna(row['Organization Legal Name English']) else 1,
        axis=1
    )

    unmatched_values = final_joined_df[final_joined_df['Names Match'] == 1].copy()
    matched_values = final_joined_df[final_joined_df['Names Match'] == 0].copy()

    return matched_values, unmatched_values

def merge_additional_data(final_joined_df: pd.DataFrame, dfs: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Merge additional data from various sources (Applied EN, InfoBase EN/FR, RG, POP/Phoenix, Harmonized)."""

    # ---------- Applied EN merge ----------
    right_applied = dfs['applied_en_df']
    applied_key = find_col(right_applied, ['Legal title', 'legal_title', 'Legal Title'])

    applied_cols = [
        find_col(right_applied, ['Legal title', 'legal_title', 'Legal Title']),
        find_col(right_applied, ['Applied title', 'applied_title']),
        find_col(right_applied, ["Titre d'usage", "titre d'usage", "titre_usage"]),
        find_col(right_applied, ['Abbreviation', 'abbreviation']),
        find_col(right_applied, ['Abreviation', 'abreviation']),
    ]
    applied_cols = [c for c in applied_cols if c]

    if applied_key:
        final_joined_df = final_joined_df.merge(
            right_applied[applied_cols].drop_duplicates() if applied_cols else right_applied,
            left_on='Organization Legal Name English',
            right_on=applied_key,
            how='left'
        )
    else:
        logger.warning("Skipped Applied EN merge: could not resolve 'Legal title' in applied_en_df")

    # ---------- InfoBase EN merge ----------
    right_inf_en = dfs['infobase_en_df']
    inf_en_key = find_col(right_inf_en, ['legal_title', 'Legal title', 'Legal Title'])
    inf_en_orgid = find_col(right_inf_en, ['org_id', 'OrgID', 'Org Id'])
    inf_en_web = find_col(right_inf_en, ['website', 'Website', 'Site Web', 'site_web'])

    inf_en_cols = [c for c in [inf_en_key, inf_en_orgid, inf_en_web] if c]
    if inf_en_key:
        final_joined_df = final_joined_df.merge(
            right_inf_en[inf_en_cols].drop_duplicates() if inf_en_cols else right_inf_en,
            left_on='Organization Legal Name English',
            right_on=inf_en_key,
            how='left'
        )
    else:
        logger.warning("Skipped InfoBase EN merge: could not resolve 'legal_title' in infobase_en_df")

    # ---------- Pull in harmonized names ----------
    right_harm = dfs['harmonized_names_df']
    harm_gc = find_col(right_harm, ['gc_orgID', 'gc orgid', 'gc_orgid'])
    harm_en = find_col(right_harm, ['harmonized_name', 'harmonized name'])
    harm_fr = find_col(right_harm, ['nom_harmonisé', 'nom harmonisé', 'nom_harmonise'])
    sel = [c for c in [harm_gc, harm_en, harm_fr] if c]

    if harm_gc:
        final_joined_df = final_joined_df.merge(
            right_harm[sel].drop_duplicates() if sel else right_harm,
            left_on='gc_orgID',
            right_on=harm_gc,
            how='left'
        )
    else:
        logger.warning("Skipped harmonized name merge: could not resolve 'gc_orgID' in harmonized_names_df")

    # ---------- Standardize columns (create 'infobaseID' + website) ----------
    if 'gc_orgID' in final_joined_df.columns:
        final_joined_df['gc_orgID'] = final_joined_df['gc_orgID'].astype(str).str.split('.').str[0].str.strip()

    rename_map = {}
    if inf_en_orgid and 'infobaseID' not in final_joined_df.columns:
        rename_map[inf_en_orgid] = 'infobaseID'
    if inf_en_web and 'website' not in final_joined_df.columns:
        rename_map[inf_en_web] = 'website'

    if rename_map:
        final_joined_df = final_joined_df.rename(columns=rename_map)

    if 'infobaseID' not in final_joined_df.columns:
        alt_id = find_col(final_joined_df, ['org_id', 'OrgID'])
        if alt_id:
            final_joined_df = final_joined_df.rename(columns={alt_id: 'infobaseID'})
        else:
            raise KeyError(
                "Expected InfoBase ID but couldn't find it after InfoBase EN merge. "
                f"Available columns: {list(final_joined_df.columns)}"
            )

    # IMPORTANT PATCH: keep nullable Int64, never force missing -> 0
    final_joined_df['infobaseID'] = safe_to_int(final_joined_df['infobaseID'])

    # ---------- RG numbers ----------
    right_rg = dfs['final_rg_match_df']
    rg_gc = find_col(right_rg, ['gc_orgID', 'gc_orgid'])
    rg_num = find_col(right_rg, ['rgnumber', 'rg', 'rg_number'])

    if rg_gc and rg_num:
        final_joined_df = final_joined_df.merge(
            right_rg[[rg_gc, rg_num]].drop_duplicates(),
            left_on='gc_orgID',
            right_on=rg_gc,
            how='left'
        )
        final_joined_df = final_joined_df.rename(columns={rg_num: 'rg'})
    else:
        logger.warning("Skipped RG merge: could not resolve gc_orgID/rgnumber in final_rg_match_df")

    # Format RG nicely (NOTE: keeps blanks blank)
    if 'rg' in final_joined_df.columns:
        def format_rg_value(value):
            if value is None:
                return ''
            v = str(value).strip()
            if v == '' or v.lower() == 'nan':
                return ''
            try:
                # tolerate strings like "001" or "0.0"
                num = int(float(v))
                return '' if num == 0 else str(num)
            except Exception:
                return ''
        final_joined_df['rg'] = final_joined_df['rg'].apply(format_rg_value)

    # ---------- InfoBase FR merge ----------
    right_inf_fr = dfs['infobase_fr_df']
    fr_orgid = find_col(right_inf_fr, ['OrgID', 'org_id', 'Org Id'])
    fr_legal = find_col(right_inf_fr, ['Appellation legale', 'Appellation légale', 'appellation_legale'])
    fr_site = find_col(right_inf_fr, ['Site Web', 'site_web', 'Website'])

    fr_cols = [c for c in [fr_orgid, fr_legal, fr_site] if c]
    if fr_orgid:
        right_inf_fr = right_inf_fr.copy()
        # IMPORTANT PATCH: keep nullable Int64 for join, no fill(0)
        try:
            right_inf_fr[fr_orgid] = safe_to_int(right_inf_fr[fr_orgid])
        except Exception as e:
            logger.warning("Could not coerce FR OrgID to Int64: %s", e)

        final_joined_df = final_joined_df.merge(
            right_inf_fr[fr_cols].drop_duplicates() if fr_cols else right_inf_fr,
            left_on='infobaseID',
            right_on=fr_orgid,
            how='left'
        )

        if fr_site and fr_site != 'site_web':
            final_joined_df = final_joined_df.rename(columns={fr_site: 'site_web'})
    else:
        logger.warning("Skipped InfoBase FR merge: could not resolve OrgID/org_id in infobase_fr_df")

    # ---------- POP & Phoenix ----------
    if 'manual_pop_phoenix_df' in dfs:
        final_joined_df = final_joined_df.merge(
            dfs['manual_pop_phoenix_df'],
            on='gc_orgID',
            how='left'
        )

    # Clean artifacts from merge if present
    if 'gc_orgID_y' in final_joined_df.columns:
        final_joined_df = final_joined_df.drop(columns=['gc_orgID_y'])
    if 'gc_orgID_x' in final_joined_df.columns:
        final_joined_df = final_joined_df.rename(columns={'gc_orgID_x': 'gc_orgID'})

    # IMPORTANT PATCH: do NOT dedupe on gc_orgID here (it will collapse blank IDs)
    # We'll do a safe dedupe later after finalization.

    final_joined_df = final_joined_df.rename(
        columns={
            'Abbreviation': 'abbreviation',
            'Abreviation': 'abreviation'
        }
    )

    return final_joined_df

def apply_manual_changes(df: pd.DataFrame) -> pd.DataFrame:
    """Apply manual changes to specific entries (PRESERVED)."""
    manual_changes = {
        # Office of the Information Commissioner
        "2281": {
            "abbreviation": "OIC",
            "abreviation": "CI",
            "infobaseID": 256,
            "website": "https://www.oic-ci.gc.ca/en",
            "site_web": "https://www.oic-ci.gc.ca/fr"
        },
        # Office of the Privacy Commissioner
        "2282": {
            "abbreviation": "OPC",
            "abreviation": "CPVP",
            "infobaseID": 256,
            "website": "https://www.priv.gc.ca/en/",
            "site_web": "https://www.priv.gc.ca/fr/"
        },
        "2287": {
            "abbreviation": "SCC",
            "abreviation": "CSC",
        },
    }

    if 'gc_orgID' not in df.columns:
        logger.warning("apply_manual_changes: 'gc_orgID' not found; skipping manual changes")
        return df

    for gc_orgid, changes in manual_changes.items():
        for field, value in changes.items():
            df.loc[df['gc_orgID'] == gc_orgid, field] = value

    return df

def finalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # Normalize some header variants to your target names
    rename_map = {
        'Nom harmonisé': 'nom_harmonisé',
        'Nom_harmonisé': 'nom_harmonisé',
        'Site Web': 'site_web',
        'Website': 'website',
        'open_gov': 'open_gov_ouvert',
        'open_gov_ouvert': 'open_gov_ouvert',
        'ati': 'ati'
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Ensure clean numeric-looking IDs (strip Excel decimals like "123.0")
    if 'gc_orgID' in df.columns:
        df['gc_orgID'] = (
            df['gc_orgID']
            .astype(str)
            .str.split('.').str[0]
            .str.strip()
            .str.replace(r'\D+', '', regex=True)
        )

    # If infobaseID came in under another name, map it now (defensive)
    for candidate in ['org_id', 'OrgID', 'Org Id']:
        if candidate in df.columns and 'infobaseID' not in df.columns:
            df = df.rename(columns={candidate: 'infobaseID'})
            break

    # Numeric coercions (leave blanks blank for friendliness in CSV)
    def _to_int_or_blank(s):
        # Keep nullable Int64; convert to string with <NA> -> ''
        v = pd.to_numeric(s, errors='coerce').astype('Int64')
        return v.astype(str).replace({'<NA>': ''})

    if 'infobaseID' in df.columns:
        df['infobaseID'] = _to_int_or_blank(df['infobaseID'])
    if 'rg' in df.columns:
        df['rg'] = _to_int_or_blank(df['rg'])

    # Ensure the exact 13 columns exist
    target_cols = [
        'gc_orgID',
        'harmonized_name',
        'nom_harmonisé',
        'abbreviation',
        'abreviation',
        'infobaseID',
        'rg',
        'ati',
        'open_gov_ouvert',
        'pop',
        'phoenix',
        'website',
        'site_web',
    ]
    for c in target_cols:
        if c not in df.columns:
            df[c] = ''

    # Select and order exactly as requested
    df = df[target_cols]

    # IMPORTANT PATCH: safe dedupe only for rows WITH gc_orgID
    has_id = df['gc_orgID'].astype(str).str.strip() != ""
    df_with_id = df[has_id].drop_duplicates(subset=['gc_orgID'])
    df_without_id = df[~has_id]
    df = pd.concat([df_with_id, df_without_id], ignore_index=True)

    # Sort by gc_orgID (blank IDs go to end)
    df['_sort_gc'] = pd.to_numeric(df['gc_orgID'], errors='coerce')
    df = df.sort_values(by=['_sort_gc', 'gc_orgID']).drop(columns=['_sort_gc'])

    return df

def validate_unmatched_data(unmatched_df: pd.DataFrame) -> None:
    """Validate the unmatched data to ensure data quality."""
    if unmatched_df.empty:
        logger.info("No unmatched records found - data appears to be clean!")
        return

    missing_counts = unmatched_df.isna().sum()
    logger.info("Unmatched records analysis:")
    logger.info("Total unmatched records: %d", len(unmatched_df))
    logger.info("Missing values by column: %s", missing_counts.to_string())

    if 'gc_orgID' in unmatched_df.columns:
        missing_ids = unmatched_df[unmatched_df['gc_orgID'].isna()].shape[0]
        logger.info("Records missing gc_orgID: %d", missing_ids)

def save_results(df: pd.DataFrame, unmatched_df: pd.DataFrame, script_folder: str) -> None:
    """
    Save the final dataframes to CSV files.

    IMPORTANT PATCH:
    - gc_concordance.csv should ONLY contain rows with non-blank gc_orgID
    - any blank gc_orgID rows (from InfoBase etc.) are appended to unmatched_org_IDs.csv
    """
    output_file = os.path.join(script_folder, 'gc_concordance.csv')
    unmatched_output_file = os.path.join(script_folder, 'unmatched_org_IDs.csv')

    try:
        # Split mapped/unmapped based on gc_orgID (post-finalization)
        df = df.copy()
        df['gc_orgID'] = df['gc_orgID'].astype(str).str.strip()
        unmapped_from_df = df[df['gc_orgID'] == ""].copy()
        mapped_df = df[df['gc_orgID'] != ""].copy()

        # Merge unmapped rows into unmatched output (preserve information)
        if unmatched_df is None:
            unmatched_df = pd.DataFrame()

        # Align columns union so concat doesn't lose fields
        all_cols = list(dict.fromkeys(list(unmatched_df.columns) + list(unmapped_from_df.columns)))
        for c in all_cols:
            if c not in unmatched_df.columns:
                unmatched_df[c] = ""
            if c not in unmapped_from_df.columns:
                unmapped_from_df[c] = ""

        combined_unmatched = pd.concat([unmatched_df[all_cols], unmapped_from_df[all_cols]], ignore_index=True)

        # Drop fully empty rows in outputs
        mapped_df = mapped_df.replace(r'^\s*$', pd.NA, regex=True).dropna(how='all').fillna('')
        combined_unmatched = combined_unmatched.replace(r'^\s*$', pd.NA, regex=True).dropna(how='all').fillna('')

        # Validate unmatched data before saving
        validate_unmatched_data(combined_unmatched)

        mapped_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        combined_unmatched.to_csv(unmatched_output_file, index=False, encoding='utf-8-sig')

        logger.info("The final joined DataFrame has been saved to %s", output_file)
        logger.info("The unmatched values have been saved to %s", unmatched_output_file)

    except Exception as e:
        logger.error("Error saving results: %s", str(e))
        raise

def main() -> None:
    """Main function to orchestrate the concordance creation process."""
    try:
        paths = setup_paths()
        dfs = load_dataframes(paths)
        dfs = standardize_dataframes(dfs)

        final_joined_df, unmatched_values = create_initial_merge(dfs)
        final_joined_df = merge_additional_data(final_joined_df, dfs)

        # PRESERVED manual overrides
        final_joined_df = apply_manual_changes(final_joined_df)

        final_joined_df = finalize_dataframe(final_joined_df)

        save_results(final_joined_df, unmatched_values, paths['script'])

    except Exception as e:
        logger.error("An error occurred: %s", str(e))
        raise

if __name__ == "__main__":
    main()