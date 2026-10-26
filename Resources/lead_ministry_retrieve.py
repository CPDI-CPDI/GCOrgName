
import os
import re
import sys
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup

# URLs
url_en_csv = "https://www.ourcommons.ca/members/en/ministries/csv"
url_fr_csv = "https://www.ourcommons.ca/members/fr/ministries/csv"
# The House of Commons Open Data page documents only the XML export for ministries.
url_en_xml = "https://www.ourcommons.ca/Members/en/ministries/XML"
url_fr_xml = "https://www.ourcommons.ca/Members/fr/ministries/XML"
url_en_scrape = "https://www.pm.gc.ca/en/cabinet"
url_fr_scrape = "https://www.pm.gc.ca/fr/cabinet"

# File paths
output_dir = "Resources"
os.makedirs(output_dir, exist_ok=True)
file_en = os.path.join(output_dir, "lead_ministries_en.csv")
file_fr = os.path.join(output_dir, "lead_ministries_fr.csv")
file_harmonized = os.path.join(output_dir, "lead_code_ministers.csv")
file_manual = os.path.join(output_dir, "manual_minID.csv")

# Set LEAD_MINISTRY_SOFT_FAIL=1 to let the daily pipeline continue (exit 0)
# when the source is blocked or has changed, keeping the existing files.
SOFT_FAIL = os.environ.get("LEAD_MINISTRY_SOFT_FAIL", "").strip() == "1"

HEADERS_EN = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}
HEADERS_FR = {**HEADERS_EN, "Accept-Language": "fr-CA,fr;q=0.9"}

# Header names we expect, with the French / variant spellings mapped onto them.
EN_RENAMES = {
    "person id": "Person ID",
    "precedence": "Precedence",
    "honorific title": "Honorific Title",
    "first name": "First Name",
    "last name": "Last Name",
    "title": "Title",
    "province / territory": "Province / Territory",
    "start date": "Start Date",
    "end date": "End Date",
}
FR_RENAMES = {
    "id de la personne": "ID de la personne",
    "precedence": "Precedence",
    "titre honorifique": "Titre honorifique",
    "prénom": "Prénom",
    "nom de famille": "Nom de famille",
    "titre": "Titre",
    "province / territoire": "Province / Territoire",
    "date de début": "Date de début",
    "date de fin": "Date de fin",
}


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    if SOFT_FAIL:
        print("LEAD_MINISTRY_SOFT_FAIL=1: keeping existing ministry files and exiting 0.")
        sys.exit(0)
    sys.exit(1)


def xml_field_to_header(name, lang):
    """Best-effort mapping of an XML element name onto the CSV header it corresponds to."""
    n = re.sub(r"[^a-z]", "", str(name).lower())
    if lang == "en":
        rules = [("honorific", "Honorific Title"), ("personid", "Person ID"), ("precedence", "Precedence"),
                 ("firstname", "First Name"), ("lastname", "Last Name"), ("province", "Province / Territory"),
                 ("start", "Start Date"), ("end", "End Date"), ("title", "Title")]
    else:
        rules = [("honorific", "Titre honorifique"), ("personid", "ID de la personne"), ("precedence", "Precedence"),
                 ("firstname", "Prénom"), ("lastname", "Nom de famille"), ("province", "Province / Territoire"),
                 ("start", "Date de début"), ("end", "Date de fin"), ("title", "Titre")]
    for key, header in rules:
        if key in n:
            return header
    return str(name)


