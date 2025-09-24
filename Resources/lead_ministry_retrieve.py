
import pandas as pd
import requests
from bs4 import BeautifulSoup
from io import StringIO
import os
import re
from dateutil import parser

# URLs
url_en_csv = "https://www.ourcommons.ca/members/en/ministries/csv"
url_fr_csv = "https://www.ourcommons.ca/members/fr/ministries/csv"
url_en_scrape = "https://www.pm.gc.ca/en/cabinet"
url_fr_scrape = "https://www.pm.gc.ca/fr/cabinet"

# File paths
output_dir = "Resources"
os.makedirs(output_dir, exist_ok=True)
file_en = os.path.join(output_dir, "lead_ministries_en.csv")
file_fr = os.path.join(output_dir, "lead_ministries_fr.csv")
file_harmonized = os.path.join(output_dir, "lead_code_ministers.csv")
file_manual = os.path.join(output_dir, "manual_minID.csv")

# Download CSVs with UTF-8 decoding
df_en = pd.read_csv(StringIO(requests.get(url_en_csv).content.decode('utf-8-sig')))
df_fr = pd.read_csv(StringIO(requests.get(url_fr_csv).content.decode('utf-8-sig')))

# Save base files
df_en.to_csv(file_en, index=False, encoding='utf-8-sig')
df_fr.to_csv(file_fr, index=False, encoding='utf-8-sig')

# Load manual_minID
df_manual = pd.read_csv(file_manual, encoding='utf-8-sig')
manual_date_cols = [col for col in df_manual.columns if re.match(r"\d{4}-\d{2}-\d{2}", col)]

df_en['Start Date'] = df_en['Start Date'].apply(lambda x: parser.parse(x) if pd.notnull(x) else pd.NaT)
latest_start_date = df_en['Start Date'].dropna().max().date()


# Convert to datetime safely
df_en['Start Date'] = pd.to_datetime(df_en['Start Date'], errors='coerce')

# Drop NaT values before extracting date and computing max
latest_start_date = df_en['Start Date'].dropna().dt.date.max()


if latest_start_date <= latest_manual_date:
    print("No new date detected. Exiting.")
    exit()

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
def scrape_titles(url):
    html = requests.get(url).content.decode('utf-8-sig')
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
    return titles

scraped_en = scrape_titles(url_en_scrape)
scraped_fr = scrape_titles(url_fr_scrape)

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
    return str(text).replace('\\xa0', ' ').strip().lower()

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
        df_manual.loc[len(df_manual)] = [new_id, row["Title"], "Identify keywords or see if there is a match with another entry, delete this when resolved", *[""]*(len(df_manual.columns)-3)]
        df_manual.at[len(df_manual)-1, new_date_col] = row["Title"]
        df_h.at[row.name, "minID"] = new_id
        df_h.at[row.name, "notes"] = "view minID file and confirm need for new minID"
        return
    df_manual.at[idx, "Keywords"] = row["Title"]
    df_manual.at[idx, new_date_col] = row["Title"]
    df_manual.at[idx, "notes"] = "Identify keywords or see if there is a match with another entry, delete this when resolved"
    new_id = f"m{int(df_manual['minID'].str[1:].astype(int).max()) + 1:04d}"
    df_manual.at[idx, "minID"] = new_id
    df_h.at[row.name, "minID"] = new_id
    df_h.at[row.name, "notes"] = "view minID file and confirm need for new minID"

# Apply two-pass matching
df_h.apply(match_with_keywords, axis=1)
df_h.apply(assign_to_blank, axis=1)

# Save all
df_en.to_csv(file_en, index=False, encoding='utf-8-sig')
df_fr.to_csv(file_fr, index=False, encoding='utf-8-sig')
df_h.to_csv(file_harmonized, index=False, encoding='utf-8-sig')
df_manual.to_csv(file_manual, index=False, encoding='utf-8-sig')

print("\nMinistry Download and Merge process completed.")
