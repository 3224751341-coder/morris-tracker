#!/usr/bin/env python3
"""认知博主推文追踪 · 多博主 · 每天10:00抓取前一天内容"""
import json, os, subprocess, sys
from datetime import datetime, timezone, timedelta

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(PROJECT_DIR, "data", "tweets.json")
HTML_FILE = os.path.join(PROJECT_DIR, "index.html")

# 博主配置：handle = X 账号，name = 展示名，desc = 一句话定位
USERS = [
    {"handle": "morris_lt",  "name": "Morris", "desc": "认知 / AI / 财富哲学"},
    {"handle": "svwang1",    "name": "王川",   "desc": "位置论 / 投资认知"},
    {"handle": "wadezone",   "name": "Koda",   "desc": "个人成长 / 赚钱方法论"},
    {"handle": "lxfater",    "name": "铁锤人", "desc": "AI 创业 / 行动派"},
]
USER_BY_HANDLE = {u["handle"]: u for u in USERS}
BJ = timezone(timedelta(hours=8))

def fetch_tweets(username, limit=50):
    """抓取某用户推文 — 三层兜底：opencli → Nitter RSS → Playwright"""
    # Tier 1: opencli (local Mac with Chrome extension)
    try:
        result = subprocess.run(
            ["opencli", "twitter", "tweets", username, "--limit", str(limit), "-f", "json",
             "--window", "background", "--keep-tab", "false"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if isinstance(data, list) and len(data) > 0:
                print(f"[{username}] opencli 抓取成功: {len(data)} 条")
                return data
    except:
        pass

    # Tier 2: Nitter RSS (cloud, no auth needed)
    import urllib.request, html as html_mod, re
    nitter_url = f"https://nitter.net/{username}/rss"
    print(f"[{username}] Nitter RSS: {nitter_url}")
    try:
        req = urllib.request.Request(nitter_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
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
                        "author": username,
                        "name": USER_BY_HANDLE.get(username, {}).get("name", username),
                        "text": html_mod.unescape(m_title.group(1)).strip(),
                        "created_at": m_date.group(1).strip(),
                        "likes": 0, "retweets": 0, "replies": 0, "views": 0,
                        "url": f"https://x.com/{username}/status/{tid_m.group(1)}" if tid_m else "",
                        "captured_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M"),
                    })
            print(f"[{username}] Nitter RSS 抓取成功: {len(tweets)} 条")
            return tweets
        print(f"[{username}] Nitter RSS 无内容")
    except Exception as e:
        print(f"[{username}] Nitter RSS 失败: {e}")

    # Tier 3: Playwright headless (last resort, needs cookies)
    print(f"[{username}] 尝试 Playwright 浏览器抓取...")
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(PROJECT_DIR, "fetch_x.py"), username, str(limit)],
            capture_output=True, text=True, timeout=90
        )
        if result.stderr:
            print(f"[{username}] Playwright 日志:\n{result.stderr[:300]}")
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if isinstance(data, list):
                print(f"[{username}] Playwright 抓取成功: {len(data)} 条")
                return data
    except Exception as e:
        print(f"[{username}] Playwright 异常: {e}")

    return []

def load_db():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            db = json.load(f)
        # 旧格式迁移：{"tweets": {...}} → {"users": {"morris_lt": {"tweets": {...}}}}
        if "tweets" in db and isinstance(db["tweets"], dict):
            print("检测到旧格式数据，迁移到 users 结构...")
            db = {
                "users": {USERS[0]["handle"]: {"tweets": db["tweets"]}},
                "last_fetch": db.get("last_fetch"),
            }
        if "users" not in db:
            db["users"] = {}
        return db
    return {"users": {}, "last_fetch": None}

def save_db(db):
    db["last_fetch"] = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    with open(DATA_FILE, "w") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def main():
    now = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    db = load_db()
    # 确保每个博主都有结构
    for u in USERS:
        if u["handle"] not in db["users"]:
            db["users"][u["handle"]] = {"tweets": {}}

    total_new = 0
    for u in USERS:
        handle = u["handle"]
        print(f"[{now}] 抓取 @{handle} ({u['name']})...")
        tweets = fetch_tweets(handle, 50)
        if not tweets:
            print(f"[{handle}] 无新推文")
            continue
        tweets_map = db["users"][handle]["tweets"]
        new_count = 0
        for t in tweets:
            tid = str(t.get("id", ""))
            if tid and tid not in tweets_map:
                # 过滤无效推文：无文本或无日期的不入库
                text = (t.get("text") or "").strip()
                date = t.get("created_at") or ""
                if not text or not date:
                    continue
                t["captured_at"] = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
                tweets_map[tid] = t
                new_count += 1
        # 清理历史空数据
        cleaned = 0
        for tid in list(tweets_map.keys()):
            t = tweets_map[tid]
            if not (t.get("text") or "").strip() or not (t.get("created_at") or ""):
                del tweets_map[tid]
                cleaned += 1
        if cleaned:
            print(f"[{handle}] 清理 {cleaned} 条空数据")
        total_new += new_count
        print(f"[{handle}] 新增 {new_count} 条，累计 {len(tweets_map)} 条")

    save_db(db)
    print(f"本轮共新增 {total_new} 条")
    generate_html(db)
    deploy()

def parse_date(date_str):
    """解析 Twitter 日期格式 — 同时支持 opencli (%a %b %d ... +0000 %Y) 和 Nitter RSS (%a, %d %b %Y ... GMT)"""
    if not date_str:
        return datetime(2000, 1, 1, tzinfo=timezone.utc)
    # 统一时区后缀: GMT/UTC → +0000 让 %z 能解析
    cleaned = date_str.strip()
    cleaned = cleaned.replace(" GMT", " +0000").replace(" UTC", " +0000")
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%a %b %d %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now().year)
            return dt
        except:
            continue
    return datetime(2000, 1, 1, tzinfo=timezone.utc)

