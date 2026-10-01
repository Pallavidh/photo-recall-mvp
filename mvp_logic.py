"""
Ask a Question Back — core logic (no UI, no API calls).

Decides when to ask, which question to ask, and how answers filter the photos.
"""

from collections import Counter

THRESHOLD = 20          # 20+ photos ≈ more than one phone screen
MAX_QUESTIONS = 3       # never ask more than this per search
BROAD_MIN = 6           # after "No, not found": ask while at least this many photos remain
DOMINANT_SHARE = 0.8    # skip a question if one answer covers 80%+ of photos (it wouldn't narrow much)
COVERAGE = 0.6          # skip a question if fewer than 60% of photos have that detail

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

QUESTIONS = {
    "year": "Do you remember which year it was?",
    "month": "Do you remember which month it was?",
    "place": "Do you remember where it was?",
    "occasion": "Do you remember what the occasion was?",
    "people": "How many people were in it?",
    "setting": "Was it indoors or outdoors?",
}

LABELS = {
    "year": "Year", "month": "Month", "place": "Place",
    "occasion": "Occasion", "people": "People", "setting": "Setting",
}

# Reliable details (stored with the photo) are preferred over AI-read ones on ties.
RELIABILITY = {"year": 3, "place": 3, "month": 2, "people": 1, "setting": 1, "occasion": 0}

OTHER = "Something else"
NOT_SURE = "Not sure"


def value(photo: dict, attr: str):
    d = photo.get("date") or ""
    if attr == "year":
        return d[:4] if len(d) >= 4 else None
    if attr == "month":
        return MONTHS[int(d[5:7]) - 1] if len(d) >= 7 and d[5:7].isdigit() else None
    v = photo.get(attr)
    return v if v else None


def distinct_days(photos: list) -> int:
    return len({p.get("date") for p in photos if p.get("date")})


def needs_question(photos: list, asked: int, broad: bool = False) -> bool:
    """Path A rule: 20+ photos. After a 'not found', ask on smaller piles too."""
    if asked >= MAX_QUESTIONS:
        return False
    if broad:
        return len(photos) >= BROAD_MIN
    return len(photos) >= THRESHOLD


def matches(photo: dict, f: dict) -> bool:
    v = value(photo, f["attr"])
    if f["op"] == "eq":
        if f["attr"] == "place":
            return bool(v) and f["value"].lower() in v.lower()
        return v == f["value"]
    if f["op"] == "not_in":
        return v not in f["value"]
    return True


def apply_filters(photos: list, filters: list) -> list:
    return [p for p in photos if all(matches(p, f) for f in filters)]


def filter_label(f: dict) -> str:
    if f["op"] == "not_in":
        return f"{LABELS[f['attr']]}: other"
    return f"{f['value']}"


def pick_question(photos: list, skip: set):
    """Choose the question whose answer would cut the pile most evenly.

    Scores each detail by how evenly the photos divide across its values
    (Gini impurity: higher = more even = any answer removes more photos).
    """
    total = len(photos)
    if total == 0:
        return None
    best = None
    for attr in QUESTIONS:
        if attr in skip:
            continue
        if attr == "month" and "year" not in skip:
            continue  # ask about the year before the month
        vals = [value(p, attr) for p in photos]
        vals = [v for v in vals if v]
        if len(vals) < COVERAGE * total:
            continue
        counts = Counter(vals)
        if len(counts) < 2:
            continue
        if counts.most_common(1)[0][1] / len(vals) >= DOMINANT_SHARE:
            continue
        gini = 1 - sum((n / len(vals)) ** 2 for n in counts.values())
        # Evenness decides; stored details (date, place) win close calls over AI-read ones.
        score = gini + 0.05 * RELIABILITY[attr]
        if best is None or score > best[0]:
            best = (score, attr, counts)
    if best is None:
        return None

    _, attr, counts = best
    options = [v for v, _ in counts.most_common(3)]
    if attr == "year":
        options.sort(reverse=True)
    elif attr == "month":
        options.sort(key=MONTHS.index)
    return {
        "attr": attr,
        "question": QUESTIONS[attr],
        "options": options,
        "has_other": len(counts) > 3,
        "counts": {o: counts[o] for o in options},
    }


def answer_to_filter(q: dict, answer: str):
    """Turn a tapped option into a filter. 'Not sure' returns None (no filter)."""
    if answer == NOT_SURE:
        return None
    if answer == OTHER:
        return {"attr": q["attr"], "op": "not_in", "value": list(q["options"]), "source": "answer"}
    return {"attr": q["attr"], "op": "eq", "value": answer, "source": "answer"}


def clue_filters(clues: dict) -> list:
    """Clues stated in the search itself ('Aug 2025', 'in Hyderabad') become filters too."""
    out = []
    if clues.get("year"):
        out.append({"attr": "year", "op": "eq", "value": str(clues["year"]), "source": "search"})
    if clues.get("month") and 1 <= int(clues["month"]) <= 12:
        out.append({"attr": "month", "op": "eq", "value": MONTHS[int(clues["month"]) - 1], "source": "search"})
    if clues.get("place"):
        out.append({"attr": "place", "op": "eq", "value": str(clues["place"]).strip(), "source": "search"})
    return out
