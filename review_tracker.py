import os
import json
import tempfile

from google.oauth2.service_account import Credentials
from google_play_scraper import reviews, Sort

PACKAGE_NAMES = [
     "com.spill.sticker.color.book",
                "com.spill.math.puzzle.games.crossmath.number.free",
                "com.spill.bird.rescue.jam.sort.puzzle",
                "com.spill.grill.master.sort.food.games.cooking.match.puzzle",
                "com.spill.cozy.finds.hidden.objects"
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

service_account_info = json.loads(
    os.environ["GOOGLE_SERVICE_ACCOUNT"]
)

with tempfile.NamedTemporaryFile(
    mode="w",
    delete=False
) as f:
    json.dump(service_account_info, f)
    temp_path = f.name

credentials = Credentials.from_service_account_file(
    temp_path,
    scopes=SCOPES
)


gc = gspread.authorize(credentials)

sheet = gc.open("Game Reviews").sheet1

if sheet.row_count == 1:
    sheet.append_row([
        "App",
        "ReviewId",
        "Rating",
        "User",
        "Comment",
        "Date"
    ])

existing_ids = set(sheet.col_values(2))

for package_name in PACKAGE_NAMES:

    result, _ = reviews(
        package_name,
        lang="en",
        country="us",
        sort=Sort.NEWEST,
        count=100
    )

    for review in result:

        review_id = review["reviewId"]

        if review_id in existing_ids:
            continue

        sheet.append_row([
            package_name,
            review_id,
            review["score"],
            review["userName"],
            review["content"],
            str(review["at"])
        ])

        print("Added", review_id)