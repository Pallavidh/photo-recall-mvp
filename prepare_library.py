"""
Build the MVP photo library from a folder of photos.

For each photo it:
  1. reads the date and GPS location stored in the photo (EXIF)
  2. turns GPS into a city name (offline, no API)
  3. saves a small copy with all EXIF removed (so no GPS is published)
  4. asks Claude to describe the photo: caption, occasion, people, setting, tags

Usage (Colab or local):
  pip install anthropic pillow pillow-heif reverse_geocoder
  export ANTHROPIC_API_KEY=sk-ant-...
  python prepare_library.py raw_photos library [overrides.csv]

overrides.csv (optional) fills in or corrects date/place per file:
  file,date,place
  IMG_1234.jpg,2025-08-14,Hyderabad
"""

import base64
import csv
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from PIL import Image, ImageOps

try:  # iPhone HEIC photos
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

MODEL = "claude-haiku-4-5-20251001"
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".heic")
MAX_SIDE = 800

OCCASIONS = ["Everyday moment", "Meal out", "Home cooking", "Trip or holiday", "Party or celebration",
             "Festival or religious event", "Wedding", "Work", "Outdoors or nature",
             "Screenshot or document", "Other"]
PEOPLE = ["No people", "One person", "Two people", "A group"]
SETTINGS = ["Indoors", "Outdoors"]

TOOL = {
    "name": "describe_photo",
    "description": "Describe a personal photo for search.",
    "input_schema": {
        "type": "object",
        "properties": {
            "caption": {"type": "string", "description": "What the photo shows, max 15 words, plain English."},
            "occasion": {"type": "string", "enum": OCCASIONS},
            "people": {"type": "string", "enum": PEOPLE},
            "setting": {"type": "string", "enum": SETTINGS},
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "3 to 6 single-word or short tags: objects, food, clothing colours, landmarks."},
        },
        "required": ["caption", "occasion", "people", "setting", "tags"],
    },
}

PROMPT = ("Describe this personal photo so its owner could find it later by memory. "
          "Name specific things people remember: the food, clothing colours, landmarks, activity. "
          "Do not guess names of people.")


def gps_to_decimal(dms, ref):
    d, m, s = [float(x) for x in dms]
    val = d + m / 60 + s / 3600
    return -val if ref in ("S", "W") else val


def read_exif(img):
    date, lat, lon = None, None, None
    try:
        exif = img.getexif()
        sub = exif.get_ifd(0x8769)
        raw = sub.get(36867) or exif.get(306)
        if raw:
            date = datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d")
        gps = exif.get_ifd(0x8825)
        if gps and 2 in gps and 4 in gps:
            lat = gps_to_decimal(gps[2], gps.get(1, "N"))
            lon = gps_to_decimal(gps[4], gps.get(3, "E"))
    except Exception:
        pass
    return date, lat, lon


def load_overrides(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {row["file"].strip(): row for row in csv.DictReader(f)}


def describe(client, jpeg_bytes):
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "describe_photo"},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(jpeg_bytes).decode()}},
            {"type": "text", "text": PROMPT},
        ]}],
    )
    for b in resp.content:
        if getattr(b, "type", "") == "tool_use":
            return b.input
    raise ValueError("No description returned")


def main(src, out, overrides_path=None):
    import anthropic
    import reverse_geocoder as rg

    client = anthropic.Anthropic()
    overrides = load_overrides(overrides_path)
    os.makedirs(os.path.join(out, "photos"), exist_ok=True)

    files = sorted(f for f in os.listdir(src) if f.lower().endswith(EXTS))
    print(f"{len(files)} photos found")

    items, coords = [], []
    for n, name in enumerate(files, start=1):
        img = Image.open(os.path.join(src, name))
        date, lat, lon = read_exif(img)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82)          # saved without EXIF: no GPS is published
        pid = f"p{n:03d}"
        with open(os.path.join(out, "photos", f"{pid}.jpg"), "wb") as f:
            f.write(buf.getvalue())
        items.append({"id": pid, "file": f"photos/{pid}.jpg", "source": name,
                      "date": date, "place": None, "_jpeg": buf.getvalue()})
        coords.append((lat, lon))

    located = [(i, c) for i, c in enumerate(coords) if c[0] is not None]
    if located:
        results = rg.search([c for _, c in located], verbose=False)
        for (i, _), r in zip(located, results):
            items[i]["place"] = r.get("name")

    for it in items:
        o = overrides.get(it["source"])
        if o:
            it["date"] = (o.get("date") or "").strip() or it["date"]
            it["place"] = (o.get("place") or "").strip() or it["place"]

    def work(it):
        return it["id"], describe(client, it["_jpeg"])

    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(work, it) for it in items]
        by_id = {it["id"]: it for it in items}
        for fut in as_completed(futures):
            try:
                pid, d = fut.result()
                by_id[pid].update({k: d.get(k) for k in ("caption", "occasion", "people", "setting", "tags")})
            except Exception as e:
                print("  description failed:", e)
            done += 1
            print(f"\r  described {done}/{len(items)}", end="", flush=True)
    print()

    library = []
    for it in items:
        it.pop("_jpeg", None)
        it.pop("source", None)
        library.append(it)
    with open(os.path.join(out, "library.json"), "w", encoding="utf-8") as f:
        json.dump(library, f, ensure_ascii=False, indent=1)

    missing = [x["id"] for x in library if not x.get("date")]
    print(f"Saved {len(library)} photos to {out}/library.json")
    if missing:
        print(f"  {len(missing)} photos have no date — add them to overrides.csv: {', '.join(missing[:10])}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python prepare_library.py raw_photos library [overrides.csv]")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
