
import csv
import subprocess
import os
import json
from datetime import datetime
import pandas as pd

# Helper function to extract diffs for a given file
def extract_negative_diffs(target_file, output_file):
    # Read headers from the current version of the file
    with open(target_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        headers = next(reader)

    # Get all commits that modified the target file
    log_output = subprocess.check_output(
        ["git", "log", "--pretty=format:%H|%cd", "--date=iso", "--", target_file],
        text=True
    )
    commits = [line.strip().split("|") for line in log_output.strip().split("\n")]

    output_rows = []

    for commit_hash, commit_date in commits:
        try:
            current_content = subprocess.check_output(
                ["git", "show", f"{commit_hash}:{target_file}"],
                stderr=subprocess.DEVNULL,
                text=True
            )
        except subprocess.CalledProcessError:
            continue

        try:
            prev_commit = subprocess.check_output(
                ["git", "rev-list", "-n", "1", f"{commit_hash}^"],
                text=True
            ).strip()
            prev_content = subprocess.check_output(
                ["git", "show", f"{prev_commit}:{target_file}"],
                stderr=subprocess.DEVNULL,
                text=True
            )
        except subprocess.CalledProcessError:
            continue

        with open("old_version.tmp", "w", encoding='utf-8-sig') as f:
            f.write(prev_content)
        with open("new_version.tmp", "w", encoding='utf-8-sig') as f:
            f.write(current_content)

        try:
            diff_output = subprocess.check_output(
                ["diff", "-u", "old_version.tmp", "new_version.tmp"],
                text=True,
                stderr=subprocess.DEVNULL
            )
            diff_lines = diff_output.splitlines()
        except subprocess.CalledProcessError as e:
            diff_lines = e.output.splitlines() if e.output else []

        for line in diff_lines:
            if line.startswith("-") and not line.startswith("---"):
                removed_line = line[1:].strip()
                values = next(csv.reader([removed_line]))
                row_dict = dict(zip(headers, values))
                row_dict["commit_date"] = commit_date
                output_rows.append(row_dict)

    os.remove("old_version.tmp")
    os.remove("new_version.tmp")

    # Write to CSV with utf-8-sig encoding
    if output_rows:
        fieldnames = ["commit_date"] + headers
        with open(output_file, "w", newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in output_rows:
                writer.writerow(row)

# Process gc_concordance.csv
extract_negative_diffs("gc_concordance.csv", "Archives/concordance_archive_by_date.csv")

# Sort by gc_orgID and save
df_concordance = pd.read_csv("Archives/concordance_archive_by_date.csv", encoding='utf-8-sig')
df_concordance_sorted = df_concordance.sort_values(by="gc_orgID")
df_concordance_sorted.to_csv("Archives/concordance_archive_by_ID.csv", index=False, encoding='utf-8-sig')

# Process gc_org_info.csv
extract_negative_diffs("gc_org_info.csv", "Archives/org_info_archive_by_date.csv")

# Sort by commit_date (newest to oldest)
df_org_info = pd.read_csv("Archives/org_info_archive_by_date.csv", encoding='utf-8-sig')
df_org_info_sorted_date = df_org_info.sort_values(by="commit_date", ascending=False)
df_org_info_sorted_date.to_csv("Archives/org_info_archive_by_date.csv", index=False, encoding='utf-8-sig')

# Sort by gc_orgID
df_org_info_sorted_id = df_org_info.sort_values(by="gc_orgID")
df_org_info_sorted_id.to_csv("Archives/org_info_archive_by_ID.csv", index=False, encoding='utf-8-sig')