def fetch_table(csv_url, xml_url, headers, renames, required, lang):
    """
    Get the ministries table. Tries the CSV first, then the documented XML export.
    Checks the response really is the data and normalises header names.
    """
    problems = []
    for kind, url in (("csv", csv_url), ("xml", xml_url)):
        try:
            r = requests.get(url, headers=headers, timeout=60)
        except requests.RequestException as e:
            problems.append(f"{kind} {url}: could not connect ({e})")
            continue

        ctype = r.headers.get("Content-Type", "")
        text = r.content.decode("utf-8-sig", errors="replace")
        if r.status_code != 200:
            problems.append(f"{kind} {r.url}: HTTP {r.status_code}, Content-Type={ctype!r}, body starts {text[:200]!r}")
            continue

        try:
            df = pd.read_csv(StringIO(text)) if kind == "csv" else pd.read_xml(StringIO(text))
        except Exception as e:
            problems.append(f"{kind} {url}: did not parse ({e}), Content-Type={ctype!r}, body starts {text[:200]!r}")
            continue

        if kind == "csv":
            # Strip stray whitespace / BOM / non-breaking spaces, then fix case and spelling variants.
            cleaned = [re.sub(r"\s+", " ", str(c).replace("﻿", "").replace("\xa0", " ")).strip() for c in df.columns]
            df.columns = [renames.get(c.lower(), c) for c in cleaned]
        else:
            df.columns = [xml_field_to_header(c, lang) for c in df.columns]

        missing = [c for c in required if c not in df.columns]
        if missing:
            problems.append(f"{kind} {url}: missing column(s) {missing}; columns received {list(df.columns)}")
            continue

        print(f"Loaded {len(df)} rows from the {kind.upper()} export: {url}")
        return df

    fail("could not load ministries data. " + " | ".join(problems))


def parse_en_dates(series):
    """Parse strings like '2025-03-14 11:31:00 a.m.' into datetimes (bad values become NaT)."""
    s = series.astype("string").str.strip()
    s = s.str.replace(r"\ba\.?\s?m\.?", "AM", case=False, regex=True)
    s = s.str.replace(r"\bp\.?\s?m\.?", "PM", case=False, regex=True)
    return pd.to_datetime(s, errors="coerce")


# Download CSVs
df_en = fetch_table(url_en_csv, url_en_xml, HEADERS_EN, EN_RENAMES, required=["Title", "Start Date"], lang="en")
df_fr = fetch_table(url_fr_csv, url_fr_xml, HEADERS_FR, FR_RENAMES, required=["Titre"], lang="fr")

# Save base files (only reached when both downloads passed the checks above,
# so a blocked or changed response can never overwrite the good copies)
df_en.to_csv(file_en, index=False, encoding="utf-8-sig")
df_fr.to_csv(file_fr, index=False, encoding="utf-8-sig")

# Load manual_minID
df_manual = pd.read_csv(file_manual, encoding="utf-8-sig")
manual_date_cols = [col for col in df_manual.columns if re.match(r"\d{4}-\d{2}-\d{2}", col)]
latest_manual_date = max(pd.to_datetime(manual_date_cols, errors="coerce").date.tolist())

# Latest start date in the source
df_en["Start Date"] = parse_en_dates(df_en["Start Date"])
if df_en["Start Date"].notna().sum() == 0:
    fail(f"no 'Start Date' values could be parsed. Sample raw rows: {df_en.head(3).to_dict('records')}")
latest_start_date = df_en["Start Date"].dropna().dt.date.max()

if latest_start_date <= latest_manual_date:
    print("No new date detected. Exiting.")
    sys.exit(0)

new_date_col = latest_start_date.strftime("%Y-%m-%d")
if new_date_col not in df_manual.columns:
    df_manual[new_date_col] = ""


# Remove rows with "("
def trim_on_paren(df, col):
    if any(df[col].str.contains(r"\(")):
        idx = df[df[col].str.contains(r"\(")].index[0]
        return df.iloc[:idx]
    return df


df_en = trim_on_paren(df_en, "Title")
df_fr = trim_on_paren(df_fr, "Titre")


