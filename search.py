"""
Ask a Question Back — Claude calls.

1. search(): which photos match what the person described, plus any clues they stated (year, month, place)
2. phrase(): turn a template question into one that refers to their search
"""

SEARCH_MODEL = "claude-haiku-4-5-20251001"

SEARCH_SYSTEM = """You help someone find a photo in their own photo library.

Each library line is: id | date | place | description | occasion | people | tags

Call report_matches exactly once.

matches — ids of photos whose CONTENT fits the search (what is in the photo, the activity, the occasion), best match first.
- Judge content only. Do not use the date or place to exclude a photo: those are handled separately as clues.
- Normal mode: include photos that clearly fit the described content.
- Broad mode: the person did NOT find their photo among the close matches. Include anything that could plausibly be what they mean, even partially — similar food, a similar outing, the same kind of scene.
- Return at most 150 ids. Return an empty list if nothing fits.

clues — only details the search states explicitly:
- year: "2025", "last August 2025" -> 2025. Otherwise null.
- month: "Aug", "in July" -> the month number. Otherwise null.
- place: a named city or place, e.g. "in Hyderabad" -> "Hyderabad". Otherwise null.
Never guess a clue that is not in the search text."""

TOOL = {
    "name": "report_matches",
    "description": "Report matching photo ids and any explicit clues in the search.",
    "input_schema": {
        "type": "object",
        "properties": {
            "matches": {"type": "array", "items": {"type": "string"}},
            "clues": {
                "type": "object",
                "properties": {
                    "year": {"type": ["integer", "null"]},
                    "month": {"type": ["integer", "null"]},
                    "place": {"type": ["string", "null"]},
                },
                "required": ["year", "month", "place"],
            },
        },
        "required": ["matches", "clues"],
    },
}


def library_lines(photos: list) -> str:
    rows = []
    for p in photos:
        rows.append(" | ".join([
            p["id"], p.get("date") or "", p.get("place") or "", p.get("caption") or "",
            p.get("occasion") or "", p.get("people") or "", ", ".join(p.get("tags") or []),
        ]))
    return "\n".join(rows)


def search(client, photos: list, query: str, broad: bool = False, model: str = SEARCH_MODEL) -> dict:
    mode = "BROAD" if broad else "NORMAL"
    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SEARCH_SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "report_matches"},
        messages=[{
            "role": "user",
            "content": f"<library>\n{library_lines(photos)}\n</library>\n\nMode: {mode}\nSearch: {query}",
        }],
    )
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use":
            data = block.input
            known = {p["id"] for p in photos}
            ids, seen = [], set()
            for i in data.get("matches", []):
                if i in known and i not in seen:
                    ids.append(i)
                    seen.add(i)
            clues = data.get("clues") or {}
            return {"ids": ids, "clues": {k: clues.get(k) for k in ("year", "month", "place")}}
    return {"ids": [], "clues": {"year": None, "month": None, "place": None}}


PHRASE_SYSTEM = """Rewrite a question so it refers naturally to what the person searched for.
Keep the meaning exactly. At most 12 words. Friendly, plain English.
Output only the question, nothing else."""


def phrase(client, query: str, template: str, model: str = SEARCH_MODEL) -> str:
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=60,
            system=PHRASE_SYSTEM,
            messages=[{"role": "user", "content": f"Search: {query}\nQuestion: {template}"}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip().strip('"')
        return text if 0 < len(text) <= 120 else template
    except Exception:
        return template
