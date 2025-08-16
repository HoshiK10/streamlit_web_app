# data_loader.py
import csv
import os
import math
import requests
import streamlit as st
from typing import List, Dict, Tuple, Optional

# 新フォーマット:
# 店名,説明,URL,住所,緯度,経度,南北補正,東西補正
REQ_MIN = {"店名", "住所"}
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

def _safe_float(v, default=0.0) -> float:
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(v)
    except Exception:
        return default

def _meters_to_deg(lat_deg: float, north_m: float, east_m: float) -> Tuple[float, float]:
    lat_rad = math.radians(lat_deg)
    m_per_deg_lat = 111_320.0
    m_per_deg_lng = 111_320.0 * math.cos(lat_rad)
    dlat = north_m / m_per_deg_lat
    dlng = east_m / m_per_deg_lng if m_per_deg_lng != 0 else 0.0
    return dlat, dlng

@st.cache_data(show_spinner=False)
def _geocode(address: str, api_key: str) -> Optional[Dict[str, float]]:
    if not address:
        return None
    try:
        r = requests.get(GEOCODE_URL, params={"address": address, "key": api_key}, timeout=10)
        data = r.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return {"lat": loc["lat"], "lng": loc["lng"]}
    except Exception:
        pass
    return None

def load_rows_from_csv(path: str) -> List[Dict]:
    """CSV（UTF-8/BOM推奨）を読み、内部標準キーに正規化して返す。列順は問わない。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} が見つかりません。プロジェクト直下に置いてください。")

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = set(reader.fieldnames or [])
        if not REQ_MIN.issubset(headers):
            raise ValueError(f"CSVに必要な列が不足：必須={REQ_MIN} / 実際={headers}")

        rows: List[Dict] = []
        for row in reader:
            rows.append({
                "name":   (row.get("店名") or "").strip(),
                "desc":   (row.get("説明") or "").strip(),
                "website":(row.get("URL") or "").strip(),
                "address":(row.get("住所") or "").strip(),
                "lat":    (None if (row.get("緯度") or "").strip() == "" else _safe_float(row.get("緯度"))),
                "lng":    (None if (row.get("経度") or "").strip() == "" else _safe_float(row.get("経度"))),
                "north_offset_m": _safe_float(row.get("南北補正"), 0.0),
                "east_offset_m":  _safe_float(row.get("東西補正"), 0.0),
            })
        return rows

def _save_rows_to_csv(rows: List[Dict], path: str) -> None:
    """新しい列順でCSVを書き戻す。緯度・経度は「素の座標」を保存。"""
    fieldnames = ["店名", "説明", "URL", "住所", "緯度", "経度", "南北補正", "東西補正"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "店名": r.get("name", ""),
                "説明": r.get("desc", ""),
                "URL": r.get("website", ""),
                "住所": r.get("address", ""),
                # 保存するのは補正前（素）の緯度・経度
                "緯度": ("" if r.get("lat") is None else f"{float(r['lat']):.7f}"),
                "経度": ("" if r.get("lng") is None else f"{float(r['lng']):.7f}"),
                "南北補正": r.get("north_offset_m", 0.0),
                "東西補正": r.get("east_offset_m", 0.0),
            })

def backfill_missing_latlng_and_save(rows: List[Dict], path: str, api_key: str) -> int:
    """
    緯度・経度が空の行のみ住所でジオコーディングし、rowsを更新。
    1件以上更新があれば新しい列順でCSVを書き戻す。
    戻り値：更新件数
    """
    updated = 0
    for r in rows:
        if (r["lat"] is None or r["lng"] is None) and r["address"]:
            base = _geocode(r["address"], api_key)
            if base:
                # CSVには補正前（素の）座標を保存
                r["lat"] = base["lat"]
                r["lng"] = base["lng"]
                updated += 1

    if updated > 0:
        _save_rows_to_csv(rows, path)
    return updated

def _apply_offset_if_possible(lat: Optional[float], lng: Optional[float],
                              north_m: float, east_m: float) -> Optional[Dict[str, float]]:
    if lat is None or lng is None:
        return None
    dlat, dlng = _meters_to_deg(lat, north_m, east_m)
    return {"lat": lat + dlat, "lng": lng + dlng}

def build_geo_from_rows(rows: List[Dict]) -> Dict:
    """
    rows（2行目=地図中心, 3行目=現在位置, 4行目〜店舗）から
    map_center / pin_center / places を構築。
    緯度経度は backfill 済み（またはCSVに入っている）前提。
    """
    if len(rows) < 2:
        raise RuntimeError("行数不足")

    map_center_row = rows[0]
    pin_center_row = rows[1] if len(rows) >= 2 else None
    store_rows     = rows[2:] if len(rows) >= 3 else []

    # 地図の中心（表示時に補正を加算）
    map_center = _apply_offset_if_possible(
        map_center_row.get("lat"), map_center_row.get("lng"),
        map_center_row.get("north_offset_m", 0.0), map_center_row.get("east_offset_m", 0.0)
    )
    if not map_center:
        raise RuntimeError("地図中心の緯度経度が未設定です。CSVを確認してください。")

    # 現在位置ピン（表示時に補正を加算）
    pin_center = None
    if pin_center_row:
        pin_center = _apply_offset_if_possible(
            pin_center_row.get("lat"), pin_center_row.get("lng"),
            pin_center_row.get("north_offset_m", 0.0), pin_center_row.get("east_offset_m", 0.0)
        )

    # 店舗（表示時に補正を加算）
    places = []
    for r in store_rows:
        adj = _apply_offset_if_possible(
            r.get("lat"), r.get("lng"),
            r.get("north_offset_m", 0.0), r.get("east_offset_m", 0.0)
        )
        if not adj:
            continue
        places.append({
            "name": r.get("name") or "(名称未設定)",
            "website": r.get("website", ""),
            "desc": r.get("desc", ""),
            "lat": adj["lat"],
            "lng": adj["lng"],
        })

    return {"map_center": map_center, "pin_center": pin_center, "places": places}
