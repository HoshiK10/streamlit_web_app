import streamlit as st
from data_loader import (
    load_rows_from_csv,
    backfill_missing_latlng_and_save,
    build_geo_from_rows,
    load_color_legend,
    load_color_legend_ordered,
)
from map_view import build_map_html
from qr_utils import show_qr_simple
import urllib.parse, re
import html as _html  # ← 追加（HTMLエスケープ用）

st.set_page_config(page_title="近くの飲食店マップ", layout="wide")
st.markdown("""
<style>
@media print {
  /* 余白を詰めて最後の「少しだけはみ出す」を防ぐ */
  .block-container { padding-bottom: 0 !important; }
  hr { page-break-after: avoid; }

  /* 地図ブロックを途中改ページしない */
  .map-print { break-inside: avoid; page-break-inside: avoid; }

  /* iframe(srcdoc) が余白で空ページを作りにくいよう高さを固定（必要に応じて調整） */
  .map-print iframe { height: 500px !important; }

  /* 一部ブラウザ向け：不要な強制改ページを避ける */
  * { page-break-after: auto !important; }
}
/* 凡例のライト/ダーク対応（Streamlitテーマの文字色を利用） */
.legend-item { display:flex; align-items:flex-start; margin:10px 0; }
.legend-icon { flex:0 0 auto; display:inline-block; margin:2px 10px 0 2px; }
.legend-text { line-height:1.35; }
.legend-title { font-weight:700; color: var(--text-color); }
.legend-desc  { color: var(--text-color); opacity: .75; white-space: pre-wrap; font-size: 13px; }
</style>
""", unsafe_allow_html=True)
st.title("🍽 近くの飲食店マップ")

def _normalize_hex(s: str) -> str:
    """#RRGGBB を返す。16進6桁のみ対応。その他は空文字。"""
    import re
    ss = (s or "").strip().lower()
    if not ss:
        return ""
    ss = re.sub(r"\s+", "", ss)
    m = re.fullmatch(r"#?([0-9a-f]{6})", ss)
    return f"#{m.group(1)}" if m else ""

def _darken_hex(hex_color: str, amount: float = 0.3) -> str | None:
    """#RRGGBB を暗くする。hex でなければ None。"""
    hx = _normalize_hex(hex_color)
    if not hx:
        return None
    num = int(hx[1:], 16)
    r = max(0, int(((num >> 16) & 255) * (1 - amount)))
    g = max(0, int(((num >> 8)  & 255) * (1 - amount)))
    b = max(0, int(((num      ) & 255) * (1 - amount)))
    return f"#{r:02x}{g:02x}{b:02x}"

def make_pin_svg_data_uri(fill: str = "#EF4444", stroke: str | None = None) -> str:
    """地図と同じ形のピンSVGを data URI で返す。"""
    s = stroke or _darken_hex(fill) or fill
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='36' height='54' viewBox='0 0 36 54'>"
        f"<path fill='{fill}' stroke='{s}' d='M18 0c-9.94 0-18 8.06-18 18 0 12 18 36 18 36s18-24 18-36C36 8.06 27.94 0 18 0z'/>"
        "<circle cx='18' cy='18' r='6' fill='#ffffff'/>"
        "</svg>"
    )
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)

# ---- Secrets ----
MAPS_JS_API_KEY = st.secrets.get("MAPS_JS_API_KEY")
GEOCODING_API_KEY = st.secrets.get("GEOCODING_API_KEY")
if not MAPS_JS_API_KEY or not GEOCODING_API_KEY:
    st.error("Secrets に MAPS_JS_API_KEY / GEOCODING_API_KEY を設定してください。")
    st.stop()

CSV_PATH = "places.csv"  # ヘッダ：店名,ジャンル,価格帯,色,説明,URL,住所,緯度,経度,南北補正,東西補正

# ---- CSV 読み込み ----
rows = load_rows_from_csv(CSV_PATH)
if len(rows) < 2:
    st.error("CSVには最低2行（2行目=地図中心／3行目=現在位置／4行目以降=店舗や領域）を入れてください。")
    st.stop()

# ---- 不足緯度経度の補完（必要な時だけ）----
missing_needed = sum(
    1 for r in rows
    if (r.get("lat") is None or r.get("lng") is None) and (r.get("address") or "").strip()
)
if missing_needed > 0:
    with st.status(f"緯度・経度の自動補完中…（{missing_needed} 件）", expanded=False) as status:
        updated = backfill_missing_latlng_and_save(rows, CSV_PATH, GEOCODING_API_KEY)
        if updated > 0:
            st.success(f"CSVに緯度・経度を {updated} 行分 追記しました。")
        status.update(label="地図データを構築しています…")
        geo = build_geo_from_rows(rows)
        status.update(label="地図の準備が完了しました", state="complete")
else:
    geo = build_geo_from_rows(rows)

# ===== フィルタ（※ 地図の下にUIを出すので、ここでは状態と反映だけ） =====
# ジャンル分割（「麺/カレー」「寿司・海鮮」「中華,点心」等を複数タグ化）
def split_genres(s: str):
    s = (s or "").strip()
    if not s:
        return ["（ジャンル未設定）"]
    for sep in ["／", "・", "、", ",", "|", "｜"]:
        s = s.replace(sep, "/")
    tokens = [t.strip() for t in s.split("/") if t.strip()]
    return tokens if tokens else ["（ジャンル未設定）"]

def place_genres(p: dict):
    return split_genres(p.get("genre", ""))

all_genres = sorted({g for p in geo["places"] for g in place_genres(p)})

