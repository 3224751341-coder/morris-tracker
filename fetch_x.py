#!/usr/bin/env python3
"""Fetch X/Twitter user tweets via Playwright (replaces opencli in cloud)"""
import json, os, sys, re, time
from datetime import datetime

USERNAME = sys.argv[1] if len(sys.argv) > 1 else "morris_lt"
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 50

def parse_count(text):
    """Parse engagement counts like '1.2K', '3.4万', '500'"""
    if not text:
        return 0
    text = text.strip().upper()
    if '万' in text:
        return int(float(text.replace('万', '')) * 10000)
    if 'K' in text:
        return int(float(text.replace('K', '')) * 1000)
    if 'M' in text:
        return int(float(text.replace('M', '')) * 1000000)
    try:
        return int(text)
    except:
        return 0

def scrape_tweets():
    """Launch headless Chrome, scrape tweets, output JSON to stdout"""
    from playwright.sync_api import sync_playwright

    tweets = []

    with sync_playwright() as p:
        # Launch headless Chromium
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
            ]
        )

        # Use a realistic user agent
        context = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 720},
            locale='en-US',
        )

        # Try to load cookies from env (base64-encoded JSON)
        cookies_b64 = os.environ.get('X_TWITTER_COOKIES')
        if cookies_b64:
            try:
                import base64
                cookies = json.loads(base64.b64decode(cookies_b64).decode())
                context.add_cookies(cookies)
            except Exception as e:
                print(f"⚠️  Cookie加载失败: {e}", file=sys.stderr)

        page = context.new_page()

        # Navigate to user's profile
        url = f'https://x.com/{USERNAME}'
        print(f"🔍 正在访问 {url}...", file=sys.stderr)

        try:
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            time.sleep(3)  # Wait for JS to render

            # Check if we hit a login wall
            page_text = page.text_content('body') or ''
            if 'log in' in page_text.lower() and ('sign up' in page_text.lower() or 'see' in page_text.lower()):
                print("❌ 需要登录才能查看推文", file=sys.stderr)
                if not cookies_b64:
                    print("💡 请导出 X.com Cookie 并设为 X_TWITTER_COOKIES secret", file=sys.stderr)
                browser.close()
                return []

            # Wait for tweets or timeout
            try:
                page.wait_for_selector('article[data-testid="tweet"]', timeout=10000)
            except:
                print("⚠️ 推文加载超时，可能没有推文或被限制", file=sys.stderr)
                browser.close()
                return []

            # Scroll to load more tweets
            last_count = 0
            for scroll in range(10):
                # Get current tweets
                tweet_articles = page.query_selector_all('article[data-testid="tweet"]')

                if len(tweet_articles) >= LIMIT or len(tweet_articles) == last_count:
                    break

                last_count = len(tweet_articles)

                # Scroll down
                page.evaluate('window.scrollBy(0, 800)')
                time.sleep(1.5)

            # Extract tweet data
            tweet_articles = page.query_selector_all('article[data-testid="tweet"]')
            print(f"📄 发现 {len(tweet_articles)} 条推文", file=sys.stderr)

            for article in tweet_articles[:LIMIT]:
                try:
                    # Tweet ID from link
                    link = article.query_selector('a[href*="/status/"]')
                    tid = ''
                    if link:
                        href = link.get_attribute('href') or ''
                        m = re.search(r'/status/(\d+)', href)
                        if m:
                            tid = m.group(1)

                    # Tweet text
                    text_elem = article.query_selector('[data-testid="tweetText"]')
                    text = text_elem.inner_text() if text_elem else ''

                    # Time
                    time_elem = article.query_selector('time')
                    created_at = ''
                    if time_elem:
                        created_at = time_elem.get_attribute('datetime') or ''

                    # Engagement metrics
                    likes = 0
                    retweets = 0
                    replies = 0
                    views = 0

                    # Try to extract stats
                    stats = article.query_selector_all('[data-testid$="count"]')
                    for stat in stats:
                        stat_text = stat.inner_text().strip() or ''
                        if not stat_text:
                            continue
                        aria_label = stat.get_attribute('aria-label') or ''
                        if 'reply' in aria_label.lower() or 'comment' in aria_label.lower():
                            replies = parse_count(stat_text)
                        elif 'retweet' in aria_label.lower() or 'repost' in aria_label.lower():
                            retweets = parse_count(stat_text)
                        elif 'like' in aria_label.lower():
                            likes = parse_count(stat_text)
                        elif 'view' in aria_label.lower():
                            views = parse_count(stat_text)

                    if tid:
                        tweets.append({
                            'id': tid,
                            'text': text.strip(),
                            'created_at': created_at,
                            'likes': likes,
                            'retweets': retweets,
                            'replies': replies,
                            'views': views,
                            'url': f'https://x.com/{USERNAME}/status/{tid}',
                            'captured_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M'),
                        })
                except Exception as e:
                    print(f"⚠️ 解析推文出错: {e}", file=sys.stderr)
                    continue

        except Exception as e:
            print(f"❌ 页面加载失败: {e}", file=sys.stderr)

        finally:
            browser.close()

    return tweets

if __name__ == '__main__':
    result = scrape_tweets()
    print(json.dumps(result, ensure_ascii=False, indent=2))
