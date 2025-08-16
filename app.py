import json
import csv
import requests
import math
import os
import streamlit as st

# ページ設定
st.set_page_config(page_title="飲食店マップ（CSV統一形式 / Google Maps）", layout="wide")
st.title("🍴 近所の飲食店マップ")

# ==== APIキー ====
MAPS_JS_API_KEY = st.secrets.get("MAPS_JS_API_KEY")
GEOCODING_API_KEY = st.secrets.get("GEOCODING_API_KEY")
if not MAPS_JS_API_KEY or not GEOCODING_API_KEY:
    st.error("`.streamlit/secrets.toml` に APIキーを設定してください。")
    st.stop()

# ==== 表示設定 ====
DEFAULT_ZOOM   = 17
MAP_HEIGHT_PX  = 700

CSV_PATH = "places.csv"  # 固定読み込み

def safe_float(v, default=0.0):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(v)
    except Exception:
        return default

def meters_to_deg(lat_deg: float, north_m: float, east_m: float):
    """メートル→度換算（緯度により経度換算が変わる）"""
    lat_rad = math.radians(lat_deg)
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = 111_320.0 * math.cos(lat_rad)
    dlat = north_m / m_per_deg_lat
    dlng = east_m / m_per_deg_lng if m_per_deg_lng != 0 else 0.0
    return dlat, dlng

# ---- Geocoding ----
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

@st.cache_data(show_spinner=False)
def geocode_one(address: str, api_key: str):
    try:
        r = requests.get(GEOCODE_URL, params={"address": address, "key": api_key}, timeout=10)
        data = r.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return {"lat": loc["lat"], "lng": loc["lng"]}
    except Exception:
        pass
    return None

# ---- CSV読み込み ----
def read_csv(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} が見つかりません")

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"店名", "住所"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"CSVに必要な列がありません: {required}")

        rows = []
        for row in reader:
            rows.append({
                "name": (row.get("店名") or "").strip(),
                "website": (row.get("URL") or "").strip(),
                "address": (row.get("住所") or "").strip(),
                "desc": (row.get("説明") or "").strip(),   # ← 新列を読み込み
                "north_offset_m": safe_float(row.get("南北補正"), 0.0),
                "east_offset_m":  safe_float(row.get("東西補正"), 0.0),
            })
        return rows

try:
    rows = read_csv(CSV_PATH)
except Exception as e:
    st.error(f"CSV読み込みエラー: {e}")
    st.stop()

if len(rows) < 2:
    st.error("CSVに地図中心・現在位置・店舗データが必要です")
    st.stop()

# ---- 2行目（地図中心）と3行目（現在位置）を特別扱い ----
map_center_row = rows[0]
pin_center_row = rows[1]
store_rows     = rows[2:]

def geocode_with_offset(row):
    base = geocode_one(row["address"], GEOCODING_API_KEY)
    if not base:
        return None
    dlat, dlng = meters_to_deg(base["lat"], row["north_offset_m"], row["east_offset_m"])
    return {"lat": base["lat"] + dlat, "lng": base["lng"] + dlng, "base": base}

# 地図中心
map_center = geocode_with_offset(map_center_row)
if not map_center:
    st.error(f"地図中心の住所をジオコーディングできませんでした: {map_center_row['address']}")
    st.stop()
print(f"[INFO] Map Center: {map_center_row['address']} => {map_center}")

# 現在位置ピン
pin_center = geocode_with_offset(pin_center_row)
if not pin_center:
    print(f"[WARN] Current pin address failed: {pin_center_row['address']}")

# 店舗群
places = []
for r in store_rows:
    g = geocode_with_offset(r)
    if g:
        places.append({**r, "lat": g["lat"], "lng": g["lng"]})

if not places:
    st.warning("有効な店舗がありません")

# ---- ペイロード ----
payload = {
    "center": {"lat": map_center["lat"], "lng": map_center["lng"]},
    "zoom": DEFAULT_ZOOM,
    "current_pin": {"lat": pin_center["lat"], "lng": pin_center["lng"]} if pin_center else None,
    "places": [
        {
            "name": p["name"], "address": p["address"], "website": p["website"], "desc": p["desc"],
            "lat": p["lat"], "lng": p["lng"]
        }
        for p in places
    ],
}
payload_json = json.dumps(payload)

# ---- 地図 ----
map_html = f"""
<div id="map" style="width:100%;height:{MAP_HEIGHT_PX}px;"></div>
<script>
const payload = {payload_json};

function initMap() {{
  const map = new google.maps.Map(document.getElementById('map'), {{
    center: payload.center,
    zoom: payload.zoom
  }});

  const info = new google.maps.InfoWindow();

  // 店舗
  payload.places.forEach((p) => {{
    const pos = {{lat: p.lat, lng: p.lng}};
    const marker = new google.maps.Marker({{ position: pos, map: map, title: p.name }});

    const link = p.website ? `<a href="${{p.website}}" target="_blank" rel="noopener">食べログURL</a>` : "";

    const html = `
      <div style="font-size:14px;line-height:1.6">
        <div style="font-size:16px;font-weight:bold;color:#333;">
          ${{p.name}}
        </div>
        <div style="font-size:13px;color:#666;margin-top:4px;">
          ${{p.desc || ""}}
        </div>
        <div style="margin-top:6px">${{link}}</div>
      </div>
    `;

    marker.addListener("click", () => {{
      info.setContent(html);
      info.open({{anchor: marker, map}});
    }});
  }});

  // 現在位置ピン
  if (payload.current_pin) {{
    new google.maps.Marker({{
      position: payload.current_pin,
      map: map,
      title: "現在位置",
      icon: {{
        url: "http://maps.google.com/mapfiles/ms/icons/blue-dot.png",
        scaledSize: new google.maps.Size(50, 50)
      }},
      animation: google.maps.Animation.BOUNCE
    }});
  }}
}}
</script>
<script async src="https://maps.googleapis.com/maps/api/js?key={MAPS_JS_API_KEY}&callback=initMap"></script>
"""

st.components.v1.html(map_html, height=MAP_HEIGHT_PX + 20, scrolling=False)
