import gspread
import os
import json
import tempfile
from google.oauth2.service_account import Credentials
from google_play_scraper import reviews, Sort

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SHEET_NAME = "Game Reviews"

if os.path.exists("service_account.json"):
    print("Using local service account file")

    credentials = Credentials.from_service_account_file(
        "service_account.json",
        scopes=SCOPES
    )

else:
    print("Using GitHub Secret")

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

sheet = gc.open(SHEET_NAME).sheet1

GAMES = {
    "com.spill.sticker.color.book" : "Sticker",
    "com.spill.math.puzzle.games.crossmath.number.free" : "Zmc",
    "com.spill.bird.rescue.jam.sort.puzzle" : "Dragon Rescue",
    "com.spill.grill.master.sort.food.games.cooking.match.puzzle" : "Grill Sort",
    "com.spill.cozy.finds.hidden.objects" : "Hidden Objects"
}



# Create headers if sheet is empty
if not sheet.cell(1, 1).value:
    sheet.append_row([
        "App",
        "ReviewId",
        "Rating",
        "User",
        "Comment",
        "Date"
    ])

# Existing review IDs already in sheet
existing_ids = set(sheet.col_values(4))

print(f"Found {len(existing_ids)} existing reviews in sheet")

# ==========================
# FETCH REVIEWS
# ==========================

for package_name, app_name in GAMES.items():

    print(f"\n{'=' * 50}")
    print(f"Fetching reviews for {package_name}")
    print(f"{'=' * 50}")

    all_reviews = []
    seen_review_ids = set()

    continuation_token = None
    page_number = 1

    while True:

        try:
            batch, continuation_token = reviews(
                package_name,
                lang="en",
                country="us",
                sort=Sort.NEWEST,
                count=200,
                continuation_token=continuation_token
            )

        except Exception as e:
            print(f"Error while fetching reviews: {e}")
            break

        if not batch:
            print("No reviews returned.")
            break

        newly_found = 0

        for review in batch:

            review_id = review["reviewId"]

            if review_id not in seen_review_ids:
                seen_review_ids.add(review_id)
                all_reviews.append(review)
                newly_found += 1

        print(
            f"Page {page_number} | "
            f"Batch: {len(batch)} | "
            f"New Unique: {newly_found} | "
            f"Total Unique: {len(all_reviews)}"
        )

        page_number += 1

        # Stop if scraper starts repeating pages
        if newly_found == 0:
            print("Detected duplicate page. Stopping.")
            break

        # Stop if no more pages
        if continuation_token is None:
            print("Reached last page.")
            break

    print(f"\nTotal unique reviews fetched: {len(all_reviews)}")

    # ==========================
    # WRITE TO SHEET
    # ==========================

    rows_to_add = []

    for review in all_reviews:

        review_id = review["reviewId"]

        if review_id in existing_ids:
            continue

        rows_to_add.append([
            "Android",
            app_name,
            package_name,
            review_id,
            review.get("userName", ""),
            review.get("score", ""),
            review.get("content", ""),
            str(review.get("at", ""))
        ])

        existing_ids.add(review_id)

    if rows_to_add:

        print(f"Adding {len(rows_to_add)} new reviews to sheet...")

        sheet.append_rows(
            rows_to_add,
            value_input_option="RAW"
        )

        print("Done.")

    else:
        print("No new reviews found.")

print("\nFinished.")