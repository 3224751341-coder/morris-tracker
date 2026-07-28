#!/usr/bin/env python3
"""Morris 推文追踪 · 每天10:00抓取前一天内容"""
import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(PROJECT_DIR, "data", "tweets.json")
HTML_FILE = os.path.join(PROJECT_DIR, "index.html")
USERNAME = "morris_lt"
BJ = timezone(timedelta(hours=8))

def fetch_tweets(limit=50):
    """抓取用户推文 — 三层兜底：opencli → Nitter RSS → Playwright"""
    # Tier 1: opencli (local Mac with Chrome extension)
    try:
        result = subprocess.run(
            ["opencli", "twitter", "tweets", USERNAME, "--limit", str(limit), "-f", "json",
             "--window", "background", "--keep-tab", "false"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                print(f"opencli 抓取成功: {len(data)} 条")
                return data
    except:
        pass

    # Tier 2: Nitter RSS (cloud, no auth needed)
    import urllib.request, html as html_mod, re
    nitter_url = f"https://nitter.net/{USERNAME}/rss"
    print(f"Nitter RSS: {nitter_url}")
    try:
        req = urllib.request.Request(nitter_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read().decode("utf-8")
        items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
        if items:
            tweets = []
            for item in items:
                m_title = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
                m_date = re.search(r"<pubDate>(.*?)</pubDate>", item)
                m_link = re.search(r"<link>(.*?)</link>", item)
                if m_title and m_date and m_link:
                    tid_m = re.search(r"/status/(\d+)", m_link.group(1))
                    tweets.append({
                        "id": tid_m.group(1) if tid_m else "",
                        "text": html_mod.unescape(m_title.group(1)).strip(),
                        "created_at": m_date.group(1).strip(),
                        "likes": 0, "retweets": 0, "replies": 0, "views": 0,
                        "url": f"https://x.com/{USERNAME}/status/{tid_m.group(1)}" if tid_m else "",
                        "captured_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M"),
                    })
            print(f"Nitter RSS 抓取成功: {len(tweets)} 条")
            return tweets
        print("Nitter RSS 无内容")
    except Exception as e:
        print(f"Nitter RSS 失败: {e}")

    # Tier 3: Playwright headless (last resort, needs cookies)
    print("尝试 Playwright 浏览器抓取...")
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(PROJECT_DIR, "fetch_x.py"), USERNAME, str(limit)],
            capture_output=True, text=True, timeout=90
        )
        if result.stderr:
            print(f"Playwright 日志:\n{result.stderr[:500]}")
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if isinstance(data, list):
                print(f"Playwright 抓取成功: {len(data)} 条")
                return data
    except Exception as e:
        print(f"Playwright 异常: {e}")

    return []

def load_db():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"tweets": {}, "last_fetch": None}

def save_db(db):
    db["last_fetch"] = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    with open(DATA_FILE, "w") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def main():
    print(f"[{datetime.now(BJ).strftime('%Y-%m-%d %H:%M')}] 抓取 @{USERNAME}...")
    tweets = fetch_tweets(50)
    if not tweets:
        print("无新推文")
        return

    db = load_db()
    new_count = 0
    for t in tweets:
        tid = str(t.get("id", ""))
        if tid and tid not in db["tweets"]:
            # 过滤无效推文：无文本或无日期的不入库
            text = (t.get("text") or "").strip()
            date = t.get("created_at") or ""
            if not text or not date:
                continue
            t["captured_at"] = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
            db["tweets"][tid] = t
            new_count += 1

    save_db(db)
    print(f"新增 {new_count} 条，共 {len(db['tweets'])} 条")
    generate_html(db)
    deploy()

def parse_date(date_str):
    """解析 Twitter 日期格式 (可能有或没有年份)"""
    if not date_str:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%a %b %d %H:%M:%S %z"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            # 无年份时用当前年份
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now().year)
            return dt
        except:
            continue
    return datetime(2000, 1, 1, tzinfo=timezone.utc)

