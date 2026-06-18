import gspread
import os
import json
import tempfile
import re
import requests
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

spreadsheet = gc.open(SHEET_NAME)

apps_sheet = spreadsheet.worksheet("Apps")
reviews_sheet = spreadsheet.worksheet("Reviews")

apps = apps_sheet.get_all_records()

# ==========================
# ENSURE HEADERS EXIST
# ==========================

HEADERS = ["Platform", "App Name", "Identifier", "User Name", "Review ID", "Rating", "Review", "Date"]

first_row = reviews_sheet.row_values(1)
if first_row != HEADERS:
    reviews_sheet.clear()
    reviews_sheet.append_row(HEADERS)
    print("Headers written to Reviews sheet.")

# Existing review IDs already in sheet (now in column 5)
existing_ids = set(reviews_sheet.col_values(5))

# ==========================
# FETCH iOS TOKEN
# ==========================

def get_ios_token():
    """Extract JWT bearer token from Apple's App Store JS bundle."""
    try:
        page_resp = requests.get(
            "https://apps.apple.com/us/app/id",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"},
            timeout=30
        )
        js_urls = re.findall(r'src="(/assets/index[^"]+\.js)"', page_resp.text)
        if not js_urls:
            # Fallback: try any index JS
            js_urls = re.findall(r'src="(/assets/[^"]+\.js)"', page_resp.text)

        for js_path in js_urls[:5]:
            js_resp = requests.get(
                f"https://apps.apple.com{js_path}",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"},
                timeout=30
            )
            token_match = re.search(
                r'(eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)',
                js_resp.text
            )
            if token_match:
                return token_match.group(1)
    except Exception as e:
        print(f"Token fetch error: {e}")
    return None


def fetch_ios_reviews_for_app(app_id, token, countries):
    """Fetch all written reviews for an iOS app across multiple countries."""
    all_reviews = {}  # review_id -> review dict (deduplicate across countries)

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Origin": "https://apps.apple.com",
        "Referer": "https://apps.apple.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
    }

    for country in countries:
        offset = 0
        country_count = 0

        while True:
            params = {
                "l": "en-us",
                "offset": str(offset),
                "limit": "20",
                "platform": "web",
                "additionalPlatforms": "appletv,ipad,iphone,mac",
            }
            try:
                resp = requests.get(
                    f"https://amp-api-edge.apps.apple.com/v1/catalog/{country}/apps/{app_id}/reviews",
                    headers=headers,
                    params=params,
                    timeout=30
                )

                if resp.status_code != 200:
                    break

                data = resp.json()
                batch = data.get("data", [])

                if not batch:
                    break

                for item in batch:
                    review_id = item.get("id", "")
                    if review_id and review_id not in all_reviews:
                        attrs = item.get("attributes", {})
                        all_reviews[review_id] = {
                            "id": review_id,
                            "userName": attrs.get("userName", ""),
                            "rating": attrs.get("rating", ""),
                            "review": attrs.get("review", ""),
                            "title": attrs.get("title", ""),
                            "date": attrs.get("date", ""),
                            "country": country,
                        }
                        country_count += 1

                next_url = data.get("next")
                if not next_url:
                    break

                offset_match = re.search(r"offset=(\d+)", next_url)
                if offset_match:
                    offset = int(offset_match.group(1))
                else:
                    break

            except Exception as e:
                print(f"  Error fetching {country} at offset {offset}: {e}")
                break

        if country_count > 0:
            print(f"  {country.upper()}: {country_count} new unique reviews")

    return list(all_reviews.values())


# Countries to fetch iOS reviews from
IOS_COUNTRIES = [
    "us", "gb", "ca", "au", "in", "de", "fr", "it", "es", "nl",
    "jp", "kr", "br", "mx", "ru", "tr", "sa", "ae", "id", "ph",
    "sg", "my", "th", "vn", "pk", "ng", "za", "ar", "cl", "co",
    "se", "no", "dk", "fi", "pl", "cz", "hu", "ro", "pt", "be",
    "ch", "at", "nz", "ie", "hk", "tw", "eg", "il", "gr", "ua",
]

print("\nFetching iOS bearer token...")
ios_token = get_ios_token()

if ios_token:
    print(f"Token obtained successfully.")
else:
    print("WARNING: Could not obtain iOS token. iOS reviews will be skipped.")

for app in apps:

    platform = app["Platform"].strip()
    app_name = app["App Name"].strip()
    identifier = str(app["Identifier"]).strip()

    if platform != "iOS":
        continue

    if not ios_token:
        print(f"Skipping {app_name} - no iOS token available.")
        continue

    print(f"\nFetching iOS reviews for {app_name} (App ID: {identifier})")

    try:
        fetched = fetch_ios_reviews_for_app(identifier, ios_token, IOS_COUNTRIES)
        print(f"Total unique reviews fetched across all countries: {len(fetched)}")

        rows_to_add = []

        for r in fetched:
            review_id = r["id"]

            if review_id in existing_ids:
                continue

            rows_to_add.append([
                "iOS",
                app_name,
                identifier,
                r.get("userName", ""),
                review_id,
                r.get("rating", ""),
                r.get("review", ""),
                r.get("date", ""),
            ])

            existing_ids.add(review_id)

        if rows_to_add:
            print(f"Adding {len(rows_to_add)} new iOS reviews to sheet...")
            reviews_sheet.append_rows(rows_to_add, value_input_option="RAW")
            print("Done.")
        else:
            print("No new iOS reviews to add.")

    except Exception as e:
        print(f"iOS fetch error for {app_name}: {e}")


print(f"Found {len(existing_ids)} existing reviews in sheet")

# ==========================
# FETCH REVIEWS
# ==========================

for app in apps:

    platform = app["Platform"].strip()
    app_name = app["App Name"].strip()
    identifier = str(app["Identifier"]).strip()

    if platform != "Android":
        continue

    package_name = identifier

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
            review.get("userName", ""),
            review_id,
            review.get("score", ""),
            review.get("content", ""),
            str(review.get("at", ""))
        ])

        existing_ids.add(review_id)

    if rows_to_add:

        print(f"Adding {len(rows_to_add)} new reviews to sheet...")

        reviews_sheet.append_rows(
            rows_to_add,
            value_input_option="RAW"
        )

        print("Done.")

    else:
        print("No new reviews found.")

# ==========================
# SORT SHEET BY DATE (NEWEST FIRST)
# ==========================

print("\nSorting reviews by date (newest first)...")
reviews_sheet.sort((8, "des"))
print("Sorted.")

print("\nFinished.")
