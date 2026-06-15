import gspread
from google.oauth2.service_account import Credentials
from google_play_scraper import reviews, Sort

PACKAGE_NAMES = [
    
]

import gspread
from google.oauth2.service_account import Credentials
from google_play_scraper import reviews, Sort

# ==========================
# CONFIGURATION
# ==========================

PACKAGE_NAMES = [
    "com.spill.sticker.color.book",
    "com.spill.math.puzzle.games.crossmath.number.free",
    "com.spill.bird.rescue.jam.sort.puzzle",
    "com.spill.grill.master.sort.food.games.cooking.match.puzzle",
    "com.spill.cozy.finds.hidden.objects"
]

SHEET_NAME = "Game Reviews"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# ==========================
# GOOGLE SHEETS SETUP
# ==========================

credentials = Credentials.from_service_account_file(
    "service_account.json",
    scopes=SCOPES
)

gc = gspread.authorize(credentials)

sheet = gc.open(SHEET_NAME).sheet1

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
existing_ids = set(sheet.col_values(2))

print(f"Found {len(existing_ids)} existing reviews in sheet")

# ==========================
# FETCH REVIEWS
# ==========================

for package_name in PACKAGE_NAMES:

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
            package_name,
            review_id,
            review.get("score", ""),
            review.get("userName", ""),
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