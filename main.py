import streamlit as st
from data_loader import (
    load_rows_from_csv,
    backfill_missing_latlng_and_save,
    build_geo_from_rows,
    load_color_legend,
)
from map_view import build_map_html
from qr_utils import show_qr_simple
import urllib.parse
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
LEGEND_CSV = "color_legend.csv"
legend_map = load_color_legend(LEGEND_CSV)

def _norm_color(c: str | None) -> str:
    import re
    s = (c or "").strip().lower()
    if not s:
        return "#ef4444"  # デフォルト赤（map_view 側に合わせる）
    s = re.sub(r"\s+", "", s)
    if re.fullmatch(r"[0-9a-f]{6}", s):
        s = "#" + s
    return s

# いま表示中の店舗から使用色を収集
used_colors = {_norm_color(p.get("color")) for p in places_for_view}

# 同一点に複数色が混在する場合は「まとめピン色(#F59E0B)」を追加
from collections import defaultdict
groups = defaultdict(list)
for p in places_for_view:
    key = (round(p["lat"], 6), round(p["lng"], 6))
    groups[key].append(_norm_color(p.get("color")))
for cols in groups.values():
    if len(cols) >= 2 and len(set(cols)) >= 2:
        used_colors.add("#f59e0b")

has_current = bool(geo.get("pin_center"))
has_colors  = bool(used_colors)

if has_current or has_colors:
    st.write("---")
    st.subheader("ピンの色の凡例")

    # 地図ピンと同じ形の SVG を凡例でも使う（色ピン用）
    import urllib.parse, re
    def _normalize_hex(s: str) -> str:
        ss = (s or "").strip().lower()
        ss = re.sub(r"\s+", "", ss)
        m = re.fullmatch(r"#?([0-9a-f]{6})", ss)
        return f"#{m.group(1)}" if m else ss
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

    # ---- 一覧アイテムを作る（現在位置→色ピンの順）----
    legend_items = []

    if has_current:
        cur_meta  = legend_map.get("current_pin", {})
        cur_label = cur_meta.get("label") or cur_meta.get("ラベル") or "現在位置"
        cur_desc  = cur_meta.get("desc")  or cur_meta.get("説明") or ""
        legend_items.append({
            "kind": "current",
            "icon_src": "https://maps.google.com/mapfiles/ms/icons/blue-dot.png",  # 地図と同じ青丸
            "label": cur_label,
            "desc":  cur_desc,
            "w": 20, "h": 20,
        })

    if has_colors:
        for color in sorted(used_colors):
            meta  = legend_map.get(color, {})
            label = meta.get("label") or meta.get("ラベル") or color.upper()
            desc  = meta.get("desc")  or meta.get("説明") or ""
            legend_items.append({
                "kind": "color",
                "icon_src": make_pin_svg_data_uri(color),  # 地図と同じピン形
                "label": label,
                "desc":  desc,
                "w": 18, "h": 27,
            })

    # ---- 2カラムで描画（現在位置も同じ一覧に混ぜる）----
    cols = st.columns(2)
    for i, it in enumerate(legend_items):
        safe_label = _html.escape(str(it["label"]))
        safe_desc  = _html.escape(str(it["desc"]))
        with cols[i % 2]:
            st.markdown(
                f"""
<div style="display:flex;align-items:flex-start;margin:10px 0">
  <img src="{it['icon_src']}" width="{it['w']}" height="{it['h']}"
       style="flex:0 0 auto;display:inline-block;margin:2px 10px 0 2px"/>
  <div style="line-height:1.35">
    <div style="font-weight:700;color:#333">{safe_label}</div>
    {f"<div style='color:#666;font-size:13px;white-space:pre-wrap'>{safe_desc}</div>" if safe_desc else ""}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )
else:
    st.info("表示中のピンに対応する凡例はありません。")

# ---- QR（APP_BASE_URL が設定されている時だけ表示）----
show_qr_simple()
