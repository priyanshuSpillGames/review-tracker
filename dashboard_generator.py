import os
import json
import tempfile
import gspread
from collections import defaultdict
from datetime import datetime

from google.oauth2.service_account import Credentials

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
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
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

print("Fetching data from Google Sheets...")
reviews_data = reviews_sheet.get_all_values()
analysis_data = analysis_sheet.get_all_values()

# ─── Parse Reviews ───────────────────────────────────────────────────────────
# Headers: Platform, App Name, Identifier, User Name, Review ID, Rating, Review, Date
reviews_rows = []
for row in reviews_data[1:]:
    if len(row) < 8:
        continue
    platform  = row[0].strip()
    app_name  = row[1].strip()
    review_id = row[4].strip()
    rating_raw = row[5].strip()
    review_text = row[6].strip()
    date_raw  = row[7].strip()

    try:
        rating = float(rating_raw)
    except ValueError:
        rating = 0.0

    # Normalise date to YYYY-MM
    month_key = ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(date_raw[:19], fmt[:len(date_raw[:19])])
            month_key = dt.strftime("%Y-%m")
            break
        except Exception:
            pass
    if not month_key and len(date_raw) >= 7:
        month_key = date_raw[:7]

    reviews_rows.append({
        "platform": platform,
        "app_name": app_name,
        "review_id": review_id,
        "rating": rating,
        "review_text": review_text,
        "month": month_key,
    })

# ─── Parse Analysis ───────────────────────────────────────────────────────────
# Headers: Platform, App Name, Review ID, Rating, Sentiment, Category
analysis_map = {}  # review_id -> {sentiment, category}
for row in analysis_data[1:]:
    if len(row) < 6:
        continue
    review_id = row[2].strip()
    sentiment = row[4].strip()
    category  = row[5].strip()
    analysis_map[review_id] = {"sentiment": sentiment, "category": category}

# ─── Merge ────────────────────────────────────────────────────────────────────
for r in reviews_rows:
    info = analysis_map.get(r["review_id"], {})
    r["sentiment"] = info.get("sentiment", "Unknown")
    r["category"]  = info.get("category", "Unknown")

# ─── Aggregate helpers ────────────────────────────────────────────────────────
def aggregate(rows):
    total = len(rows)
    ratings = [r["rating"] for r in rows if r["rating"] > 0]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0

    rating_dist = defaultdict(int)
    for r in rows:
        star = int(r["rating"])
        if 1 <= star <= 5:
            rating_dist[star] += 1

    sentiment_dist = defaultdict(int)
    for r in rows:
        sentiment_dist[r["sentiment"]] += 1

    category_dist = defaultdict(int)
    for r in rows:
        category_dist[r["category"]] += 1

    platform_dist = defaultdict(int)
    for r in rows:
        platform_dist[r["platform"]] += 1

    monthly = defaultdict(int)
    for r in rows:
        if r["month"]:
            monthly[r["month"]] += 1

    return {
        "total": total,
        "avg_rating": avg_rating,
        "rating_dist": dict(rating_dist),
        "sentiment_dist": dict(sentiment_dist),
        "category_dist": dict(category_dist),
        "platform_dist": dict(platform_dist),
        "monthly": dict(sorted(monthly.items())),
    }

# Overall
overall = aggregate(reviews_rows)

# Per game
games = sorted(set(r["app_name"] for r in reviews_rows))
per_game = {}
for game in games:
    game_rows = [r for r in reviews_rows if r["app_name"] == game]
    per_game[game] = aggregate(game_rows)

# Recent reviews per game (last 10)
recent_reviews = {}
for game in games:
    game_rows = [r for r in reviews_rows if r["app_name"] == game]
    recent = sorted(game_rows, key=lambda x: x["month"], reverse=True)[:10]
    recent_reviews[game] = recent

print(f"Total reviews: {overall['total']}")
print(f"Games found: {games}")

# ─── Build HTML ───────────────────────────────────────────────────────────────
def safe_js(obj):
    return json.dumps(obj)

