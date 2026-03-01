"""
BBS_streamlit.py  ―  Streamlit Webアプリ本体
----------------------------------------------
fetch_bbs.py で生成した comments.json をアップロードし、
週間予定表PNG画像を生成・ダウンロードできます。
スマホ（iPhone / Android）のブラウザから利用可能。
"""

import os
import re
import io
import json
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta

# ページ設定
st.set_page_config(
    page_title="BBS予定表作成ツール",
    page_icon="📅",
    layout="centered"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans JP', sans-serif; }
    .block-container { padding-top: 1.5rem; max-width: 720px; }
    .title-block {
        background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%);
        color: white;
        padding: 1.4rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        text-align: center;
    }
    .step-box {
        background: #f0f4ff;
        border-left: 4px solid #1a73e8;
        border-radius: 6px;
        padding: 0.8rem 1.2rem;
        margin-bottom: 1rem;
    }
    .stButton>button {
        border-radius: 8px;
        font-weight: bold;
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

# セッション初期化
if "bbs_comments" not in st.session_state:
    st.session_state.bbs_comments = []
if "extra_comments" not in st.session_state:
    st.session_state.extra_comments = []


# ===================== ユーティリティ関数 =====================

def load_comments_from_json(data: bytes):
    """JSONバイト列をコメントリストに変換（date文字列→datetimeへ復元）"""
    raw = json.loads(data.decode("utf-8"))
    comments = []
    for c in raw:
        try:
            c["date"] = datetime.fromisoformat(c["date"])
        except Exception:
            continue
        comments.append(c)
    return comments


def merge_date_and_time_lines(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    merged = []
    i = 0
    while i < len(lines):
        line = lines[i]
        date_pat = r'(\d{1,2}日)|(\d{1,2}（)|(\d{1,2}\()'
        time_pat = r'\d{1,2}[ｰ\-~〜]\d{1,2}'
        if re.search(date_pat, line) and not re.search(time_pat, line):
            if i + 1 < len(lines) and re.search(time_pat, lines[i + 1]):
                merged.append(line + " " + lines[i + 1])
                i += 2
                continue
        elif re.search(time_pat, line) and not re.search(date_pat, line):
            if i + 1 < len(lines) and re.search(date_pat, lines[i + 1]):
                merged.append(line + " " + lines[i + 1])
                i += 2
                continue
        merged.append(line)
        i += 1
    return "\n".join(merged)


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
            for pattern in [r'(\d{1,2})日', r'(\d{1,2})（', r'(\d{1,2})\(']:
                m = re.search(pattern, part)
                if m:
                    date = (datetime.now().month, int(m.group(1)))
                    break
            else:
                if re.search(r'今日', part):
                    date = (dt.month, dt.day)

        time_range = None
        if time_match:
            s, e = map(int, time_match.groups())
            time_range = (s, e)

        if date is not None:
            schedules.append((date, time_range))

    return schedules


def count_schedules(all_comments):
    now = datetime.now()
    tuesday = now - timedelta(days=(now.weekday() - 1) % 7)
    days = [(tuesday + timedelta(days=i)) for i in range(7)]
    start_hour, end_hour = 8, 24
    count = 0
    for c in all_comments:
        if "date" in c:
            schedules = parse_schedule_from_comment(c["text"], c["date"])
        elif "weekday" in c:
            wdays = ["火","水","木","金","土","日","月"]
            wmap = {w: i for i, w in enumerate(wdays)}
            idx = wmap.get(c["weekday"])
            if idx is None:
                continue
            schedules = [((days[idx].month, days[idx].day), c["time_range"])]
        else:
            continue
        for date, time_range in schedules:
            if date is None or time_range is None:
                continue
            s, e = time_range
            if e <= start_hour or s >= end_hour:
                continue
            for day in days:
                if day.month == date[0] and day.day == date[1]:
                    count += 1
                    break
    return count


def draw_weekly_schedule(all_comments):
    width, height = 1150, 850
    margin_top = 100
    margin_left = 100
    day_width = 130
    hour_height = 30
    start_hour = 8
    end_hour = 24

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font_paths = [
        "meiryo.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    ]
    font_large = font_medium = font_small = None
    for fp in font_paths:
        if os.path.exists(fp):
            font_large  = ImageFont.truetype(fp, 18)
            font_medium = ImageFont.truetype(fp, 14)
            font_small  = ImageFont.truetype(fp, 12)
            break
    if font_large is None:
        font_large = font_medium = font_small = ImageFont.load_default()

    now = datetime.now()
    tuesday = now - timedelta(days=(now.weekday() - 1) % 7)
    days = [(tuesday + timedelta(days=i)) for i in range(7)]
    weekdays = ["火","水","木","金","土","日","月"]
    weekday_map = {w: i for i, w in enumerate(weekdays)}

    # 日付ヘッダ
    for i, day in enumerate(days):
        x = margin_left + i * day_width
        draw.text((x + 30, 50), f"{day.month}/{day.day}", fill="black", font=font_large)
        draw.text((x + 91, 53), f"({weekdays[i]})", fill="#444444", font=font_medium)

    # 時間軸 & グリッド
    for h in range(start_hour, end_hour + 1, 2):
        y = margin_top + (h - start_hour) * hour_height
        draw.text((40, y - 5), f"{h:02d}:00", fill="gray", font=font_small)
        draw.line((margin_left, y, margin_left + len(days) * day_width, y), fill="#DDDDDD")

    # 縦線
    for i in range(len(days) + 1):
        x = margin_left + i * day_width
        draw.line((x, margin_top, x, margin_top + (end_hour - start_hour) * hour_height), fill="black")

    # 予定ブロック描画
    for c in all_comments:
        if "date" in c:
            schedules = parse_schedule_from_comment(c["text"], c["date"])
            author = c.get("author", "")
        elif "weekday" in c:
            idx = weekday_map.get(c["weekday"])
            if idx is None:
                continue
            date = (days[idx].month, days[idx].day)
            schedules = [(date, c["time_range"])]
            author = c["author"]
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
                        draw.text((x + 10, y1 + 5), f"{time_range[0]}-{time_range[1]}", fill="black", font=font_small)
                        if time_range[1] - time_range[0] == 1:
                            draw.text((x + 53, y1 + 7), author, fill="black", font=font_small)
                        else:
                            draw.text((x + 15, y1 + 23), author, fill="black", font=font_small)

    right = margin_left + len(days) * day_width
    bottom = margin_top + (end_hour - start_hour) * hour_height
    img = img.crop((0, 0, right + margin_left, bottom + 80))
    return img


# ===================== UI =====================

st.markdown("""
<div class="title-block">
  <h2 style="margin:0;font-size:1.5rem;">📅 BBS予定表作成ツール</h2>
  <p style="margin:0.3rem 0 0;opacity:0.85;font-size:0.85rem;">
    PCで取得したコメントデータをもとに週間予定表を生成します
  </p>
</div>
""", unsafe_allow_html=True)

# -------- STEP 1: JSON アップロード --------
st.subheader("STEP 1　コメントデータを読み込む")

st.markdown("""
<div class="step-box">
  PCで <code>fetch_bbs.py</code> を実行して生成した
  <strong>comments.json</strong> をアップロードしてください。
</div>
""", unsafe_allow_html=True)

uploaded_json = st.file_uploader(
    "comments.json をアップロード",
    type=["json"],
    help="fetch_bbs.py を実行すると同じフォルダに生成されます"
)

if uploaded_json:
    try:
        loaded = load_comments_from_json(uploaded_json.read())
        st.session_state.bbs_comments = loaded
        count = count_schedules(loaded + st.session_state.extra_comments)
        st.success(f"✅ {len(loaded)} 件のコメントを読み込みました（今週の予約数：{count} 件）")
    except Exception as e:
        st.error(f"読み込みエラー：{e}")

if st.session_state.bbs_comments:
    with st.expander(f"📋 読み込んだコメント（{len(st.session_state.bbs_comments)} 件）"):
        for c in st.session_state.bbs_comments:
            dt = c["date"]
            st.markdown(f"**{c['author']}** — {dt.month}/{dt.day}  \n{c['text'][:80]}...")

st.divider()

# -------- STEP 2: 手動追加 --------
st.subheader("STEP 2　予定を手動で追加（任意）")

with st.expander("➕ 予定を追加する"):
    c1, c2, c3 = st.columns(3)
    with c1:
        weekday = st.selectbox("曜日", ["月", "火", "水", "木", "金", "土", "日"])
    with c2:
        t_start = st.number_input("開始", min_value=0, max_value=23, value=10)
    with c3:
        t_end = st.number_input("終了", min_value=1, max_value=24, value=12)
    author_name = st.text_input("投稿者名", placeholder="例：田中")

    if st.button("追加する"):
        if t_end <= t_start:
            st.error("終了時間は開始時間より後にしてください。")
        elif not author_name.strip():
            st.error("投稿者名を入力してください。")
        else:
            st.session_state.extra_comments.append({
                "weekday": weekday,
                "time_range": (t_start, t_end),
                "author": author_name.strip()
            })
            st.success(f"追加：{weekday}曜日 {t_start}-{t_end} ({author_name})")
            st.rerun()

if st.session_state.extra_comments:
    st.markdown("**手動追加済み：**")
    for i, c in enumerate(st.session_state.extra_comments):
        ca, cb = st.columns([5, 1])
        with ca:
            st.write(f"　{c['weekday']}曜日　{c['time_range'][0]}-{c['time_range'][1]}時　{c['author']}")
        with cb:
            if st.button("削除", key=f"del_{i}"):
                st.session_state.extra_comments.pop(i)
                st.rerun()

st.divider()

# -------- STEP 3: 画像生成 --------
st.subheader("STEP 3　週間予定表を生成")

all_comments = st.session_state.bbs_comments + st.session_state.extra_comments

if st.button("🖼️ 予定表を生成する", type="primary"):
    if not all_comments:
        st.warning("コメントが0件です。空の予定表を生成します。")
    with st.spinner("画像を生成中..."):
        try:
            img = draw_weekly_schedule(all_comments)
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
        except Exception as e:
            st.error(f"画像生成エラー：{e}")

st.divider()

if st.button("🗑️ すべてリセット"):
    st.session_state.bbs_comments = []
    st.session_state.extra_comments = []
    st.rerun()
