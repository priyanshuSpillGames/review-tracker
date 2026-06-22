import os
import json
import tempfile
import gspread
from collections import defaultdict
from datetime import datetime
from flask import Flask, render_template, jsonify, redirect, url_for

from google.oauth2.service_account import Credentials

app = Flask(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

SHEET_NAME = "Game Reviews"

# ─── Cache ────────────────────────────────────────────────────────────────────
_cache = {
    "data": None,
    "last_updated": None,
}


def get_credentials():
    if os.path.exists("service_account.json"):
        return Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    else:
        service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            json.dump(service_account_info, f)
            temp_json = f.name
        return Credentials.from_service_account_file(temp_json, scopes=SCOPES)


def fetch_data():
    """Fetch and aggregate all data from Google Sheets."""
    credentials = get_credentials()
    gc = gspread.authorize(credentials)
    spreadsheet = gc.open(SHEET_NAME)

    reviews_sheet = spreadsheet.worksheet("Reviews")
    analysis_sheet = spreadsheet.worksheet("Review Analysis")

    reviews_data = reviews_sheet.get_all_values()
    analysis_data = analysis_sheet.get_all_values()

    # ── Parse Reviews ──────────────────────────────────────────────────────────
    reviews_rows = []
    for row in reviews_data[1:]:
        if len(row) < 8:
            continue
        platform    = row[0].strip()
        app_name    = row[1].strip()
        review_id   = row[4].strip()
        rating_raw  = row[5].strip()
        review_text = row[6].strip()
        date_raw    = row[7].strip()

        try:
            rating = float(rating_raw)
        except ValueError:
            rating = 0.0

        month_key = ""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(date_raw[:len(fmt)], fmt)
                month_key = dt.strftime("%Y-%m")
                break
            except Exception:
                pass
        if not month_key and len(date_raw) >= 7:
            month_key = date_raw[:7]

        reviews_rows.append({
            "platform":    platform,
            "app_name":    app_name,
            "review_id":   review_id,
            "rating":      rating,
            "review_text": review_text,
            "month":       month_key,
        })

    # ── Parse Analysis ─────────────────────────────────────────────────────────
    analysis_map = {}
    for row in analysis_data[1:]:
        if len(row) < 6:
            continue
        review_id = row[2].strip()
        sentiment = row[4].strip()
        category  = row[5].strip()
        analysis_map[review_id] = {"sentiment": sentiment, "category": category}

    # ── Merge ──────────────────────────────────────────────────────────────────
    for r in reviews_rows:
        info = analysis_map.get(r["review_id"], {})
        r["sentiment"] = info.get("sentiment", "Unknown")
        r["category"]  = info.get("category", "Unknown")

    # ── Aggregate ──────────────────────────────────────────────────────────────
    def aggregate(rows):
        total  = len(rows)
        ratings = [r["rating"] for r in rows if r["rating"] > 0]
        avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0

        rating_dist   = defaultdict(int)
        sentiment_dist = defaultdict(int)
        category_dist  = defaultdict(int)
        platform_dist  = defaultdict(int)
        monthly        = defaultdict(int)

        for r in rows:
            star = int(r["rating"])
            if 1 <= star <= 5:
                rating_dist[star] += 1
            sentiment_dist[r["sentiment"]] += 1
            category_dist[r["category"]]   += 1
            platform_dist[r["platform"]]   += 1
            if r["month"]:
                monthly[r["month"]] += 1

        return {
            "total":          total,
            "avg_rating":     avg_rating,
            "rating_dist":    dict(rating_dist),
            "sentiment_dist": dict(sentiment_dist),
            "category_dist":  dict(category_dist),
            "platform_dist":  dict(platform_dist),
            "monthly":        dict(sorted(monthly.items())),
        }

    overall = aggregate(reviews_rows)
    games   = sorted(set(r["app_name"] for r in reviews_rows))

    per_game = {}
    recent_reviews = {}
    for game in games:
        game_rows = [r for r in reviews_rows if r["app_name"] == game]
        per_game[game] = aggregate(game_rows)
        recent_reviews[game] = sorted(game_rows, key=lambda x: x["month"], reverse=True)[:15]

    # ── Pre-compute chart data for Jinja2 ─────────────────────────────────────
    def chart_data(agg):
        cats_sorted = sorted(agg["category_dist"].keys())
        platforms_sorted = sorted(agg["platform_dist"].keys())
        return {
            "rating_dist":    [agg["rating_dist"].get(s, 0) for s in range(1, 6)],
            "sentiment_dist": [agg["sentiment_dist"].get(s, 0) for s in ["Positive", "Neutral", "Negative", "Unknown"]],
            "category_labels": cats_sorted,
            "category_values": [agg["category_dist"][c] for c in cats_sorted],
            "platform_labels": platforms_sorted,
            "platform_values": [agg["platform_dist"][p] for p in platforms_sorted],
            "monthly_labels":  list(agg["monthly"].keys()),
            "monthly_values":  list(agg["monthly"].values()),
        }

    overall_chart = chart_data(overall)
    per_game_chart = {game: chart_data(per_game[game]) for game in games}

    # Game comparison arrays
    game_totals   = [per_game[g]["total"] for g in games]
    game_avgs     = [per_game[g]["avg_rating"] for g in games]
    game_positive = [per_game[g]["sentiment_dist"].get("Positive", 0) for g in games]
    game_negative = [per_game[g]["sentiment_dist"].get("Negative", 0) for g in games]

    return {
        "overall":        overall,
        "games":          games,
        "per_game":       per_game,
        "recent_reviews": recent_reviews,
        "overall_chart":  overall_chart,
        "per_game_chart": per_game_chart,
        "game_totals":    game_totals,
        "game_avgs":      game_avgs,
        "game_positive":  game_positive,
        "game_negative":  game_negative,
        "last_updated":   datetime.now().strftime("%B %d, %Y at %I:%M %p"),
    }


def get_cached_data(force_refresh=False):
    if force_refresh or _cache["data"] is None:
        _cache["data"] = fetch_data()
        _cache["last_updated"] = datetime.now()
    return _cache["data"]


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    data = get_cached_data()
    return render_template("dashboard.html", **data, active_game=None)


@app.route("/refresh")
def refresh():
    get_cached_data(force_refresh=True)
    return redirect(url_for("index"))


@app.route("/game/<game_name>")
def game_detail(game_name):
    data = get_cached_data()
    if game_name not in data["per_game"]:
        return redirect(url_for("index"))
    return render_template("dashboard.html", **data, active_game=game_name)


@app.route("/api/data")
def api_data():
    data = get_cached_data()
    return jsonify({
        "overall":    data["overall"],
        "games":      data["games"],
        "per_game":   data["per_game"],
        "last_updated": data["last_updated"],
    })


@app.route("/api/refresh")
def api_refresh():
    data = get_cached_data(force_refresh=True)
    return jsonify({"status": "ok", "last_updated": data["last_updated"]})


if __name__ == "__main__":
    print("Starting Game Reviews Dashboard...")
    print("Loading data from Google Sheets...")
    get_cached_data()
    print(f"Dashboard ready at http://localhost:5001")
    app.run(debug=True, host="0.0.0.0", port=5001)