def rating_stars(rating):
    try:
        r = float(rating)
        full = int(r)
        half = 1 if (r - full) >= 0.5 else 0
        empty = 5 - full - half
        return "★" * full + ("½" if half else "") + "☆" * empty
    except Exception:
        return "—"

# Build game tabs HTML
game_tabs_html = ""
game_panels_html = ""

for i, game in enumerate(games):
    g = per_game[game]
    active_tab = "active" if i == 0 else ""
    active_panel = "active" if i == 0 else ""
    game_id = f"game_{i}"

    # Rating dist for chart
    rd = [g["rating_dist"].get(s, 0) for s in range(1, 6)]
    # Sentiment
    sentiments = ["Positive", "Neutral", "Negative", "Unknown"]
    sd = [g["sentiment_dist"].get(s, 0) for s in sentiments]
    # Category
    cats = sorted(g["category_dist"].keys())
    cd = [g["category_dist"][c] for c in cats]
    # Platform
    platforms = sorted(g["platform_dist"].keys())
    pd_vals = [g["platform_dist"][p] for p in platforms]
    # Monthly
    months = list(g["monthly"].keys())
    monthly_vals = list(g["monthly"].values())

    # Recent reviews table rows
    recent_rows_html = ""
    for rev in recent_reviews[game]:
        sentiment_class = rev["sentiment"].lower()
        recent_rows_html += f"""
        <tr>
            <td>{rev["platform"]}</td>
            <td>{"★" * int(rev["rating"])}</td>
            <td><span class="badge badge-{sentiment_class}">{rev["sentiment"]}</span></td>
            <td><span class="badge badge-category">{rev["category"]}</span></td>
            <td class="review-text">{rev["review_text"][:120]}{"..." if len(rev["review_text"]) > 120 else ""}</td>
            <td>{rev["month"]}</td>
        </tr>"""

    game_tabs_html += f'<button class="tab-btn {active_tab}" onclick="switchGame({i})">{game}</button>\n'

    game_panels_html += f"""
    <div class="game-panel {active_panel}" id="{game_id}">
        <div class="game-header">
            <h2>🎮 {game}</h2>
            <div class="game-stats-row">
                <div class="stat-card">
                    <div class="stat-number">{g["total"]}</div>
                    <div class="stat-label">Total Reviews</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{g["avg_rating"]}</div>
                    <div class="stat-label">Avg Rating</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{g["platform_dist"].get("Android", 0)}</div>
                    <div class="stat-label">Android</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{g["platform_dist"].get("iOS", 0)}</div>
                    <div class="stat-label">iOS</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{g["sentiment_dist"].get("Positive", 0)}</div>
                    <div class="stat-label">Positive</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{g["sentiment_dist"].get("Negative", 0)}</div>
                    <div class="stat-label">Negative</div>
                </div>
            </div>
        </div>

        <div class="charts-grid">
            <div class="chart-card">
                <h3>⭐ Rating Distribution</h3>
                <canvas id="ratingChart_{game_id}"></canvas>
            </div>
            <div class="chart-card">
                <h3>💬 Sentiment Breakdown</h3>
                <canvas id="sentimentChart_{game_id}"></canvas>
            </div>
            <div class="chart-card">
                <h3>🏷️ Category Breakdown</h3>
                <canvas id="categoryChart_{game_id}"></canvas>
            </div>
            <div class="chart-card">
                <h3>📅 Reviews Over Time</h3>
                <canvas id="monthlyChart_{game_id}"></canvas>
            </div>
        </div>

        <div class="table-card">
            <h3>📝 Recent Reviews</h3>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>Platform</th>
                            <th>Rating</th>
                            <th>Sentiment</th>
                            <th>Category</th>
                            <th>Review</th>
                            <th>Month</th>
                        </tr>
                    </thead>
                    <tbody>
                        {recent_rows_html}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
    (function() {{
        var rd = {safe_js(rd)};
        var sd = {safe_js(sd)};
        var cats = {safe_js(cats)};
        var cd = {safe_js(cd)};
        var months = {safe_js(months)};
        var mv = {safe_js(monthly_vals)};

        new Chart(document.getElementById('ratingChart_{game_id}'), {{
            type: 'bar',
            data: {{
                labels: ['1★','2★','3★','4★','5★'],
                datasets: [{{
                    label: 'Reviews',
                    data: rd,
                    backgroundColor: ['#ef4444','#f97316','#eab308','#84cc16','#22c55e'],
                    borderRadius: 6
                }}]
            }},
            options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
        }});

        new Chart(document.getElementById('sentimentChart_{game_id}'), {{
            type: 'doughnut',
            data: {{
                labels: ['Positive','Neutral','Negative','Unknown'],
                datasets: [{{
                    data: sd,
                    backgroundColor: ['#22c55e','#eab308','#ef4444','#94a3b8'],
                    borderWidth: 2,
                    borderColor: '#1e293b'
                }}]
            }},
            options: {{ responsive: true, plugins: {{ legend: {{ position: 'bottom' }} }} }}
        }});

        new Chart(document.getElementById('categoryChart_{game_id}'), {{
            type: 'bar',
            data: {{
                labels: cats,
                datasets: [{{
                    label: 'Reviews',
                    data: cd,
                    backgroundColor: '#6366f1',
                    borderRadius: 6
                }}]
            }},
            options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
        }});

        new Chart(document.getElementById('monthlyChart_{game_id}'), {{
            type: 'line',
            data: {{
                labels: months,
                datasets: [{{
                    label: 'Reviews',
                    data: mv,
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99,102,241,0.15)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 4
                }}]
            }},
            options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
        }});
    }})();
    </script>
"""

