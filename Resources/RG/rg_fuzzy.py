import os
import pandas as pd
from rapidfuzz import process

# Enable debugging
DEBUG = True

def debug_print(message):
    if DEBUG:
        print(f"DEBUG: {message}")

# Paths to the CSV files
script_folder = os.path.dirname(os.path.abspath(__file__))
rg_dir = os.path.join(script_folder, 'RG')
os.makedirs(rg_dir, exist_ok=True)
rg_data_file = os.path.join(rg_dir, 'rg_data.csv')
manual_org_file = os.path.join(script_folder, 'Manual org ID link.csv')
matched_file = os.path.join(rg_dir, 'rg_matched.csv')
fixed_file = os.path.join(rg_dir, 'rg_fixed.csv')  # read only in Step 2
review_queue_file = os.path.join(rg_dir, 'rg_review_queue.csv')

debug_print(f"Script folder: {script_folder}")
debug_print(f"RG data file: {rg_data_file}")
debug_print(f"Manual org file: {manual_org_file}")
debug_print(f"Fixed file (read-only): {fixed_file}")
debug_print(f"Review queue file: {review_queue_file}")

# Read the CSV files
rg_data_df = pd.read_csv(rg_data_file)
debug_print(f"RG data loaded with {len(rg_data_df)} rows")
debug_print(f"RG data columns: {list(rg_data_df.columns)}")

manual_org_df = pd.read_csv(manual_org_file)
debug_print(f"Manual org data loaded with {len(manual_org_df)} rows")
debug_print(f"Manual org columns: {list(manual_org_df.columns)}")
debug_print(f"First 5 organization names: {manual_org_df['Organization Legal Name English'].head().tolist()}")

# Try to read the fixed file, but create an empty DataFrame if it doesn't exist
# (read-only for duplicate/review awareness; no writing in Step 2)
try:
    fixed_df = pd.read_csv(fixed_file)
    debug_print(f"Fixed data loaded with {len(fixed_df)} rows")
    debug_print(f"Fixed data columns: {list(fixed_df.columns)}")
except FileNotFoundError:
    debug_print("Fixed file not found, creating empty DataFrame (read-only)")
    fixed_df = pd.DataFrame(columns=['RGOriginalName', 'rgnumber', 'MatchedName', 'MatchScore', 'Organization Legal Name English', 'gc_orgID'])

# Extract the relevant columns for matching
rg_names = rg_data_df['rg_dept_en']
manual_org_names = manual_org_df['Organization Legal Name English']

# Function to perform fuzzy matching and return best match and score
def fuzzy_match(name, choices, threshold=80):
    if pd.isna(name) or name == "":
        debug_print("Empty name provided to fuzzy_match")
        return None, 0

    debug_print(f"Fuzzy matching: '{name}'")
    result = process.extractOne(name, choices)

    if result is not None:
        match, score = result[0], result[1]
        debug_print(f"Match found: '{match}' with score {score}")
        if score >= threshold:
            return match, score
        else:
            debug_print(f"Score below threshold ({threshold})")
    else:
        debug_print("No match found")

    return None, 0

# Perform fuzzy matching for rg_data_df
debug_print("Starting fuzzy matching process...")
matches = rg_names.apply(lambda x: fuzzy_match(x, manual_org_names))
debug_print(f"Completed fuzzy matching: {len(matches)} results")

# Create a DataFrame with the matching results
match_df = pd.DataFrame({
    'RGOriginalName': rg_names,
    'rgnumber': rg_data_df['rgnumber'],
    'MatchedName': matches.apply(lambda x: x[0]),
    'MatchScore': matches.apply(lambda x: x[1])
})

debug_print(f"Created match_df with {len(match_df)} rows")
debug_print(f"Match_df columns: {list(match_df.columns)}")
debug_print(f"Sample of matches: {match_df[['RGOriginalName', 'MatchedName', 'MatchScore']].head().to_dict('records')}")

