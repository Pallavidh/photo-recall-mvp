"""
Ask a Question Back — MVP (Phase 1: Path A and Path C).

Path A: 20+ photos -> photos plus a narrowing question; answers become filters (max 3).
Path C: fewer than 20 -> just the photos, then "Did you find it?". "No" searches more broadly and asks.
The user can pick a photo or end the search at any point.
"""

import csv
import io
import json
import os
import time
from datetime import datetime

import streamlit as st

import mvp_logic as L
import search as S

st.set_page_config(page_title="Find a photo", page_icon="🔍", layout="wide")

LIB_DIR = "library"
LIB_FILE = os.path.join(LIB_DIR, "library.json")
PAGE = 20              # photos shown before "+N more"
MAX_CALLS = 60         # AI calls per visit, protects the API budget


# ---------------------------------------------------------------- setup

def secret(name, default=""):
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)


@st.cache_resource
def get_client():
    key = secret("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key)


@st.cache_data
def load_library(path, mtime):
    with open(path, encoding="utf-8") as f:
        photos = json.load(f)
    return sorted(photos, key=lambda p: p.get("date") or "", reverse=True)


client = get_client()
ss = st.session_state
ss.setdefault("attempt", None)
ss.setdefault("log", [])
ss.setdefault("calls", 0)

if not os.path.exists(LIB_FILE):
    st.error("No photo library found. Run prepare_library.py and add the library folder to the repo.")
    st.stop()
LIB = load_library(LIB_FILE, os.path.getmtime(LIB_FILE))
BY_ID = {p["id"]: p for p in LIB}


def budget_ok(cost=1):
    if client is None:
        st.error("Searching is off because no API key is set.")
        return False
    if ss.calls + cost > MAX_CALLS:
        st.warning("This prototype allows a limited number of searches per visit. Refresh the page to continue.")
        return False
    return True


# ---------------------------------------------------------------- state changes

def new_attempt(query):
    if not budget_ok():
        return
    try:
        res = S.search(client, LIB, query)
    except Exception as e:
        st.session_state["error"] = f"The search didn't go through ({e}). Try again."
        return
    ss.calls += 1
    filters = L.clue_filters(res["clues"])
    photos = L.apply_filters([BY_ID[i] for i in res["ids"]], filters)
    ss.attempt = {
        "query": query,
        "ids": res["ids"],
        "filters": filters,
        "skip": [f["attr"] for f in filters],
        "asked": 0,
        "broad": False,
        "said_no": False,
        "answers": [],
        "started": time.time(),
        "first_count": len(photos),
        "path": "A" if L.needs_question(photos, 0) else "C",
        "shown": PAGE,
        "q": None,
        "q_key": None,
        "done": False,
        "outcome": None,
        "found_id": None,
    }


def photos_now(a):
    return L.apply_filters([BY_ID[i] for i in a["ids"]], a["filters"])


def question_now(a, photos):
    if not L.needs_question(photos, a["asked"], a["broad"]):
        return None
    key = (len(photos), a["asked"], tuple(sorted(a["skip"])))
    if a["q_key"] == key:
        return a["q"]
    q = L.pick_question(photos, set(a["skip"]))
    if q and client and ss.calls < MAX_CALLS:
        q["question"] = S.phrase(client, a["query"], q["question"])
        ss.calls += 1
    a["q"], a["q_key"] = q, key
    return q


def answer(option):
    a = ss.attempt
    q = a["q"]
    f = L.answer_to_filter(q, option)
    if f:
        a["filters"].append(f)
    a["skip"].append(q["attr"])
    a["asked"] += 1
    a["answers"].append(f"{L.LABELS[q['attr']]}: {option}")
    a["shown"] = PAGE
    a["q_key"] = None


def remove_filter(i):
    a = ss.attempt
    f = a["filters"].pop(i)
    if f["attr"] in a["skip"]:
        a["skip"].remove(f["attr"])
    a["answers"].append(f"Removed: {L.filter_label(f)}")
    a["shown"] = PAGE
    a["q_key"] = None


def found(pid):
    finish("Found (picked a photo)", pid)


def said_yes():
    finish("Found (said yes)")


def said_no():
    a = ss.attempt
    if a["broad"]:
        finish("Not found")
        return
    if not budget_ok():
        return
    try:
        res = S.search(client, LIB, a["query"], broad=True)
    except Exception as e:
        st.session_state["error"] = f"The wider search didn't go through ({e}). Try again."
        return
    ss.calls += 1
    merged = list(dict.fromkeys(a["ids"] + res["ids"]))
    a["ids"] = merged
    a["broad"] = True
    a["said_no"] = True
    a["answers"].append("Said: not found")
    a["shown"] = PAGE
    a["q_key"] = None


def end_search():
    finish("Ended search")


def finish(outcome, pid=None):
    a = ss.attempt
    a["done"] = True
    a["outcome"] = outcome
    a["found_id"] = pid
    ss.log.append({
        "tester": ss.get("tester", ""),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "search": a["query"],
        "first_results": a["first_count"],
        "path": a["path"],
        "said_not_found": "yes" if a["said_no"] else "no",
        "questions_answered": a["asked"],
        "steps": " | ".join(a["answers"]),
        "outcome": outcome,
        "photo": pid or "",
        "seconds": round(time.time() - a["started"]),
    })


def reset():
    ss.attempt = None


def pretty_date(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return d or ""


# ---------------------------------------------------------------- sidebar

with st.sidebar:
    st.header("About this prototype")
    st.write("Search this sample photo library the way you'd search your own. "
             "When there are lots of results, it asks one question at a time to narrow them down. "
             "You can pick a photo or end the search whenever you like.")
    st.text_input("Your name (for the test log)", key="tester")
    st.caption(f"Library: {len(LIB)} photos · AI calls this visit: {ss.calls} of {MAX_CALLS}")

    st.header("Test log")
    if ss.log:
        st.dataframe(ss.log, hide_index=True)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(ss.log[0].keys()))
        w.writeheader()
        w.writerows(ss.log)
        st.download_button("Download test log (CSV)", buf.getvalue(), "test_log.csv", "text/csv")
    else:
        st.caption("Each finished search is recorded here.")


# ---------------------------------------------------------------- main

st.title("Find a photo")

with st.form("search", clear_on_submit=False):
    q_text = st.text_input("Describe the photo you're looking for",
                           placeholder='e.g. "biryani in Hyderabad" or "me in a yellow dress"')
    if st.form_submit_button("Search", type="primary") and q_text.strip():
        new_attempt(q_text.strip())

if ss.get("error"):
    st.error(ss.pop("error"))

a = ss.attempt
if a is None:
    st.write("Try describing a photo the way you'd remember it — a place, a meal, an occasion, roughly when.")
    st.stop()

# ----- finished
if a["done"]:
    if a["found_id"]:
        p = BY_ID[a["found_id"]]
        secs = ss.log[-1]["seconds"]
        st.success(f"Found it in {secs} seconds, after {a['asked']} "
                   f"question{'s' if a['asked'] != 1 else ''}.")
        st.image(os.path.join(LIB_DIR, p["file"]), width=420)
        st.caption(f"{pretty_date(p.get('date'))}, {p.get('place') or ''} — {p.get('caption') or ''}")
    elif a["outcome"].startswith("Found"):
        st.success("Glad you found it.")
    else:
        st.info("Search ended. Try describing it differently — a person, a place or roughly when.")
    st.button("Start a new search", on_click=reset, type="primary")
    st.stop()

photos = photos_now(a)
q = question_now(a, photos)

# ----- filters and exit
top_l, top_r = st.columns([5, 1])
with top_l:
    if a["filters"]:
        st.write("Showing photos that match:")
        cols = st.columns(min(len(a["filters"]), 6))
        for i, f in enumerate(a["filters"]):
            cols[i % len(cols)].button(f"{L.filter_label(f)}  ✕", key=f"f{i}_{len(a['filters'])}",
                                       on_click=remove_filter, args=(i,),
                                       help="Remove this filter to see more photos")
with top_r:
    st.button("End search", key="end_top", on_click=end_search)

st.write(f"**{len(photos)} photo{'s' if len(photos) != 1 else ''}**")

# ----- the question (Path A, or after 'not found')
if q:
    with st.container(border=True):
        st.subheader(q["question"])
        opts = q["options"] + ([L.OTHER] if q["has_other"] else []) + [L.NOT_SURE]
        cols = st.columns(len(opts))
        for i, o in enumerate(opts):
            cols[i].button(o, key=f"o{a['asked']}_{i}", on_click=answer, args=(o,),
                           type="primary" if o not in (L.OTHER, L.NOT_SURE) else "secondary")
        st.caption("Or just pick your photo below.")

# ----- empty results
if not photos:
    st.info("No photos match. Remove a filter above, or let us look more widely.")

# ----- photo grid
shown = photos[: a["shown"]]
for r in range(0, len(shown), 4):
    cols = st.columns(4)
    for c, p in zip(cols, shown[r:r + 4]):
        with c:
            st.image(os.path.join(LIB_DIR, p["file"]), width=220)
            st.caption(f"{pretty_date(p.get('date'))}, {p.get('place') or ''}")
            st.button("This is it", key=f"pick_{p['id']}", on_click=found, args=(p["id"],))

if len(photos) > a["shown"]:
    if st.button(f"+{len(photos) - a['shown']} more"):
        a["shown"] += PAGE
        st.rerun()

# ----- Path C: no question pending -> confirm
if not q:
    with st.container(border=True):
        if not photos and not a["broad"]:
            st.write("**Nothing matched closely.**")
            st.button("Look more widely", on_click=said_no, type="primary")
        elif not photos:
            st.write("**Nothing close to that description in this library.**")
            st.button("End search", key="end_bottom", on_click=end_search)
        else:
            st.write("**Is it here now?**" if a["broad"] else "**Did you find what you were looking for?**")
            y, n = st.columns(2)
            y.button("Yes", on_click=said_yes, type="primary")
            n.button("No, still not here" if a["broad"] else "No, not yet", on_click=said_no)