# Scrape cabinet titles
def scrape_titles(url, headers):
    try:
        r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"WARNING: could not scrape {url} ({e}); using titles from the CSV only.")
        return []
    html = r.content.decode("utf-8-sig", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    div = soup.find("div", class_="field field--name-body field--type-text-with-summary field--label-hidden field--item")
    titles = []
    if div:
        ps = div.find_all("p")
        for i in range(2, len(ps)):
            if ps[i].find("strong") and ps[i].find("br"):
                contents = ps[i].contents
                for j, item in enumerate(contents):
                    if item.name == "br" and j + 1 < len(contents):
                        titles.append(contents[j + 1].strip())
    else:
        print(f"WARNING: cabinet list not found on {url}; page layout may have changed.")
    return titles


scraped_en = scrape_titles(url_en_scrape, HEADERS_EN)
scraped_fr = scrape_titles(url_fr_scrape, HEADERS_FR)


# Replace titles
def update_titles(df, col, scraped):
    for i, title in df[col].items():
        for s in scraped:
            if title.lower() in s.lower():
                df.at[i, col] = s
                break
    return df


df_en = update_titles(df_en, "Title", scraped_en)
df_fr = update_titles(df_fr, "Titre", scraped_fr)

# Harmonize
df_h = df_en.copy()
df_h["Titre"] = df_fr["Titre"]
df_h["minID"] = ""
df_h["notes"] = ""


# Normalize
def norm(text):
    return str(text).replace("\xa0", " ").strip().lower()


# First pass: match using keywords only
def match_with_keywords(row):
    title = norm(row["Title"])
    for idx, mrow in df_manual.iterrows():
        kw = mrow["Keywords"]
        if pd.isna(kw) or kw.strip() == "":
            continue
        kw = str(kw)
        if "," in kw:
            parts = [p.strip().lower() for p in kw.split(",")]
            if all(p in title for p in parts):
                if df_manual.at[idx, new_date_col] == "":
                    df_manual.at[idx, new_date_col] = row["Title"]
                else:
                    df_h.at[row.name, "notes"] += "matched more than once"
                    return False
                df_h.at[row.name, "minID"] = mrow["minID"]
                return True
        else:
            if kw.strip().lower() in title:
                if df_manual.at[idx, new_date_col] == "":
                    df_manual.at[idx, new_date_col] = row["Title"]
                else:
                    df_h.at[row.name, "notes"] += "matched more than once"
                    return False
                df_h.at[row.name, "minID"] = mrow["minID"]
                return True
    return False


# Second pass: assign to blank keyword rows
def assign_to_blank(row):
    if df_h.at[row.name, "minID"] != "":
        return
    blank = df_manual[df_manual["Keywords"].isna() | (df_manual["Keywords"] == "")].index
    if len(blank) > 0:
        idx = blank[0]
    else:
        new_id = f"m{int(df_manual['minID'].str[1:].astype(int).max()) + 1:04d}"
        df_manual.loc[len(df_manual)] = [new_id, row["Title"], "Identify keywords or see if there is a match with another entry, delete this when resolved", *[""] * (len(df_manual.columns) - 3)]
        df_manual.at[len(df_manual) - 1, new_date_col] = row["Title"]
        df_h.at[row.name, "minID"] = new_id
        df_h.at[row.name, "notes"] = "view minID file and confirm need for new minID"
        return
    df_manual.at[idx, "Keywords"] = row["Title"]
    df_manual.at[idx, new_date_col] = row["Title"]
    df_manual.at[idx, "Notes"] = "Identify keywords or see if there is a match with another entry, delete this when resolved"
    new_id = f"m{int(df_manual['minID'].str[1:].astype(int).max()) + 1:04d}"
    df_manual.at[idx, "minID"] = new_id
    df_h.at[row.name, "minID"] = new_id
    df_h.at[row.name, "notes"] = "view minID file and confirm need for new minID"


# Apply two-pass matching
df_h.apply(match_with_keywords, axis=1)
df_h.apply(assign_to_blank, axis=1)

# Save all
df_en.to_csv(file_en, index=False, encoding="utf-8-sig")
df_fr.to_csv(file_fr, index=False, encoding="utf-8-sig")
df_h.to_csv(file_harmonized, index=False, encoding="utf-8-sig")
df_manual.to_csv(file_manual, index=False, encoding="utf-8-sig")

print("\nMinistry Download and Merge process completed.")
