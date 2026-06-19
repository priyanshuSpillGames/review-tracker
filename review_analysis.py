import os
import json
import tempfile
import gspread

from google.oauth2.service_account import Credentials
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SHEET_NAME = "Game Reviews"

if os.path.exists("service_account.json"):
    credentials = Credentials.from_service_account_file(
        "service_account.json",
        scopes=SCOPES
    )
else:
    service_account_info = json.loads(
        os.environ["GOOGLE_SERVICE_ACCOUNT"]
    )

    with tempfile.NamedTemporaryFile(
        mode="w",
        delete=False
    ) as f:
        json.dump(service_account_info, f)
        temp_json = f.name

    credentials = Credentials.from_service_account_file(
        temp_json,
        scopes=SCOPES
    )

gc = gspread.authorize(credentials)

spreadsheet = gc.open(SHEET_NAME)

reviews_sheet = spreadsheet.worksheet("Reviews")
analysis_sheet = spreadsheet.worksheet("Review Analysis")

analyzer = SentimentIntensityAnalyzer()

existing_ids = set()

analysis_rows = analysis_sheet.get_all_values()

for row in analysis_rows[1:]:
    if len(row) >= 3:
        existing_ids.add(row[2])

reviews = reviews_sheet.get_all_values()

rows_to_add = []

for row in reviews[1:]:

    if len(row) < 8:
        continue

    platform = row[0]
    app_name = row[1]
    review_id = row[3]
    rating = row[5]
    review_text = row[6]

    if review_id in existing_ids:
        continue

    score = analyzer.polarity_scores(review_text)["compound"]

    if score > 0.2:
        sentiment = "Positive"
    elif score < -0.2:
        sentiment = "Negative"
    else:
        sentiment = "Neutral"

    text = review_text.lower()

    if any(x in text for x in ["crash", "bug", "freeze", "stuck"]):
        category = "Bug"

    elif any(x in text for x in ["ad", "ads", "advertisement"]):
        category = "Ads"

    elif any(x in text for x in ["hard", "difficult", "impossible"]):
        category = "Difficulty"

    elif any(x in text for x in ["level", "more levels"]):
        category = "Levels"

    elif any(x in text for x in ["feature", "add", "wish"]):
        category = "Feature Request"

    else:
        category = "General"

    rows_to_add.append([
        platform,
        app_name,
        review_id,
        rating,
        sentiment,
        category
    ])

if rows_to_add:
    analysis_sheet.append_rows(rows_to_add)

print(f"Added {len(rows_to_add)} analysis rows")