import os
import re
import shutil
import time
from datetime import datetime, timedelta

from flask import Flask, render_template, request, redirect, url_for, send_from_directory

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium import webdriver


## 初期設定 ##
URL = "https://pken0hirosaki.jimdofree.com/bbs/"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

OUTPUT_PATH = os.path.join(STATIC_DIR, "BBS予定表.png")
HTML_PATH = os.path.join(STATIC_DIR, "BBS.html")

os.makedirs(STATIC_DIR, exist_ok=True)

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

## メモリ上で保持（サーバー起動中だけ保持）##
comments_cache = []
log_lines = ["| ログ表示"]


## Chromeが入っているかチェック ##
def check_chrome_installed():
    # Docker(Render)環境では which で確認
    if shutil.which("google-chrome") or shutil.which("google-chrome-stable"):
        return True

    # Windows環境用（ローカル用）
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
    ]

    for path in chrome_paths:
        if os.path.exists(path):
            return True

    if shutil.which("chrome") or shutil.which("chrome.exe"):
        return True

    return False


## HTMLを取得 ##
def download_bbs_html():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    driver.get(URL)
    time.sleep(3)

    html = driver.page_source
    driver.quit()

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)


## ログ追加用関数 ##
def add_log(msg):
    # now = datetime.now().strftime("%H:%M:%S")
    log_lines.append(f"{msg}")


## コメント取得 ##
def fetch_weekly_comments():
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

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
            date_match = re.match(r"(\d{1,2})\s+(\d{1,2})月\s+(\d{4})\s+(\d{1,2}):(\d{2})", date_text)
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
                comments.append({"date": dt, "text": text, "author": author})

    return comments