# --- 初期化（初回のみ） ---
if "show_shapes" not in st.session_state:
    st.session_state.show_shapes = True
if "selected_genres" not in st.session_state:
    st.session_state.selected_genres = list(all_genres)  # ← 初期選択はここだけで設定

# 反映
shapes_for_view = geo["shapes"] if st.session_state.show_shapes else []
sel = set(st.session_state.selected_genres or [])
places_for_view = [p for p in geo["places"] if sel.intersection(place_genres(p))] if sel else []

# ---- 地図描画 ----
DEFAULT_ZOOM = 17
MAP_HEIGHT_PX = 820
html = build_map_html(
    maps_js_api_key=MAPS_JS_API_KEY,
    center=geo["map_center"],
    current_pin=geo["pin_center"],
    places=places_for_view,     # ← ジャンルフィルタ済み
    zoom=DEFAULT_ZOOM,
    height_px=MAP_HEIGHT_PX,
    shapes=shapes_for_view,     # ← 領域ON/OFF反映
)

st.markdown('<div class="map-print">', unsafe_allow_html=True)
st.components.v1.html(html, height=MAP_HEIGHT_PX + 20, scrolling=False)
st.markdown('</div>', unsafe_allow_html=True)

# ---- 地図の“下”にコントロールを配置 ----
st.write("---")
st.subheader("表示オプション")
col1, col2 = st.columns([1, 2], vertical_alignment="top")
with col1:
    st.toggle("🟦 領域を表示する", key="show_shapes")
with col2:
    st.multiselect(
        "ジャンルで表示（複数選択可）",
        options=all_genres,
        key="selected_genres",
        help="例: CSVのジャンルに『麺/カレー』と書くと両方のフィルタにヒットします。",
    )

# ---- ピンの凡例（現在位置 + 色）----
# ---- ピンの凡例（CSVの順番でのみ表示）----
LEGEND_CSV = "color_legend.csv"
legend_rows = load_color_legend_ordered(LEGEND_CSV)  # [{key,label,desc}] 順序保持

def canon_color_key(s: str) -> str:
    if not s:
        return ""
    t = re.sub(r"\s+", "", s.strip()).lower()
    m = re.fullmatch(r"#?([0-9a-f]{6})", t)
    return f"#{m.group(1)}" if m else t  # hex6桁は # を付与、それ以外はそのまま（色名/rgba/…）

# 地図に実際に出ている“色”を正規化して収集（空は除外）
used_colors = {
    canon_color_key(p.get("color"))
    for p in places_for_view
    if (p.get("color") or "").strip()
}

# もし同一点に複数色が混在して“まとめピン色”を使っているなら、
# それも CSV に載せておくのが推奨です（自動追加はしない）。
# 例：legend_rows に key = #F59E0B の行を用意しておく

has_current = bool(geo.get("pin_center"))

# 色ピンSVG（凡例用）
def _normalize_hex(s: str) -> str:
    t = canon_color_key(s)
    return t if t.startswith("#") and len(t) == 7 else t

def _darken_hex(hex_color: str, amount: float = 0.3):
    m = re.fullmatch(r"#([0-9a-f]{6})", (hex_color or "").lower())
    if not m: return None
    num = int(m.group(1), 16)
    r = max(0, int(((num>>16)&255)*(1-amount)))
    g = max(0, int(((num>>8 )&255)*(1-amount)))
    b = max(0, int(((num    )&255)*(1-amount)))
    return f"#{r:02x}{g:02x}{b:02x}"

def make_pin_svg_data_uri(fill: str):
    s = _darken_hex(_normalize_hex(fill)) or fill
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='36' height='54' viewBox='0 0 36 54'>"
        f"<path fill='{fill}' stroke='{s}' d='M18 0c-9.94 0-18 8.06-18 18 0 12 18 36 18 36s18-24 18-36C36 8.06 27.94 0 18 0z'/>"
        "<circle cx='18' cy='18' r='6' fill='#ffffff'/>"
        "</svg>"
    )
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)

# 描画（CSVの行順で、current_pin と “使われている色”だけを表示）
to_render = []
for row in legend_rows:
    key   = (row["key"] or "").strip()
    label = row["label"] or ""
    desc  = row["desc"] or ""

    if key.lower() == "current_pin":
        if not has_current:
            continue
        to_render.append({
            "icon_src": "https://maps.google.com/mapfiles/ms/icons/blue-dot.png",  # 現在位置アイコン
            "w": 20, "h": 20,
            "label": label or "現在位置",
            "desc":  desc,
        })
    else:
        key_norm = canon_color_key(key)
        if key_norm not in used_colors:
            continue  # CSVにあるが、今は使っていない色 → 出さない
        to_render.append({
            "icon_src": make_pin_svg_data_uri(key_norm),
            "w": 18, "h": 27,
            "label": label or key.upper(),
            "desc":  desc,
        })

if to_render:
    st.write("---")
    st.subheader("ピンの色の凡例")
    cols = st.columns(2)
    for i, it in enumerate(to_render):
        safe_label = _html.escape(it["label"])
        safe_desc  = _html.escape(it["desc"])
        with cols[i % 2]:
            st.markdown(
                f"""
<div class="legend-item">
  <img src="{it['icon_src']}" width="{it['w']}" height="{it['h']}" class="legend-icon"/>
  <div class="legend-text">
    <div class="legend-title">{safe_label}</div>
    {f"<div class='legend-desc'>{safe_desc}</div>" if safe_desc else ""}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
else:
    st.info("表示中のピンに対応する凡例はありません。")

# ---- QR（APP_BASE_URL が設定されている時だけ表示）----
show_qr_simple()
