
import subprocess
import csv
import json
import os
import pandas as pd

# Load the headers from the target CSV file
df = pd.read_csv("gc_concordance.csv", encoding="utf-8-sig")
headers = df.columns.tolist()[1:]  # Skip the index column if present

# Set the target file path relative to the repo root
target_file = "gc_concordance.csv"

# Get all commits that modified the target file
log_output = subprocess.check_output(
    ["git", "log", "--pretty=format:%H|%cd", "--date=iso", "--", target_file],
    text=True
)

commits = [line.strip().split("|") for line in log_output.strip().split("\n")]

output_rows = []

for commit_hash, commit_date in commits:
    try:
        diff_output = subprocess.check_output(
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
        prev_diff_output = subprocess.check_output(
            ["git", "show", f"{prev_commit}:{target_file}"],
            stderr=subprocess.DEVNULL,
            text=True
        )
    except subprocess.CalledProcessError:
        continue

    with open("old_version.tmp", "w", encoding="utf-8-sig") as f:
        f.write(prev_diff_output)
    with open("new_version.tmp", "w", encoding="utf-8-sig") as f:
        f.write(diff_output)

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
            values = removed_line.split(",")
            row_dict = dict(zip(headers, values))
            row_dict["commit_date"] = commit_date
            output_rows.append(row_dict)

os.remove("old_version.tmp")
os.remove("new_version.tmp")

# Write to CSV with utf-8-sig encoding
output_headers = headers + ["commit_date"]
with open("concordance_archive.csv", "w", newline='', encoding="utf-8-sig") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=output_headers)
    writer.writeheader()
    writer.writerows(output_rows)

