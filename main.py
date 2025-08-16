# main.py
import streamlit as st
from data_loader import (
    load_rows_from_csv,
    backfill_missing_latlng_and_save,
    build_geo_from_rows,
)
from map_view import build_map_html
from qr_utils import show_qr_simple

DEFAULT_ZOOM = 17
MAP_HEIGHT_PX = 600
CSV_PATH = "places.csv"  # 固定CSV

st.set_page_config(page_title="飲食店マップ（CSV緯度経度／自動補完）", layout="wide")
st.title("🍽 近くの飲食店")

# Secrets（Streamlit Cloudの「Edit secrets」に設定）
MAPS_JS_API_KEY = st.secrets.get("MAPS_JS_API_KEY")
GEOCODING_API_KEY = st.secrets.get("GEOCODING_API_KEY")
if not MAPS_JS_API_KEY or not GEOCODING_API_KEY:
    st.error("Secrets に MAPS_JS_API_KEY / GEOCODING_API_KEY を設定してください。")
    st.stop()

# --- CSV 読み込み（ここは軽いのでローディング不要） ---
rows = load_rows_from_csv(CSV_PATH)
if len(rows) < 2:
    st.error("CSVには最低2行（2行目=地図中心／3行目=現在位置／4行目以降=店舗…）が必要です。")
    st.stop()

# --- 今回ジオコーディングが必要かどうかを事前判定 ---
missing_needed = sum(
    1 for r in rows
    if (r.get("lat") is None or r.get("lng") is None) and (r.get("address") or "").strip()
)

if missing_needed > 0:
    # ★ 不足があるときだけローディングを表示
    with st.status(f"緯度・経度の自動補完中…（{missing_needed} 件）", expanded=False) as status:
        updated_count = backfill_missing_latlng_and_save(rows, CSV_PATH, GEOCODING_API_KEY)
        if updated_count > 0:
            st.success(f"CSVに緯度・経度を {updated_count} 行分 追記しました。")

        status.update(label="地図データを構築しています…")
        geo = build_geo_from_rows(rows)

        status.update(label="地図の準備が完了しました", state="complete")
else:
    # ★ 不足が無いならローディングを一切出さない
    geo = build_geo_from_rows(rows)

# --- 地図描画 ---
html = build_map_html(
    maps_js_api_key=MAPS_JS_API_KEY,
    center=geo["map_center"],       # {"lat":..., "lng":...}
    current_pin=geo["pin_center"],  # None or {"lat":..., "lng":...}
    places=geo["places"],           # [{name, website, desc, lat, lng}]
    zoom=DEFAULT_ZOOM,
    height_px=MAP_HEIGHT_PX,
)

st.subheader("🗺 地図")
st.components.v1.html(html, height=MAP_HEIGHT_PX + 20, scrolling=False)

# --- QR（SecretsにAPP_BASE_URLがある時だけ表示。未設定なら何も出さない） ---
show_qr_simple()