# Function to look up Organization Legal Name English and gc_orgID from manual_org_df
def lookup_org_details(matched_name):
    if pd.isna(matched_name) or matched_name == "":
        debug_print("Empty matched_name provided to lookup_org_details")
        return None, None

    debug_print(f"Looking up details for: '{matched_name}'")

    # First try exact match
    match_row = manual_org_df[manual_org_df['Organization Legal Name English'] == matched_name]
    if not match_row.empty:
        org_name = match_row['Organization Legal Name English'].iloc[0]
        org_id = match_row['gc_orgID'].iloc[0]
        debug_print(f"Found exact match: name='{org_name}', id={org_id}")
        return org_name, org_id

    # If no exact match, try a fuzzy match with a high threshold
    debug_print("No exact match found, trying fuzzy match")
    best_match = process.extractOne(matched_name, manual_org_df['Organization Legal Name English'])
    if best_match and best_match[1] > 95:  # High confidence threshold
        match_name = best_match[0]
        match_row = manual_org_df[manual_org_df['Organization Legal Name English'] == match_name]
        if not match_row.empty:
            org_name = match_row['Organization Legal Name English'].iloc[0]
            org_id = match_row['gc_orgID'].iloc[0]
            debug_print(f"Found fuzzy match: name='{org_name}', id={org_id}, score={best_match[1]}")
            return org_name, org_id

    debug_print(f"No match found in manual_org_df for '{matched_name}'")
    return matched_name, None  # Return the matched_name as fallback for org_name (to be tightened in later step)

# Apply the lookup function to get Organization Legal Name English and gc_orgID
debug_print("Looking up organization details...")
org_details = match_df['MatchedName'].apply(lookup_org_details)
debug_print(f"Completed organization detail lookup: {len(org_details)} results")

match_df['Organization Legal Name English'] = org_details.apply(lambda x: x[0] if x is not None else None)
match_df['gc_orgID'] = org_details.apply(lambda x: x[1] if x is not None else None)

# Make a special check for matches with no gc_orgID
debug_print("Checking for matches with no gc_orgID...")
for i, row in match_df.iterrows():
    if pd.isna(row['gc_orgID']) or row['gc_orgID'] == "":
        debug_print(f"Row {i} has no gc_orgID: {row['RGOriginalName']} -> {row['MatchedName']}")
        # Look for the matched name directly in manual_org_df
        try:
            closest_match = process.extractOne(row['MatchedName'], manual_org_df['Organization Legal Name English'])
            if closest_match and closest_match[1] >= 95:
                match_name = closest_match[0]
                debug_print(f"Found close match: {match_name} with score {closest_match[1]}")
                match_row = manual_org_df[manual_org_df['Organization Legal Name English'] == match_name]
                if not match_row.empty:
                    debug_print(f"Setting Organization Legal Name English to {match_name}")
                    match_df.at[i, 'Organization Legal Name English'] = match_name
                    match_df.at[i, 'gc_orgID'] = match_row['gc_orgID'].iloc[0]
        except Exception as e:
            debug_print(f"Error during closest match lookup: {str(e)}")

# Count how many records have Organization Legal Name English populated after additional check
debug_print(f"Records with 'Organization Legal Name English' populated after additional check: {match_df['Organization Legal Name English'].notna().sum()}")
debug_print(f"Records with 'gc_orgID' populated after additional check: {match_df['gc_orgID'].notna().sum()}")

# Count how many records have Organization Legal Name English populated
debug_print(f"Records with 'Organization Legal Name English' populated: {match_df['Organization Legal Name English'].notna().sum()}")
debug_print(f"Records with 'gc_orgID' populated: {match_df['gc_orgID'].notna().sum()}")

# Identify records with missing Organization Legal Name English
missing_org_names = match_df[match_df['Organization Legal Name English'].isna()]
if not missing_org_names.empty:
    debug_print("Example of records with missing Organization Legal Name English:")
    debug_print(missing_org_names[['RGOriginalName', 'MatchedName', 'MatchScore']].head().to_dict('records'))

# Create final_df from match_df
final_df = match_df.copy()

# Ensure 'rgnumber' values do not have decimals (Step 3 will revisit identifier handling)
final_df['rgnumber'] = pd.to_numeric(final_df['rgnumber'], errors='coerce').fillna(0).astype(int)

# Sort by 'MatchedName' and 'MatchScore' in descending order (readability only)
final_df = final_df.sort_values(by=['MatchedName', 'MatchScore'], ascending=[True, False])