## 改行結合 ##
def merge_date_and_time_lines(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    merged = []
    i = 0

    while i < len(lines):
        line = lines[i]
        date_line_pattern = r'(\d{1,2}日)|(\d{1,2}（)|(\d{1,2}\()'

        if re.search(date_line_pattern, line) and not re.search(r'\d{1,2}[ｰ\-~〜]\d{1,2}', line):
            if i + 1 < len(lines) and re.search(r'\d{1,2}[ｰ\-~〜]\d{1,2}', lines[i+1]):
                merged.append(line + " " + lines[i + 1])
                i += 2
                continue

        elif re.search(r'\d{1,2}[ｰ\-~〜]\d{1,2}', line) and not re.search(date_line_pattern, line):
            if i + 1 < len(lines) and re.search(date_line_pattern, lines[i + 1]):
                merged.append(line + " " + lines[i + 1])
                i += 2
                continue

        merged.append(line)
        i += 1

    return "\n".join(merged)


## コメントから日付時間抽出 ##
def parse_schedule_from_comment(text, dt):
    schedules = []
    text = merge_date_and_time_lines(text)
    parts = re.split(r"[と、,/／\n]", text)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        date = None
        date_match = re.search(r'(\d{1,2})/(\d{1,2})', part)
        time_match = re.search(r'(\d{1,2})[ｰ\-~〜](\d{1,2})', part)

        if date_match:
            month, day = map(int, date_match.groups())
            date = (month, day)
        else:
            date_match = re.search(r'(\d{1,2})日', part)
            if date_match:
                day = int(date_match.group(1))
                month = datetime.now().month
                date = (month, day)
            else:
                date_match = re.search(r'(\d{1,2})（', part)
                if date_match:
                    day = int(date_match.group(1))
                    month = datetime.now().month
                    date = (month, day)
                else:
                    date_match = re.search(r'(\d{1,2})\(', part)
                    if date_match:
                        day = int(date_match.group(1))
                        month = datetime.now().month
                        date = (month, day)
                    else:
                        date_match = re.search(r'今日', part)
                        if date_match:
                            day = dt.day
                            month = dt.month
                            date = (month, day)

        if time_match:
            start, end = map(int, time_match.groups())
            time_range = (start, end)
        else:
            time_range = None

        if date is not None:
            schedules.append((date, time_range))

    return schedules


## 予約件数カウント ##
def count_schedules(comments):
    now = datetime.now()
    tuesday = now - timedelta(days=(now.weekday() - 1) % 7)
    days = [(tuesday + timedelta(days=i)) for i in range(7)]

    start_hour = 8
    end_hour = 24

    count = 0

    for c in comments:
        if "date" in c:
            schedules = parse_schedule_from_comment(c["text"], c["date"])
        elif "weekday" in c:
            weekdays = ["火", "水", "木", "金", "土", "日", "月"]
            weekday_map = {w: i for i, w in enumerate(weekdays)}

            weekday_index = weekday_map.get(c["weekday"])
            if weekday_index is None:
                continue

            date = (days[weekday_index].month, days[weekday_index].day)
            schedules = [(date, c["time_range"])]
        else:
            continue

        for date, time_range in schedules:
            if date is None or time_range is None:
                continue

            start, end = time_range

            if end <= start_hour or start >= end_hour:
                continue

            for day in days:
                if day.month == date[0] and day.day == date[1]:
                    count += 1
                    break

    return count


## 画像生成 ##
def draw_weekly_schedule(comments):
    width, height = 1150, 850
    margin_top = 100
    margin_left = 100
    day_width = 130
    hour_height = 30
    start_hour = 8
    end_hour = 24

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype("meiryo.ttc", 18)
        font_medium = ImageFont.truetype("meiryo.ttc", 14)
        font_small = ImageFont.truetype("meiryo.ttc", 12)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()

    now = datetime.now()
    tuesday = now - timedelta(days=(now.weekday() - 1) % 7)
    days = [(tuesday + timedelta(days=i)) for i in range(7)]
    weekdays = ["火", "水", "木", "金", "土", "日", "月"]
    weekday_map = {w: i for i, w in enumerate(weekdays)}

    for i, day in enumerate(days):
        x = margin_left + i * day_width
        label = f"{day.month}/{day.day}"
        draw.text((x + 30, 50), label, fill="black", font=font_large)
        draw.text((x + 91, 53), f"({weekdays[i]})", fill="#444444", font=font_medium)

    for h in range(start_hour, end_hour + 1, 2):
        y = margin_top + (h - start_hour) * hour_height
        draw.text((40, y - 5), f"{h:02d}:00", fill="gray", font=font_small)
        draw.line((margin_left, y, margin_left + len(days) * day_width, y), fill="#DDDDDD")

    for i in range(len(days) + 1):
        x = margin_left + i * day_width
        draw.line((x, margin_top, x, margin_top + (end_hour - start_hour) * hour_height), fill="black")

    for c in comments:
        if "date" in c:
            schedules = parse_schedule_from_comment(c["text"], c["date"])
            author = c.get("author", "")
        elif "weekday" in c:
            weekday_index = weekday_map.get(c["weekday"])
            if weekday_index is None:
                continue
            date = (days[weekday_index].month, days[weekday_index].day)
            time_range = c["time_range"]
            author = c["author"]
            schedules = [(date, time_range)]
        else:
            continue

        for date, time_range in schedules:
            if date is None:
                continue

            for i, day in enumerate(days):
                if day.month == date[0] and day.day == date[1]:
                    x = margin_left + i * day_width + 5
                    if time_range:
                        y1 = margin_top + (time_range[0] - start_hour) * hour_height
                        y2 = margin_top + (time_range[1] - start_hour) * hour_height
                        draw.rectangle((x, y1, x + day_width - 10, y2), fill="#A7C7E7", outline="black")

                        time_text = f"{time_range[0]}-{time_range[1]}"
                        draw.text((x + 10, y1 + 5), time_text, fill="black", font=font_small)

                        if (time_range[1] - time_range[0] == 1):
                            draw.text((x + 53, y1 + 7), f"{author}", fill="black", font=font_small)
                        else:
                            draw.text((x + 15, y1 + 23), f"{author}", fill="black", font=font_small)

    header_height = 80
    right = margin_left + len(days) * day_width
    bottom = margin_top + (end_hour - start_hour) * hour_height
    img = img.crop((0, 0, right + margin_left, bottom + header_height))

    img.save(OUTPUT_PATH)


## Flask 画面 ##
@app.route("/", methods=["GET"])
def index():
    schedule_count = count_schedules(comments_cache)
    return render_template("index.html", count=schedule_count, logs=log_lines)


@app.route("/fetch", methods=["POST"])
def fetch():
    global comments_cache

    if not check_chrome_installed():
        add_log("| Chromeがインストールされていません")
        return "Chromeがインストールされていません", 400

    add_log("| ページを取得してHTMLを保存します...")
    download_bbs_html()

    add_log("| HTMLから今週のコメントを抽出します...")
    comments_cache = fetch_weekly_comments()

    schedule_count = count_schedules(comments_cache)
    add_log(f"| 今週の予約件数 : {schedule_count}")

    return redirect(url_for("index"))


@app.route("/add", methods=["POST"])
def add():
    weekday = request.form.get("weekday")
    time_range_str = request.form.get("time_range")
    author = request.form.get("author")

    time_match = re.match(r"(\d{1,2})[ｰ\-~〜](\d{1,2})", time_range_str)
    if not time_match:
        add_log("| エラー: 時間の形式が不正です (例: 10-12)")
        return "時間の形式が不正です (例: 10-12)", 400

    start, end = map(int, time_match.groups())

    comments_cache.append({
        "weekday": weekday,
        "time_range": (start, end),
        "author": author
    })

    add_log(f"| 追加: {weekday} {start}-{end} {author}")

    return redirect(url_for("index"))


@app.route("/draw", methods=["POST"])
def draw():
    add_log("| 週間予定表を作成します...")
    draw_weekly_schedule(comments_cache)
    add_log("| 画像を出力しました : BBS予定表.png")

    return redirect(url_for("index"))


@app.route("/image")
def image():
    if not os.path.exists(OUTPUT_PATH):
        return "画像がまだ生成されていません", 404

    return send_from_directory(STATIC_DIR, "BBS予定表.png")


@app.route("/reset", methods=["POST"])
def reset():
    global comments_cache, log_lines

    comments_cache = []
    log_lines = ["| ログ表示"]

    if os.path.exists(OUTPUT_PATH):
        os.remove(OUTPUT_PATH)

    if os.path.exists(HTML_PATH):
        os.remove(HTML_PATH)

    # add_log("| リセットしました")

    return redirect(url_for("index"))


if __name__ == "__main__":
    # スマホからアクセスするため host="0.0.0.0"
    # app.run(host="0.0.0.0", port=5000, debug=True)

    # Render用

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
