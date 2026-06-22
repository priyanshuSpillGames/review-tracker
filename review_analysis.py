import os
import json
import re
import tempfile
import gspread

from google.oauth2.service_account import Credentials
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SHEET_NAME = "Game Reviews"

# ── Credentials ────────────────────────────────────────────────────────────────
if os.path.exists("service_account.json"):
    credentials = Credentials.from_service_account_file(
        "service_account.json", scopes=SCOPES
    )
else:
    service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(service_account_info, f)
        temp_json = f.name
    credentials = Credentials.from_service_account_file(temp_json, scopes=SCOPES)
    try:
        os.unlink(temp_json)
    except Exception:
        pass

gc = gspread.authorize(credentials)
spreadsheet = gc.open(SHEET_NAME)

reviews_sheet  = spreadsheet.worksheet("Reviews")
analysis_sheet = spreadsheet.worksheet("Review Analysis")

analyzer = SentimentIntensityAnalyzer()

# ── Ensure Analysis sheet has headers ─────────────────────────────────────────
ANALYSIS_HEADERS = ["Platform", "App Name", "Review ID", "Rating", "Sentiment", "Category", "Sentiment Score"]
first_row = analysis_sheet.row_values(1)
if first_row != ANALYSIS_HEADERS:
    analysis_sheet.clear()
    analysis_sheet.append_row(ANALYSIS_HEADERS)
    print("Analysis sheet headers written.")

# ── Load existing analysed review IDs ─────────────────────────────────────────
# Analysis sheet columns: Platform | App Name | Review ID | Rating | Sentiment | Category | Sentiment Score
existing_ids = set()
analysis_rows = analysis_sheet.get_all_values()
for row in analysis_rows[1:]:
    if len(row) >= 3 and row[2]:
        existing_ids.add(row[2])

print(f"Already analysed: {len(existing_ids)} reviews")

# ── Load reviews ───────────────────────────────────────────────────────────────
# Reviews sheet columns: Platform | App Name | Identifier | User Name | Review ID | Rating | Review | Date
reviews = reviews_sheet.get_all_values()

rows_to_add = []

def classify_category(text: str) -> str:
    """Classify review into a category using word-boundary-aware matching."""
    t = text.lower()

    def has_word(words):
        return any(re.search(r'\b' + re.escape(w) + r'\b', t) for w in words)

    if has_word(["crash", "crashes", "crashed", "bug", "bugs", "freeze", "freezes",
                 "frozen", "stuck", "glitch", "glitches", "error", "broken"]):
        return "Bug"

    if has_word(["ad", "ads", "advertisement", "advertisements", "popup", "pop-up",
                 "pop up", "banner"]):
        return "Ads"

    if has_word(["pay", "paid", "payment", "purchase", "subscription", "money",
                 "expensive", "price", "cost", "refund", "charge", "charged"]):
        return "Payment"

    if has_word(["hard", "difficult", "difficulty", "impossible", "too hard",
                 "unfair", "unbalanced", "overpowered"]):
        return "Difficulty"

    if has_word(["level", "levels", "stage", "stages", "map", "maps", "world"]):
        return "Levels"

    if has_word(["slow", "lag", "lagging", "laggy", "loading", "load", "performance",
                 "fps", "frame", "stutter", "battery", "heat", "hot"]):
        return "Performance"

    if has_word(["ui", "ux", "interface", "design", "layout", "confusing", "menu",
                 "button", "buttons", "navigation", "ugly", "look", "looks"]):
        return "UI/UX"

    if has_word(["feature", "add", "wish", "want", "would be nice", "suggestion",
                 "request", "please add", "hope", "update"]):
        return "Feature Request"

    return "General"


for row in reviews[1:]:
    # Reviews sheet: Platform(0) | App Name(1) | Identifier(2) | User Name(3) | Review ID(4) | Rating(5) | Review(6) | Date(7)
    if len(row) < 7:
        continue

    platform    = row[0].strip()
    app_name    = row[1].strip()
    review_id   = row[4].strip()   # ← correct column (index 4)
    rating      = row[5].strip()
    review_text = row[6].strip()

    if not review_id or review_id in existing_ids:
        continue

    if not review_text:
        continue

    # ── Sentiment ──────────────────────────────────────────────────────────────
    score = analyzer.polarity_scores(review_text)["compound"]

    if score > 0.2:
        sentiment = "Positive"
    elif score < -0.2:
        sentiment = "Negative"
    else:
        sentiment = "Neutral"

    # ── Category ───────────────────────────────────────────────────────────────
    category = classify_category(review_text)

    rows_to_add.append([
        platform,
        app_name,
        review_id,
        rating,
        sentiment,
        category,
        round(score, 4),
    ])

    existing_ids.add(review_id)

if rows_to_add:
    analysis_sheet.append_rows(rows_to_add, value_input_option="RAW")
    print(f"Added {len(rows_to_add)} analysis rows")
else:
    print("No new reviews to analyse")