# STEP 1 HARDENING: flag collisions instead of dropping duplicate MatchedName rows
final_df['CandidateCollision'] = (
    final_df['MatchedName'].notna() &
    final_df['MatchedName'].astype(str).str.strip().ne('') &
    final_df.duplicated(subset=['MatchedName'], keep=False)
)

collision_count = int(final_df['CandidateCollision'].sum())
debug_print(f"Flagged {collision_count} rows with candidate collisions (no rows removed)")

# Reorder columns for rg_matched.csv
matched_columns = ['RGOriginalName', 'rgnumber', 'MatchedName', 'MatchScore', 'gc_orgID', 'CandidateCollision']
final_df_matched = final_df[matched_columns]

debug_print(f"Prepared final_df_matched with {len(final_df_matched)} rows and columns: {list(final_df_matched.columns)}")

# Save the result to rg_matched.csv
final_df_matched.to_csv(matched_file, index=False, encoding='utf-8-sig')
debug_print(f"Saved matched data to {matched_file}")

# =========================
# STEP 2 HARDENING (NEW)
# Generate review queue instead of auto-updating rg_fixed.csv
# =========================

# Track whether row already exists in rg_fixed.csv (for reviewer context only)
if 'RGOriginalName' in fixed_df.columns:
    fixed_name_set = set(fixed_df['RGOriginalName'].dropna().astype(str).str.strip())
else:
    fixed_name_set = set()

final_df['AlreadyInFixed'] = final_df['RGOriginalName'].astype(str).str.strip().isin(fixed_name_set)

# Define review conditions (conservative for Step 2; threshold policy will be tightened later)
REVIEW_SCORE_THRESHOLD = 95

final_df['Review_LowScore'] = final_df['MatchScore'].fillna(0) < REVIEW_SCORE_THRESHOLD
final_df['Review_NoMatchedName'] = final_df['MatchedName'].isna() | final_df['MatchedName'].astype(str).str.strip().eq('')
final_df['Review_NoGcOrgID'] = final_df['gc_orgID'].isna() | final_df['gc_orgID'].astype(str).str.strip().eq('')
final_df['Review_CandidateCollision'] = final_df['CandidateCollision'].fillna(False)

# Any review reason
review_mask = (
    final_df['Review_LowScore'] |
    final_df['Review_NoMatchedName'] |
    final_df['Review_NoGcOrgID'] |
    final_df['Review_CandidateCollision']
)

review_df = final_df.loc[review_mask].copy()

# Add a compact text reason column for human reviewers
def build_review_reasons(row):
    reasons = []
    if row.get('Review_LowScore', False):
        reasons.append('LowScore')
    if row.get('Review_NoMatchedName', False):
        reasons.append('NoMatchedName')
    if row.get('Review_NoGcOrgID', False):
        reasons.append('NoGcOrgID')
    if row.get('Review_CandidateCollision', False):
        reasons.append('CandidateCollision')
    return ';'.join(reasons)

if not review_df.empty:
    review_df['ReviewReasons'] = review_df.apply(build_review_reasons, axis=1)
else:
    review_df['ReviewReasons'] = pd.Series(dtype='object')

# Reorder review queue columns for readability
review_columns = [
    'RGOriginalName',
    'rgnumber',
    'MatchedName',
    'MatchScore',
    'Organization Legal Name English',
    'gc_orgID',
    'CandidateCollision',
    'AlreadyInFixed',
    'Review_LowScore',
    'Review_NoMatchedName',
    'Review_NoGcOrgID',
    'Review_CandidateCollision',
    'ReviewReasons'
]

# Ensure all columns exist
for col in review_columns:
    if col not in review_df.columns:
        review_df[col] = None

review_df = review_df[review_columns]

# Save review queue
review_df.to_csv(review_queue_file, index=False, encoding='utf-8-sig')
debug_print(f"Saved review queue to {review_queue_file} with {len(review_df)} rows")

print(f"The matched names have been saved to {matched_file}")
print(f"Review queue has been saved to {review_queue_file}")
print("rg_fixed.csv was NOT modified (manual-authoritative mode)")