import os
import re
import io
import streamlit as st
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta
import requests

## ページ設定 ##
st.set_page_config(
    page_title="BBS予定表作成ツール",
    page_icon="📅",
    layout="centered"
)

## スタイル ##
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans JP', sans-serif; }
    .main { background-color: #f8f9fa; }
    .stButton>button {
        border-radius: 8px;
        font-weight: bold;
        padding: 0.5em 1.5em;
        width: 100%;
    }
    .block-container { padding-top: 2rem; }
    .title-block {
        background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%);
        color: white;
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        text-align: center;
    }
    .info-box {
        background: #e3f2fd;
        border-left: 4px solid #1a73e8;
        padding: 0.8rem 1rem;
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    .success-box {
        background: #e8f5e9;
        border-left: 4px solid #43a047;
        padding: 0.8rem 1rem;
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

URL = "https://pken0hirosaki.jimdofree.com/bbs/"

## セッション初期化 ##
if "comments" not in st.session_state:
    st.session_state.comments = []
if "log" not in st.session_state:
    st.session_state.log = []

def add_log(msg):
    st.session_state.log.append(msg)


## HTMLをrequestsで取得（Seleniumの代替） ##
def download_bbs_html():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(URL, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


## コメントの取得 ##
def fetch_weekly_comments(html):
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


## 改行しているコメントを一行に直す ##
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


## コメントから日付・時間抽出 ##
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
            for pattern, use_posting_month in [
                (r'(\d{1,2})日', True),
                (r'(\d{1,2})（', True),
                (r'(\d{1,2})\(', True),
            ]:
                m = re.search(pattern, part)
                if m:
                    day = int(m.group(1))
                    month = datetime.now().month
                    date = (month, day)
                    break
            else:
                if re.search(r'今日', part):
                    date = (dt.month, dt.day)

        time_range = None
        if time_match:
            start, end = map(int, time_match.groups())
            time_range = (start, end)

        if date is not None:
            schedules.append((date, time_range))

    return schedules


## 予定件数カウント ##
def count_schedules(comments):
    now = datetime.now()
    tuesday = now - timedelta(days=(now.weekday() - 1) % 7)
    days = [(tuesday + timedelta(days=i)) for i in range(7)]
    start_hour, end_hour = 8, 24
    count = 0

    for c in comments:
        if "date" in c:
            schedules = parse_schedule_from_comment(c["text"], c["date"])
        elif "weekday" in c:
            weekdays = ["火","水","木","金","土","日","月"]
            weekday_map = {w:i for i,w in enumerate(weekdays)}
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


## 週間予定表描画 ##
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
        try:
            # Linux環境でよく使われる日本語フォント
            for fp in [
                "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            ]:
                if os.path.exists(fp):
                    font_large = ImageFont.truetype(fp, 18)
                    font_medium = ImageFont.truetype(fp, 14)
                    font_small = ImageFont.truetype(fp, 12)
                    break
            else:
                raise FileNotFoundError
        except:
            font_large = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()

    now = datetime.now()
    tuesday = now - timedelta(days=(now.weekday() - 1) % 7)
    days = [(tuesday + timedelta(days=i)) for i in range(7)]
    weekdays = ["火","水","木","金","土","日","月"]
    weekday_map = {w:i for i,w in enumerate(weekdays)}

    # 日付ヘッダ
    for i, day in enumerate(days):
        x = margin_left + i * day_width
        label = f"{day.month}/{day.day}"
        draw.text((x + 30, 50), label, fill="black", font=font_large)
        draw.text((x + 91, 53), f"({weekdays[i]})", fill="#444444", font=font_medium)

    # 時間軸
    for h in range(start_hour, end_hour + 1, 2):
        y = margin_top + (h - start_hour) * hour_height
        draw.text((40, y - 5), f"{h:02d}:00", fill="gray", font=font_small)
        draw.line((margin_left, y, margin_left + len(days) * day_width, y), fill="#DDDDDD")

    # 縦線
    for i in range(len(days) + 1):
        x = margin_left + i * day_width
        draw.line((x, margin_top, x, margin_top + (end_hour - start_hour) * hour_height), fill="black")

    # 予定描画
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
                        if time_range[1] - time_range[0] == 1:
                            draw.text((x + 53, y1 + 7), f"{author}", fill="black", font=font_small)
                        else:
                            draw.text((x + 15, y1 + 23), f"{author}", fill="black", font=font_small)

    # トリミング
    header_height = 80
    right = margin_left + len(days) * day_width
    bottom = margin_top + (end_hour - start_hour) * hour_height
    img = img.crop((0, 0, right + margin_left, bottom + header_height))

    return img


## ==== UI ====

st.markdown("""
<div class="title-block">
    <h2 style="margin:0; font-size:1.6rem;">📅 BBS予定表作成ツール</h2>
    <p style="margin:0.3rem 0 0; opacity:0.85; font-size:0.9rem;">
        BBSのコメントから週間予定表を自動生成します
    </p>
</div>
""", unsafe_allow_html=True)

# ------- STEP 1: コメント取得 -------
st.subheader("STEP 1　今週のコメントを取得")
col1, col2 = st.columns([3, 1])
with col1:
    st.markdown(f'<div class="info-box">取得先: <code>{URL}</code></div>', unsafe_allow_html=True)
with col2:
    fetch_btn = st.button("🔄 取得する", type="primary")

if fetch_btn:
    with st.spinner("BBSページを読み込み中..."):
        try:
            html = download_bbs_html()
            new_comments = fetch_weekly_comments(html)
            # 既存のBBSコメント（dateキーを持つもの）を置き換え
            st.session_state.comments = [c for c in st.session_state.comments if "weekday" in c]
            st.session_state.comments = new_comments + st.session_state.comments
            add_log(f"✅ コメント取得成功")
            count = count_schedules(st.session_state.comments)
            if new_comments:
                st.success(f"今週の予約件数：{count} 件")
                add_log(f"今週の予約件数：{count} 件")
            else:
                st.info("今週のコメントは見つかりませんでした。")
                add_log("今週のコメントは見つかりませんでした。")
        except Exception as e:
            st.error(f"取得エラー：{e}")
            add_log(f"❌ エラー: {e}")

st.divider()

# ------- STEP 2: 予定追加 -------
st.subheader("STEP 2　予定を手動で追加（任意）")

with st.expander("➕ 予定を追加する", expanded=False):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        weekday = st.selectbox("曜日", ["月", "火", "水", "木", "金", "土", "日"])
    with col_b:
        time_start = st.number_input("開始時間", min_value=0, max_value=23, value=10)
    with col_c:
        time_end = st.number_input("終了時間", min_value=1, max_value=24, value=12)
    author_name = st.text_input("投稿者名", placeholder="例：田中")

    if st.button("追加する"):
        if time_end <= time_start:
            st.error("終了時間は開始時間より後にしてください。")
        elif not author_name.strip():
            st.error("投稿者名を入力してください。")
        else:
            st.session_state.comments.append({
                "weekday": weekday,
                "time_range": (time_start, time_end),
                "author": author_name.strip()
            })
            st.success(f"追加しました：{weekday}曜日 {time_start}-{time_end} ({author_name})")
            add_log(f"手動追加：{weekday} {time_start}-{time_end} {author_name}")

# 追加済みリスト表示
manual = [c for c in st.session_state.comments if "weekday" in c]
if manual:
    st.markdown("**追加済みの予定：**")
    for i, c in enumerate(manual):
        col_x, col_y = st.columns([4, 1])
        with col_x:
            st.write(f"　{c['weekday']}曜日　{c['time_range'][0]}-{c['time_range'][1]}時　{c['author']}")
        with col_y:
            if st.button("削除", key=f"del_{i}"):
                st.session_state.comments = [x for x in st.session_state.comments if x is not c]
                st.rerun()

st.divider()

# ------- STEP 3: 画像生成 -------
st.subheader("STEP 3　週間予定表を生成")

if st.button("🖼️ 予定表を生成する", type="primary"):
    with st.spinner("画像を生成中..."):
        try:
            img = draw_weekly_schedule(st.session_state.comments)

            # バイト列に変換
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)

            st.image(img, caption="週間予定表", use_container_width=True)

            st.download_button(
                label="📥 画像をダウンロード (PNG)",
                data=buf,
                file_name="BBS予定表.png",
                mime="image/png"
            )
            add_log("✅ 画像生成完了")
        except Exception as e:
            st.error(f"画像生成エラー：{e}")
            add_log(f"❌ 画像生成エラー: {e}")

st.divider()

# ------- ログ -------
if st.session_state.log:
    with st.expander("📋 ログ", expanded=False):
        for line in st.session_state.log:
            st.text(line)

# ------- リセット -------
if st.button("🗑️ すべてリセット"):
    st.session_state.comments = []
    st.session_state.log = []
    st.rerun()