def generate_html(db):
    tweets = sorted(db["tweets"].values(), key=lambda t: parse_date(t.get("created_at", "")), reverse=True)

    # Group by YYYY-MM-DD (properly parsed, not raw string prefix)
    by_date = {}
    for t in tweets:
        dt = parse_date(t.get("created_at", ""))
        date_key = dt.strftime("%Y-%m-%d")
        if date_key not in by_date:
            by_date[date_key] = {"dt": dt, "tweets": []}
        by_date[date_key]["tweets"].append(t)

    now_str = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    total = len(tweets)
    days = len(by_date)

    # Sort dates chronologically (newest first)
    sorted_dates = sorted(by_date.keys(), reverse=True)

    # Build sidebar items
    sidebar_items = ""
    for i, date_key in enumerate(sorted_dates):
        group = by_date[date_key]
        dt = group["dt"]
        count = len(group["tweets"])
        weekday = ["日","一","二","三","四","五","六"][int(dt.strftime("%w"))]
        date_display = f'{dt.strftime("%m月%d日")} <span class="wk">周{weekday}</span>'
        active = "active" if i == 0 else ""
        sidebar_items += f"""<div class="date-item {active}" data-date="{date_key}" onclick="switchDate('{date_key}')">
            <span class="date-label">{date_display}</span>
            <span class="date-count">{count}</span>
        </div>"""

    # Build content panels
    content_panels = ""
    for i, date_key in enumerate(sorted_dates):
        group = by_date[date_key]
        active = "active" if i == 0 else ""
        cards = ""
        for t in group["tweets"]:
            text = (t.get("text", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            import re
            text = re.sub(r'(https?://\S+)', r'<a href="\1" target="_blank" rel="noopener">\1</a>', text)
            likes = t.get("likes", 0) or 0
            retweets = t.get("retweets", 0) or 0
            replies = t.get("replies", 0) or 0
            views = t.get("views", 0) or 0
            tid = t.get("id", "")
            tweet_url = f"https://x.com/{USERNAME}/status/{tid}" if tid else "#"
            time_str = (t.get("created_at", "")[11:16] or "") if t.get("created_at") else ""
            cards += f"""<div class="tweet-card">
                <div class="tweet-time">{time_str}</div>
                <div class="tweet-text">{text}</div>
                <div class="tweet-stats">
                    <span class="stat">❤ {fmt_num(likes)}</span>
                    <span class="stat">⇄ {fmt_num(retweets)}</span>
                    <span class="stat">✎ {fmt_num(replies)}</span>
                    <span class="stat">◎ {fmt_num(views)}</span>
                    <a href="{tweet_url}" target="_blank" rel="noopener" class="tweet-link">原文 →</a>
                </div>
            </div>"""
        content_panels += f"""<div class="day-panel {active}" id="panel-{date_key}">{cards}</div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Morris 推文时间轴</title>
<style>
:root{{
    --bg:#faf9f5;
    --surface:#fff;
    --border:#e8e5e0;
    --ink:#1c1917;
    --ink-muted:#57534e;
    --ink-soft:#a8a29e;
    --amber:#b45309;
    --amber-bg:#fffbeb;
    --blue:#1d4ed8;
    --radius:10px;
    --ease: cubic-bezier(0.32, 0.72, 0, 1);
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
    font-family: "PingFang SC","Hiragino Sans GB","Noto Serif SC","Microsoft YaHei",serif;
    background: var(--bg); color: var(--ink); line-height: 1.8;
    -webkit-font-smoothing: antialiased; font-size: 15px;
}}
header{{
    background: linear-gradient(135deg, #1c1917 0%, #292524 100%);
    color: #fff; padding: 28px 24px; text-align: center;
}}
header h1{{ font-size: 20px; font-weight: 700; letter-spacing: -.02em; }}
header .sub{{ font-size: 12px; opacity: .55; margin-top: 4px; }}
/* ── Layout ── */
.layout{{
    display: grid;
    grid-template-columns: 180px 1fr;
    max-width: 880px; margin: 0 auto; padding: 24px 16px 60px;
    gap: 28px; align-items: start;
}}
/* ── Sidebar ── */
.sidebar{{
    position: sticky; top: 20px;
    display: flex; flex-direction: column; gap: 2px;
}}
.date-item{{
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px; border-radius: 8px; cursor: pointer;
    transition: background .2s var(--ease);
    user-select: none; font-size: 14px;
}}
.date-item:hover{{ background: var(--amber-bg); }}
.date-item.active{{
    background: var(--amber-bg);
    box-shadow: inset 3px 0 0 var(--amber);
}}
.date-label{{ font-weight: 600; color: var(--ink); }}
.date-label .wk{{ font-weight: 400; color: var(--ink-soft); font-size: 12px; }}
.date-count{{
    font-size: 11px; color: var(--ink-soft); background: var(--bg);
    padding: 1px 8px; border-radius: 8px; font-weight: 500;
    font-variant-numeric: tabular-nums;
}}
.date-item.active .date-count{{ background: var(--amber); color: #fff; }}
/* ── Content ── */
.content{{ min-height: 400px; }}
.day-panel{{ display: none; }}
.day-panel.active{{ display: block; animation: fadeIn .35s var(--ease); }}
@keyframes fadeIn{{
    from{{ opacity: 0; transform: translateY(6px); }}
    to{{ opacity: 1; transform: translateY(0); }}
}}
.tweet-card{{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 18px 20px; margin-bottom: 10px;
    transition: box-shadow .2s var(--ease);
}}
.tweet-card:hover{{ box-shadow: 0 2px 8px rgba(0,0,0,.04); }}
.tweet-time{{ font-size: 11px; color: var(--ink-soft); margin-bottom: 6px; }}
.tweet-text{{ font-size: 15px; line-height: 1.8; word-break: break-word; }}
.tweet-text a{{ color: var(--blue); text-decoration: none; }}
.tweet-text a:hover{{ text-decoration: underline; }}
.tweet-stats{{
    display: flex; gap: 18px; margin-top: 12px; font-size: 12px;
    color: var(--ink-soft); flex-wrap: wrap; align-items: center;
}}
.tweet-stats .stat{{ white-space: nowrap; font-variant-numeric: tabular-nums; }}
.tweet-link{{
    color: var(--amber) !important; font-weight: 600;
    text-decoration: none; margin-left: auto; transition: opacity .2s;
}}
.tweet-link:hover{{ opacity: .7; text-decoration: none; }}
/* ── Stats bar ── */
.stats{{ display: flex; gap: 12px; margin: 20px 0; }}
.stat-card{{
    flex: 1; background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 14px; text-align: center;
}}
.stat-card .num{{ font-size: 26px; font-weight: 700; color: var(--amber); font-variant-numeric: tabular-nums; }}
.stat-card .label{{ font-size: 11px; color: var(--ink-soft); margin-top: 2px; }}
.footer{{ text-align: center; color: var(--ink-soft); font-size: 11px; margin-top: 48px; }}
/* ── Empty state ── */
.empty{{ text-align: center; padding: 60px 20px; color: var(--ink-soft); }}
.empty p{{ font-size: 14px; margin-top: 8px; }}
/* ── Mobile ── */
@media (max-width: 768px){{
    .layout{{
        grid-template-columns: 1fr; gap: 16px;
    }}
    .sidebar{{
        position: static; flex-direction: row; flex-wrap: wrap; gap: 4px;
    }}
    .date-item{{ font-size: 12px; padding: 6px 10px; }}
    .date-item.active{{ box-shadow: inset 0 -2px 0 var(--amber); }}
    .date-count{{ display: none; }}
}}
</style>
</head>
<body>
<header>
    <h1>Morris 推文时间轴</h1>
    <div class="sub">@{USERNAME} · 追踪 {days} 天 {total} 条 · 更新于 {now_str}</div>
</header>
<div class="layout">
    <nav class="sidebar">{sidebar_items}</nav>
    <main class="content">{content_panels}</main>
</div>
<div class="footer">自动抓取 · 每日 10:00 更新 · 数据来源 X/Twitter</div>
<script>
function switchDate(dateKey) {{
    document.querySelectorAll('.date-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.day-panel').forEach(el => el.classList.remove('active'));
    var item = document.querySelector('.date-item[data-date="' + dateKey + '"]');
    var panel = document.getElementById('panel-' + dateKey);
    if (item) item.classList.add('active');
    if (panel) panel.classList.add('active');
}}
</script>
</body>
</html>"""

    with open(HTML_FILE, "w") as f:
        f.write(html)
    print(f"看板: {HTML_FILE}")

def fmt_num(n):
    n = int(n or 0)
    if n >= 10000: return f"{n/10000:.1f}万"
    if n >= 1000: return f"{n/1000:.1f}k"
    return str(n)

def deploy():
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account_id:
        print("跳过部署：缺少 CLOUDFLARE_API_TOKEN 或 CLOUDFLARE_ACCOUNT_ID")
        return
    try:
        result = subprocess.run(
            ["npx", "wrangler", "pages", "deploy", PROJECT_DIR,
             "--project-name=morris-tracker", "--branch=main", "--commit-dirty=true"],
            capture_output=True, timeout=90, cwd=PROJECT_DIR,
            env={**os.environ, "CLOUDFLARE_API_TOKEN": token, "CLOUDFLARE_ACCOUNT_ID": account_id}
        )
        if result.returncode != 0:
            print(f"部署失败: {result.stderr[:200]}")
        else:
            print("部署成功")
    except Exception as e:
        print(f"部署异常: {e}")

if __name__ == "__main__":
    main()