# Overall charts data
overall_rd = [overall["rating_dist"].get(s, 0) for s in range(1, 6)]
overall_sd = [overall["sentiment_dist"].get(s, 0) for s in ["Positive", "Neutral", "Negative", "Unknown"]]
overall_cats = sorted(overall["category_dist"].keys())
overall_cd = [overall["category_dist"][c] for c in overall_cats]
overall_months = list(overall["monthly"].keys())
overall_mv = list(overall["monthly"].values())
overall_platforms = sorted(overall["platform_dist"].keys())
overall_pv = [overall["platform_dist"][p] for p in overall_platforms]

# Game comparison data
game_names = list(per_game.keys())
game_totals = [per_game[g]["total"] for g in game_names]
game_avgs = [per_game[g]["avg_rating"] for g in game_names]
game_positive = [per_game[g]["sentiment_dist"].get("Positive", 0) for g in game_names]
game_negative = [per_game[g]["sentiment_dist"].get("Negative", 0) for g in game_names]

generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Game Reviews Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            min-height: 100vh;
        }}

        /* ── Header ── */
        .header {{
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border-bottom: 1px solid #334155;
            padding: 24px 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .header h1 {{
            font-size: 1.8rem;
            font-weight: 700;
            background: linear-gradient(90deg, #6366f1, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header .meta {{
            font-size: 0.8rem;
            color: #64748b;
        }}

        /* ── Nav ── */
        .nav {{
            background: #1e293b;
            border-bottom: 1px solid #334155;
            display: flex;
            gap: 4px;
            padding: 0 32px;
            overflow-x: auto;
        }}
        .nav-btn {{
            background: none;
            border: none;
            color: #94a3b8;
            padding: 16px 20px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 500;
            border-bottom: 3px solid transparent;
            white-space: nowrap;
            transition: all 0.2s;
        }}
        .nav-btn:hover {{ color: #e2e8f0; }}
        .nav-btn.active {{
            color: #6366f1;
            border-bottom-color: #6366f1;
        }}

        /* ── Sections ── */
        .section {{ display: none; padding: 32px; }}
        .section.active {{ display: block; }}

        /* ── Stat Cards ── */
        .stats-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }}
        .stat-card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            transition: transform 0.2s;
        }}
        .stat-card:hover {{ transform: translateY(-2px); }}
        .stat-number {{
            font-size: 2rem;
            font-weight: 700;
            color: #6366f1;
            line-height: 1;
        }}
        .stat-label {{
            font-size: 0.8rem;
            color: #64748b;
            margin-top: 6px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        /* ── Charts Grid ── */
        .charts-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 20px;
            margin-bottom: 28px;
        }}
        .chart-card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 20px;
        }}
        .chart-card h3 {{
            font-size: 0.95rem;
            font-weight: 600;
            color: #94a3b8;
            margin-bottom: 16px;
        }}

        /* ── Table ── */
        .table-card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 28px;
        }}
        .table-card h3 {{
            font-size: 0.95rem;
            font-weight: 600;
            color: #94a3b8;
            margin-bottom: 16px;
        }}
        .table-wrapper {{ overflow-x: auto; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }}
        th {{
            text-align: left;
            padding: 10px 12px;
            background: #0f172a;
            color: #64748b;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
        }}
        td {{
            padding: 10px 12px;
            border-top: 1px solid #334155;
            vertical-align: top;
        }}
        tr:hover td {{ background: #0f172a; }}
        .review-text {{ max-width: 320px; color: #94a3b8; line-height: 1.4; }}

        /* ── Badges ── */
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-positive {{ background: rgba(34,197,94,0.15); color: #22c55e; }}
        .badge-neutral  {{ background: rgba(234,179,8,0.15);  color: #eab308; }}
        .badge-negative {{ background: rgba(239,68,68,0.15);  color: #ef4444; }}
        .badge-unknown  {{ background: rgba(148,163,184,0.15); color: #94a3b8; }}
        .badge-category {{ background: rgba(99,102,241,0.15); color: #a78bfa; }}

        /* ── Game Tabs ── */
        .game-tabs {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 24px;
        }}
        .tab-btn {{
            background: #1e293b;
            border: 1px solid #334155;
            color: #94a3b8;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.85rem;
            font-weight: 500;
            transition: all 0.2s;
        }}
        .tab-btn:hover {{ border-color: #6366f1; color: #e2e8f0; }}
        .tab-btn.active {{
            background: #6366f1;
            border-color: #6366f1;
            color: #fff;
        }}
        .game-panel {{ display: none; }}
        .game-panel.active {{ display: block; }}
        .game-header {{ margin-bottom: 20px; }}
        .game-header h2 {{ font-size: 1.4rem; font-weight: 700; margin-bottom: 16px; }}
        .game-stats-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 12px;
        }}

        /* ── Comparison Table ── */
        .comparison-table td:first-child {{ font-weight: 600; color: #e2e8f0; }}

        /* ── Responsive ── */
        @media (max-width: 640px) {{
            .header {{ padding: 16px; }}
            .section {{ padding: 16px; }}
            .nav {{ padding: 0 16px; }}
            .charts-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>

<div class="header">
    <div>
        <h1>🎮 Game Reviews Dashboard</h1>
        <div class="meta">Last updated: {generated_at}</div>
    </div>
    <div class="meta">{overall["total"]} total reviews · {len(games)} games</div>
</div>

<nav class="nav">
    <button class="nav-btn active" onclick="switchSection('overview', this)">📊 Overview</button>
    <button class="nav-btn" onclick="switchSection('games', this)">🎮 Per Game</button>
    <button class="nav-btn" onclick="switchSection('comparison', this)">📈 Comparison</button>
</nav>

<!-- ═══════════════════════════════════════════════════════════════════════════
     OVERVIEW SECTION
════════════════════════════════════════════════════════════════════════════ -->
<div class="section active" id="section-overview">

    <div class="stats-row">
        <div class="stat-card">
            <div class="stat-number">{overall["total"]}</div>
            <div class="stat-label">Total Reviews</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{overall["avg_rating"]}</div>
            <div class="stat-label">Avg Rating</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{len(games)}</div>
            <div class="stat-label">Games Tracked</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{overall["platform_dist"].get("Android", 0)}</div>
            <div class="stat-label">Android Reviews</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{overall["platform_dist"].get("iOS", 0)}</div>
            <div class="stat-label">iOS Reviews</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{overall["sentiment_dist"].get("Positive", 0)}</div>
            <div class="stat-label">Positive</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{overall["sentiment_dist"].get("Negative", 0)}</div>
            <div class="stat-label">Negative</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{overall["sentiment_dist"].get("Neutral", 0)}</div>
            <div class="stat-label">Neutral</div>
        </div>
    </div>

    <div class="charts-grid">
        <div class="chart-card">
            <h3>⭐ Overall Rating Distribution</h3>
            <canvas id="overallRatingChart"></canvas>
        </div>
        <div class="chart-card">
            <h3>💬 Overall Sentiment</h3>
            <canvas id="overallSentimentChart"></canvas>
        </div>
        <div class="chart-card">
            <h3>📱 Platform Split</h3>
            <canvas id="overallPlatformChart"></canvas>
        </div>
        <div class="chart-card">
            <h3>🏷️ Category Breakdown</h3>
            <canvas id="overallCategoryChart"></canvas>
        </div>
    </div>

    <div class="chart-card" style="margin-bottom:28px;">
        <h3>📅 Reviews Over Time (All Games)</h3>
        <canvas id="overallMonthlyChart"></canvas>
    </div>

</div>

<!-- ═══════════════════════════════════════════════════════════════════════════
     PER GAME SECTION
════════════════════════════════════════════════════════════════════════════ -->
<div class="section" id="section-games">
    <div class="game-tabs">
        {game_tabs_html}
    </div>
    {game_panels_html}
</div>

<!-- ═══════════════════════════════════════════════════════════════════════════
     COMPARISON SECTION
════════════════════════════════════════════════════════════════════════════ -->
<div class="section" id="section-comparison">

    <div class="charts-grid">
        <div class="chart-card">
            <h3>📊 Total Reviews by Game</h3>
            <canvas id="compTotalChart"></canvas>
        </div>
        <div class="chart-card">
            <h3>⭐ Average Rating by Game</h3>
            <canvas id="compAvgChart"></canvas>
        </div>
        <div class="chart-card">
            <h3>😊 Positive Reviews by Game</h3>
            <canvas id="compPositiveChart"></canvas>
        </div>
        <div class="chart-card">
            <h3>😠 Negative Reviews by Game</h3>
            <canvas id="compNegativeChart"></canvas>
        </div>
    </div>

    <div class="table-card">
        <h3>📋 Game Comparison Table</h3>
        <div class="table-wrapper">
            <table class="comparison-table">
                <thead>
                    <tr>
                        <th>Game</th>
                        <th>Total</th>
                        <th>Avg Rating</th>
                        <th>Android</th>
                        <th>iOS</th>
                        <th>Positive</th>
                        <th>Neutral</th>
                        <th>Negative</th>
                        <th>Top Category</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(
                        f"<tr>"
                        f"<td>{g}</td>"
                        f"<td>{per_game[g]['total']}</td>"
                        f"<td>{'★' * int(per_game[g]['avg_rating'])} {per_game[g]['avg_rating']}</td>"
                        f"<td>{per_game[g]['platform_dist'].get('Android', 0)}</td>"
                        f"<td>{per_game[g]['platform_dist'].get('iOS', 0)}</td>"
                        f"<td><span class='badge badge-positive'>{per_game[g]['sentiment_dist'].get('Positive', 0)}</span></td>"
                        f"<td><span class='badge badge-neutral'>{per_game[g]['sentiment_dist'].get('Neutral', 0)}</span></td>"
                        f"<td><span class='badge badge-negative'>{per_game[g]['sentiment_dist'].get('Negative', 0)}</span></td>"
                        f"<td><span class='badge badge-category'>{max(per_game[g]['category_dist'], key=per_game[g]['category_dist'].get) if per_game[g]['category_dist'] else '—'}</span></td>"
                        f"</tr>"
                        for g in games
                    )}
                </tbody>
            </table>
        </div>
    </div>

</div>

<script>
// ── Section navigation ──────────────────────────────────────────────────────
function switchSection(id, btn) {{
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('section-' + id).classList.add('active');
    btn.classList.add('active');
}}

// ── Game tab navigation ──────────────────────────────────────────────────────
function switchGame(idx) {{
    document.querySelectorAll('.game-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('game_' + idx).classList.add('active');
    document.querySelectorAll('.tab-btn')[idx].classList.add('active');
}}

// ── Overall Charts ───────────────────────────────────────────────────────────
new Chart(document.getElementById('overallRatingChart'), {{
    type: 'bar',
    data: {{
        labels: ['1★','2★','3★','4★','5★'],
        datasets: [{{
            label: 'Reviews',
            data: {safe_js(overall_rd)},
            backgroundColor: ['#ef4444','#f97316','#eab308','#84cc16','#22c55e'],
            borderRadius: 6
        }}]
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
}});

new Chart(document.getElementById('overallSentimentChart'), {{
    type: 'doughnut',
    data: {{
        labels: ['Positive','Neutral','Negative','Unknown'],
        datasets: [{{
            data: {safe_js(overall_sd)},
            backgroundColor: ['#22c55e','#eab308','#ef4444','#94a3b8'],
            borderWidth: 2,
            borderColor: '#1e293b'
        }}]
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ position: 'bottom' }} }} }}
}});

new Chart(document.getElementById('overallPlatformChart'), {{
    type: 'doughnut',
    data: {{
        labels: {safe_js(overall_platforms)},
        datasets: [{{
            data: {safe_js(overall_pv)},
            backgroundColor: ['#6366f1','#06b6d4','#f97316','#22c55e'],
            borderWidth: 2,
            borderColor: '#1e293b'
        }}]
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ position: 'bottom' }} }} }}
}});

new Chart(document.getElementById('overallCategoryChart'), {{
    type: 'bar',
    data: {{
        labels: {safe_js(overall_cats)},
        datasets: [{{
            label: 'Reviews',
            data: {safe_js(overall_cd)},
            backgroundColor: '#6366f1',
            borderRadius: 6
        }}]
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
}});

new Chart(document.getElementById('overallMonthlyChart'), {{
    type: 'line',
    data: {{
        labels: {safe_js(overall_months)},
        datasets: [{{
            label: 'Reviews',
            data: {safe_js(overall_mv)},
            borderColor: '#6366f1',
            backgroundColor: 'rgba(99,102,241,0.15)',
            fill: true,
            tension: 0.4,
            pointRadius: 4
        }}]
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
}});

// ── Comparison Charts ────────────────────────────────────────────────────────
new Chart(document.getElementById('compTotalChart'), {{
    type: 'bar',
    data: {{
        labels: {safe_js(game_names)},
        datasets: [{{
            label: 'Total Reviews',
            data: {safe_js(game_totals)},
            backgroundColor: '#6366f1',
            borderRadius: 6
        }}]
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
}});

new Chart(document.getElementById('compAvgChart'), {{
    type: 'bar',
    data: {{
        labels: {safe_js(game_names)},
        datasets: [{{
            label: 'Avg Rating',
            data: {safe_js(game_avgs)},
            backgroundColor: '#22c55e',
            borderRadius: 6
        }}]
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: false, min: 0, max: 5 }} }} }}
}});

new Chart(document.getElementById('compPositiveChart'), {{
    type: 'bar',
    data: {{
        labels: {safe_js(game_names)},
        datasets: [{{
            label: 'Positive',
            data: {safe_js(game_positive)},
            backgroundColor: '#22c55e',
            borderRadius: 6
        }}]
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
}});

new Chart(document.getElementById('compNegativeChart'), {{
    type: 'bar',
    data: {{
        labels: {safe_js(game_names)},
        datasets: [{{
            label: 'Negative',
            data: {safe_js(game_negative)},
            backgroundColor: '#ef4444',
            borderRadius: 6
        }}]
    }},
    options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
}});
</script>

</body>
</html>
"""

output_path = "dashboard.html"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nDashboard generated: {output_path}")
print(f"Total reviews: {overall['total']}")
print(f"Games: {', '.join(games)}")
