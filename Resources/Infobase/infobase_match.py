import os
import re
import pandas as pd
from rapidfuzz import fuzz, process

SCRIPT_FOLDER = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.dirname(SCRIPT_FOLDER)

MANUAL_ORG = os.path.join(RESOURCES, "Manual org ID link.csv")
INFOBASE_EN = os.path.join(RESOURCES, "Infobase", "infobase_en.csv")

OUT_MATCHED = os.path.join(RESOURCES, "Infobase", "infobase_matched.csv")
OUT_QUEUE = os.path.join(RESOURCES, "Infobase", "infobase_review_queue.csv")

os.makedirs(os.path.join(RESOURCES, "Infobase"), exist_ok=True)

def norm_name(s: str) -> str:
    s = "" if s is None else str(s)
    s = s.strip()
    s = s.replace("’", "'")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s'-]", "", s)  # drop punctuation except - '
    return s.lower()

def acronym(s: str) -> str:
    s = norm_name(s)
    parts = re.split(r"[\s\-]+", s)
    parts = [p for p in parts if p and p not in {"of","the","and","for","to","in","on","la","le","les","des","du","de"}]
    if not parts:
        return ""
    return "".join(p[0] for p in parts).upper()

def main():
    manual = pd.read_csv(MANUAL_ORG, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    ibe = pd.read_csv(INFOBASE_EN, dtype=str, keep_default_na=False, encoding="utf-8-sig")

    # Resolve essential columns
    if "gc_orgID" not in manual.columns:
        raise ValueError("Manual org file missing gc_orgID")
    if "Organization Legal Name English" not in manual.columns:
        raise ValueError("Manual org file missing Organization Legal Name English")

    # InfoBase: try common header variants
    ib_id = "org_id" if "org_id" in ibe.columns else ("OrgID" if "OrgID" in ibe.columns else None)
    ib_title = "legal_title" if "legal_title" in ibe.columns else ("Legal title" if "Legal title" in ibe.columns else None)
    ib_status = "status" if "status" in ibe.columns else ("status_statut" if "status_statut" in ibe.columns else None)
    ib_end = "end_fin" if "end_fin" in ibe.columns else ("end_date" if "end_date" in ibe.columns else None)

    if not ib_id or not ib_title:
        raise ValueError(f"InfoBase missing org_id/legal_title. Have: {list(ibe.columns)}")

    # Precompute InfoBase candidates list
    ibe = ibe.copy()
    ibe["__ib_title_norm"] = ibe[ib_title].map(norm_name)
    ibe["__ib_acronym"] = ibe[ib_title].map(acronym)
    ib_choices = ibe["__ib_title_norm"].tolist()

    # Manual org normalized
    manual = manual.copy()
    manual["gc_orgID"] = manual["gc_orgID"].astype(str).str.split(".").str[0].str.strip()
    manual["__name_norm"] = manual["Organization Legal Name English"].map(norm_name)
    if "abbreviation" in manual.columns:
        manual["__abbr"] = manual["abbreviation"].astype(str).str.strip().str.upper()
    else:
        manual["__abbr"] = ""

    rows = []
    queue_rows = []

    # Matching thresholds
    MIN_SCORE_OK = 92
    COLLISION_GAP = 2  # if top2 within 2 points, flag collision

    for _, r in manual.iterrows():
        gc_orgID = r["gc_orgID"]
        src_name = r["Organization Legal Name English"]
        q = r["__name_norm"]
        abbr = r["__abbr"]

        if not gc_orgID or not q:
            continue

        # top 5 candidates by token_set_ratio (good for reordered words)
        matches = process.extract(
            q,
            ib_choices,
            scorer=fuzz.token_set_ratio,
            limit=5
        )

        best_norm, best_score, best_idx = matches[0] if matches else ("", 0, None)
        second_score = matches[1][1] if len(matches) > 1 else 0

        # Get the InfoBase row
        cand = ibe.iloc[best_idx] if best_idx is not None else None

        cand_id = cand[ib_id] if cand is not None else ""
        cand_title = cand[ib_title] if cand is not None else ""
        cand_status = cand[ib_status] if (cand is not None and ib_status) else ""
        cand_end = cand[ib_end] if (cand is not None and ib_end) else ""

        # Boost if abbreviation matches InfoBase acronym
        reasons = []
        boosted_score = best_score
        if abbr and cand is not None and cand["__ib_acronym"] == abbr:
            boosted_score = min(100, boosted_score + 3)
            reasons.append("acronym_boost")

        # Determine review requirement
        needs_review = False
        if boosted_score < MIN_SCORE_OK:
            needs_review = True
            reasons.append("low_score")
        if (best_score - second_score) <= COLLISION_GAP and second_score > 0:
            needs_review = True
            reasons.append("collision_top2_close")
        if not cand_id:
            needs_review = True
            reasons.append("no_candidate")

        row = {
            "gc_orgID": gc_orgID,
            "GCOrg_legal_title": src_name,
            "GCOrg_abbreviation": abbr,
            "Candidate_infobaseID": str(cand_id).split(".")[0].strip(),
            "Candidate_legal_title": cand_title,
            "Candidate_status": cand_status,
            "Candidate_end_fin": cand_end,
            "MatchScore": int(boosted_score),
            "SecondBestScore": int(second_score),
            "ReviewReasons": ";".join(reasons),
        }
        rows.append(row)

        if needs_review:
            queue_rows.append(row)

    matched_df = pd.DataFrame(rows)
    queue_df = pd.DataFrame(queue_rows)

    matched_df.to_csv(OUT_MATCHED, index=False, encoding="utf-8-sig")
    queue_df.to_csv(OUT_QUEUE, index=False, encoding="utf-8-sig")

    print(f"Wrote: {OUT_MATCHED} ({len(matched_df)} rows)")
    print(f"Wrote: {OUT_QUEUE} ({len(queue_df)} rows needing review)")

if __name__ == "__main__":
    main()