def generate_html(db):
    import re
    now_str = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    total_all = 0

    # ── 博主 Tab + 侧边栏日期项 + 内容面板 ──
    tabs = ""
    sidebar_items = ""
    content_panels = ""
    for idx, u in enumerate(USERS):
        handle = u["handle"]
        tweets_map = db.get("users", {}).get(handle, {}).get("tweets", {})
        tweets = sorted(tweets_map.values(), key=lambda t: parse_date(t.get("created_at", "")), reverse=True)
        total_all += len(tweets)

        # 按日期分组
        by_date = {}
        for t in tweets:
            dt = parse_date(t.get("created_at", ""))
            date_key = dt.strftime("%Y-%m-%d")
            if date_key not in by_date:
                by_date[date_key] = {"dt": dt, "tweets": []}
            by_date[date_key]["tweets"].append(t)
        sorted_dates = sorted(by_date.keys(), reverse=True)

        tab_active = "active" if idx == 0 else ""
        tabs += f"""<div class="user-tab {tab_active}" data-user="{handle}" onclick="switchUser('{handle}')">
                <span class="user-name">{u['name']}</span>
                <span class="user-count">{len(tweets)}</span>
            </div>"""

        for i, date_key in enumerate(sorted_dates):
            group = by_date[date_key]
            dt = group["dt"]
            count = len(group["tweets"])
            weekday = ["日","一","二","三","四","五","六"][int(dt.strftime("%w"))]
            date_display = f'{dt.strftime("%m月%d日")} <span class="wk">周{weekday}</span>'
            hidden = ' style="display:none"' if idx != 0 else ""
            active = "active" if idx == 0 and i == 0 else ""
            sidebar_items += f"""<div class="date-item {active}" data-user="{handle}" data-date="{date_key}" onclick="switchDate('{handle}','{date_key}')"{hidden}>
                <span class="date-label">{date_display}</span>
                <span class="date-count">{count}</span>
            </div>"""

            cards = ""
            for t in group["tweets"]:
                text = (t.get("text", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                text = re.sub(r'(https?://\S+)', r'<a href="\1" target="_blank" rel="noopener">\1</a>', text)
                likes = t.get("likes", 0) or 0
                retweets = t.get("retweets", 0) or 0
                replies = t.get("replies", 0) or 0
                views = t.get("views", 0) or 0
                tid = t.get("id", "")
                tweet_url = f"https://x.com/{handle}/status/{tid}" if tid else "#"
                t_dt = parse_date(t.get("created_at", ""))
                time_str = t_dt.strftime("%H:%M") if t_dt.year != 2000 else ""
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
            panel_active = "active" if idx == 0 and i == 0 else ""
            content_panels += f"""<div class="day-panel {panel_active}" id="panel-{handle}-{date_key}">{cards}</div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>认知博主时间轴</title>
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
    color: #fff; padding: 26px 24px 20px; text-align: center;
}}
header h1{{ font-size: 20px; font-weight: 700; letter-spacing: -.02em; }}
header .sub{{ font-size: 12px; opacity: .55; margin-top: 4px; }}
/* ── User Tabs ── */
.user-tabs{{
    display: flex; justify-content: center; gap: 8px; margin-top: 16px; flex-wrap: wrap;
}}
.user-tab{{
    display: flex; align-items: center; gap: 8px;
    padding: 8px 16px; border-radius: 999px; cursor: pointer;
    background: rgba(255,255,255,.08); color: #e7e5e4;
    font-size: 14px; font-weight: 600; user-select: none;
    transition: background .2s var(--ease);
}}
.user-tab:hover{{ background: rgba(255,255,255,.16); }}
.user-tab.active{{
    background: var(--amber); color: #fff;
}}
.user-count{{
    font-size: 11px; font-weight: 400; opacity: .75;
    background: rgba(0,0,0,.15); padding: 1px 8px; border-radius: 8px;
    font-variant-numeric: tabular-nums;
}}
.user-tab.active .user-count{{ background: rgba(0,0,0,.2); }}
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
    <h1>认知博主时间轴</h1>
    <div class="sub">{len(USERS)} 位博主 · {total_all} 条推文 · 更新于 {now_str}</div>
    <nav class="user-tabs">{tabs}</nav>
</header>
<div class="layout">
    <nav class="sidebar">{sidebar_items}</nav>
    <main class="content">{content_panels}</main>
</div>
<div class="footer">自动抓取 · 每日 10:00 更新 · 数据来源 X/Twitter</div>
<script>
function switchUser(user) {{
    document.querySelectorAll('.user-tab').forEach(el => el.classList.toggle('active', el.dataset.user === user));
    document.querySelectorAll('.date-item').forEach(el => {{
        el.style.display = (el.dataset.user === user) ? '' : 'none';
    }});
    var first = document.querySelector('.date-item[data-user="' + user + '"]');
    switchDate(user, first ? first.dataset.date : '');
}}
function switchDate(user, date) {{
    document.querySelectorAll('.date-item[data-user="' + user + '"]').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.day-panel').forEach(el => el.classList.remove('active'));
    var item = document.querySelector('.date-item[data-user="' + user + '"][data-date="' + date + '"]');
    var panel = document.getElementById('panel-' + user + '-' + date);
    if (item) item.classList.add('active');
    if (panel) panel.classList.add('active');
}}
switchUser('{USERS[0]["handle"]}');
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
