"""
fetch_bbs.py  ―  PC上で実行するスクリプト
----------------------------------------------
Selenium で BBS を取得し、コメントを comments.json に保存します。
保存したJSONをStreamlitアプリにアップロードすれば
スマホから予定表を生成できます。

【使い方】
  1. pip install selenium webdriver-manager beautifulsoup4
  2. python fetch_bbs.py
  3. 生成された comments.json をStreamlitアプリにアップロード
"""

import re
import json
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

URL = "https://pken0hirosaki.jimdofree.com/bbs/"
OUTPUT_FILE = "comments.json"


def fetch_html_with_selenium():
    print("[ 1/3 ] Chromeを起動してBBSページを取得中...")

    options = webdriver.ChromeOptions()
    # headless を外すことで Cloudflare を回避（ポップアップを実際に表示する）
    # options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,800")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    driver.get(URL)

    # Cloudflare チャレンジが出た場合に備えて少し待機
    import time
    print("[ 2/3 ] ページ読み込み待機中（5秒）...")
    time.sleep(5)

    html = driver.page_source
    driver.quit()
    return html


def fetch_weekly_comments(html):
    print("[ 3/3 ] コメントを解析中...")
    soup = BeautifulSoup(html, "html.parser")

    now = datetime.now()
    tuesday = (now - timedelta(days=(now.weekday() - 1) % 7)).date()
    monday = tuesday + timedelta(days=6)

    comments = []

    for li in soup.find_all("li", id=re.compile("^commentEntry")):
        meta = li.find("p", class_="com-meta")
        if not meta:
            continue

        author_tag = meta.find("strong")
        author = author_tag.get_text(strip=True) if author_tag else "不明"

        em_tag = meta.find("em")
        if not em_tag:
            continue

        date_text = em_tag.get_text(strip=True)
        date_text = re.sub(r'^[^,]+,\s*', '', date_text)

        try:
            date_match = re.match(
                r"(\d{1,2})\s+(\d{1,2})月\s+(\d{4})\s+(\d{1,2}):(\d{2})", date_text
            )
            if not date_match:
                continue
            d, m, y, hh, mm = map(int, date_match.groups())
            dt = datetime(y, m, d, hh, mm)
        except Exception:
            continue

        if tuesday - timedelta(days=14) <= dt.date() <= monday:
            body = li.find("p", class_="commententry")
            if body:
                text = body.get_text("\n", strip=True)
                comments.append({
                    "date": dt.isoformat(),   # JSON用にISO形式で保存
                    "text": text,
                    "author": author
                })

    return comments


def main():
    html = fetch_html_with_selenium()
    comments = fetch_weekly_comments(html)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(comments, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完了！ {len(comments)} 件のコメントを {OUTPUT_FILE} に保存しました。")
    print(f"   → このファイルをStreamlitアプリにアップロードしてください。")


if __name__ == "__main__":
    main()
