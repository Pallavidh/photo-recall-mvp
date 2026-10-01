# Ask a Question Back — MVP (Phase 1)

A working prototype of the selected solution: when a photo search returns a pile, it asks one question at a time to narrow it down, and every answer becomes a filter the user can remove.

## What it does

**Path A — lots of results.** If a search returns 20 or more photos, the photos appear with a question above them ("Do you remember which year it was?"). Tapping an option filters the photos. It asks at most 3 questions, and the user can pick a photo or end the search at any time.

**Path C — few results.** Under 20 photos: just the photos, then "Did you find what you were looking for?"
- **Yes** — the search ends.
- **No** — it searches more widely, then asks a question to narrow the wider set.

Clues typed into the search ("Aug 2025", "in Hyderabad") are applied as filters too, shown at the top with an ✕ to remove them.

**How the question is chosen:** the app checks how the current photos divide by year, month, place, occasion, number of people and setting, and asks about whichever divides them most evenly — so any answer removes a large share. Dates and places (stored in the photo) are preferred over details the AI had to read from the image.

## Files

| File | Purpose |
|---|---|
| `app.py` | The prototype (Streamlit) |
| `mvp_logic.py` | When to ask, which question, how answers filter |
| `search.py` | Claude: match the search to photos; phrase the question naturally |
| `prepare_library.py` | One-time: turns a folder of photos into the library |
| `library/` | The prepared photos and `library.json` |

## Step 1 — Build the photo library (about 30 minutes)

**Choose 150–300 photos** that make the questions meaningful:
- Spread across **at least 3 years** and **3+ cities or places**
- **Repeated subjects** across time — the same kind of food, outfit or outing on different dates. That's what creates a pile worth narrowing.
- Include photos that match your research tasks: biryani in different cities and years, a yellow dress on several occasions, a trip.

**Privacy:** the deployed app is public, so only use photos you're comfortable sharing. The script strips all EXIF (including GPS) from the copies it saves.

**Run the script** — in Google Colab, upload the photos as a zip and `prepare_library.py`, then:

```bash
!pip install -q anthropic pillow pillow-heif reverse_geocoder
!unzip -q raw_photos.zip -d raw_photos
import os, getpass
os.environ["ANTHROPIC_API_KEY"] = getpass.getpass("API key: ")
!python prepare_library.py raw_photos library
!zip -qr library.zip library
```

Download `library.zip`. Photos without a date (WhatsApp forwards, downloads) are listed at the end — add them to an `overrides.csv` (`file,date,place`) and rerun with `python prepare_library.py raw_photos library overrides.csv`.

## Step 2 — Deploy

1. Create a new public GitHub repo. Upload everything in this folder plus the unzipped `library` folder (`library/library.json` and `library/photos/`).
2. share.streamlit.io → Create app → this repo → main file `app.py`.
3. Advanced settings → Secrets:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
4. Deploy, then open the link in an incognito window to check it works.

## Step 3 — Test with 3 users

Give each tester 3 retrieval tasks based on the research, for example:
1. "Find the biryani you had in Hyderabad in August 2025."
2. "Find the photo in the yellow dress from last July."
3. "Find a photo from the Prague trip where you were eating ice cream."

For each task: ask them to type what they remember, in their own words. Don't help. Stop at 3 minutes.

Each finished search is recorded in the sidebar **Test log** — have each tester enter their name first, then download the CSV at the end. It records: the search, first result count, path (A or C), whether they said "not found", questions answered, each step, outcome and seconds taken.

**Watch for** (this decides Phase 2):
- Did they understand each question? Could they answer it?
- Did any answer remove the photo they wanted — and did they notice the ✕?
- Did they reach for "Not sure"?
- Did they pick the photo early, or wait for more questions?

## Limits of this prototype
- Uses a sample library, not the tester's own Google Photos.
- Path B (detecting a stuck user from scrolling and taps) is not built; the "Did you find it?" step stands in for it.
- Search uses Claude over photo descriptions — a stand-in for Google's search, not a replacement.
- 60 AI calls per visit, to protect the API budget.
