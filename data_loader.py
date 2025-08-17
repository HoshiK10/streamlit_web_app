import csv
import os
import re
import math
import requests
import streamlit as st
from typing import List, Dict, Tuple, Optional
from html import escape
from collections import Counter

# 必須は据え置き（新列は任意）
REQ_MIN = {"店名", "住所"}
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

def _normalize_color_key(s: str) -> str:
    s = (s or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"\s+", "", s)  # rgb( 1, 2, 3 ) → rgb(1,2,3)
    if re.fullmatch(r"[0-9a-f]{6}", s):  # "ff0000" → "#ff0000"
        s = "#" + s
    return s

def load_color_legend(path: str) -> dict:
    """
    color_legend.csv を読み、{normalized_color: {label, desc}} を返す。
    列: 色,ラベル,説明
    """
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            key = _normalize_color_key((r.get("色") or ""))
            if not key:
                continue
            out[key] = {
                "label": (r.get("ラベル") or "").strip(),
                "desc": (r.get("説明") or "").strip(),
            }
    return out

def _safe_float(v, default=0.0) -> float:
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(v)
    except Exception:
        return default

def _meters_to_deg(lat_deg: float, north_m: float, east_m: float):
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
    """CSV を読み、内部標準キーに正規化して返す。列順は問わない。"""
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
                # 形状検出や元の店名保持
                "raw_name": (row.get("店名") or "").strip(),
                "name":     (row.get("店名") or "").strip(),

                # 新列
                "genre":    (row.get("ジャンル") or "").strip(),
                "price":    (row.get("価格帯") or "").strip(),
                "color":    (row.get("色") or "").strip(),

                # 従来の列
                "desc":     (row.get("説明") or "").strip(),
                "website":  (row.get("URL") or "").strip(),
                "address":  (row.get("住所") or "").strip(),
                "lat":      (None if (row.get("緯度") or "").strip() == "" else _safe_float(row.get("緯度"))),
                "lng":      (None if (row.get("経度") or "").strip() == "" else _safe_float(row.get("経度"))),
                "north_offset_m": _safe_float(row.get("南北補正"), 0.0),
                "east_offset_m":  _safe_float(row.get("東西補正"), 0.0),
            })
        return rows

def _save_rows_to_csv(rows: List[Dict], path: str) -> None:
    """新フォーマット順でCSVを書き戻す（緯度・経度＝補正前の素の座標）。"""
    fieldnames = ["店名", "ジャンル", "価格帯", "色", "説明", "URL", "住所", "緯度", "経度", "南北補正", "東西補正"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "店名": r.get("raw_name") or r.get("name", ""),
                "ジャンル": r.get("genre", ""),
                "価格帯": r.get("price", ""),
                "色": r.get("color", ""),
                "説明": r.get("desc", ""),
                "URL": r.get("website", ""),
                "住所": r.get("address", ""),
                "緯度": ("" if r.get("lat") is None else f"{float(r['lat']):.7f}"),
                "経度": ("" if r.get("lng") is None else f"{float(r['lng']):.7f}"),
                "南北補正": r.get("north_offset_m", 0.0),
                "東西補正": r.get("east_offset_m", 0.0),
            })

def backfill_missing_latlng_and_save(rows: List[Dict], path: str, api_key: str) -> int:
    """緯度・経度が空の行のみ住所でジオコーディングし、rowsを更新。更新があればCSV書き戻し。"""
    updated = 0
    for r in rows:
        if (r["lat"] is None or r["lng"] is None) and r["address"]:
            base = _geocode(r["address"], api_key)
            if base:
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

# 形状の行名パターン（左上NN／右下NN）
_SHAPE_UL_RE = re.compile(r"^左上(\d+)$")
_SHAPE_LR_RE = re.compile(r"^右下(\d+)$")

def _rotate_east_north(east_m: float, north_m: float, deg: float):
    r = math.radians(deg)
    xr = east_m * math.cos(r) - north_m * math.sin(r)
    yr = east_m * math.sin(r) + north_m * math.cos(r)
    return xr, yr

def _build_shapes(rows: List[Dict]):
    """左上NN／右下NN のペアから領域（四角/楕円/回転四角）を生成。
       形状タイプは『左上NN の URL 列』で指定（四角/rect/rectangle/楕円/ellipse + 任意回転）。
       吹き出しは「左上の説明（強調）」「右下の説明（薄め）」を表示。
    """
    ul_map, lr_map = {}, {}
    for r in rows:
        m1 = _SHAPE_UL_RE.match(r.get("raw_name", ""))
        m2 = _SHAPE_LR_RE.match(r.get("raw_name", ""))
        if m1: ul_map[m1.group(1)] = r
        elif m2: lr_map[m2.group(1)] = r

    shapes, warnings = [], []
    palette = [
        {"stroke": "#3B82F6", "fill": "#3B82F6", "label": "#1E40AF"},  # 青
        {"stroke": "#F59E0B", "fill": "#F59E0B", "label": "#9A3412"},  # 橙
        {"stroke": "#10B981", "fill": "#10B981", "label": "#065F46"},  # 緑
        {"stroke": "#EF4444", "fill": "#EF4444", "label": "#7F1D1D"},  # 赤
        {"stroke": "#8B5CF6", "fill": "#8B5CF6", "label": "#4C1D95"},  # 紫
    ]

    for key in sorted(set(ul_map.keys()) | set(lr_map.keys())):
        ul = ul_map.get(key); lr = lr_map.get(key)
        if not ul or not lr:
            warnings.append(f"組 {key}: 左上／右下 のいずれかがありません。")
            continue

        ul_adj = _apply_offset_if_possible(ul.get("lat"), ul.get("lng"),
                                           ul.get("north_offset_m", 0.0), ul.get("east_offset_m", 0.0))
        lr_adj = _apply_offset_if_possible(lr.get("lat"), lr.get("lng"),
                                           lr.get("north_offset_m", 0.0), lr.get("east_offset_m", 0.0))
        if not ul_adj or not lr_adj:
            warnings.append(f"組 {key}: 座標が未設定のためスキップ。")
            continue

        north = max(ul_adj["lat"], lr_adj["lat"])
        south = min(ul_adj["lat"], lr_adj["lat"])
        west  = min(ul_adj["lng"], lr_adj["lng"])
        east  = max(ul_adj["lng"], lr_adj["lng"])

        shape_spec = (ul.get("website") or "").strip()
        spec_lower = shape_spec.lower()

        rot_deg = 0.0
        m = re.search(r'(?:回転|rotate)?\s*([\-]?\d+(?:\.\d+)?)\s*(?:度|°|deg)?', shape_spec)
        if m:
            try: rot_deg = float(m.group(1))
            except Exception: rot_deg = 0.0

        is_rect    = ("四角" in shape_spec) or ("rect" in spec_lower) or ("rectangle" in spec_lower)
        is_ellipse = ("楕円" in shape_spec) or ("ellipse" in spec_lower)

        idx = int(key) if key.isdigit() else 0
        pal = palette[idx % len(palette)]

        label_text = (ul.get("desc") or "").strip()
        sub_text   = (lr.get("desc") or "").strip()
        info_html = (
            '<div style="font-size:14px;line-height:1.6">'
            f'<div style="font-size:16px;font-weight:bold;color:#333;">{escape(label_text or f"領域 {key}")}</div>'
            f'<div style="font-size:13px;color:#666;margin-top:4px;">{escape(sub_text)}</div>'
            '</div>'
        )

        if is_ellipse:
            center_lat = (north + south) / 2.0
            center_lng = (east + west) / 2.0
            m_per_deg_lat = 111_320.0
            m_per_deg_lng = 111_320.0 * math.cos(math.radians(center_lat))
            radius_n_m = max(1.0, abs(north - south) * 0.5 * m_per_deg_lat)
            radius_e_m = max(1.0, abs(east  - west ) * 0.5 * m_per_deg_lng)

            shapes.append({
                "type": "ellipse",
                "center": {"lat": center_lat, "lng": center_lng},
                "radiusNorthM": radius_n_m,
                "radiusEastM":  radius_e_m,
                "rotationDeg": rot_deg,
                "fillOpacity": 0.18,
                "strokeColor": pal["stroke"],
                "fillColor": pal["fill"],
                "label": label_text,
                "labelColor": pal["label"],
                "labelFontSize": 16,
                "labelAnchor": "bottom-right",
                "labelInsetM": 60,
                "info": info_html,
            })
        else:
            center_lat = (north + south) / 2.0
            center_lng = (east + west) / 2.0
            m_per_deg_lat = 111_320.0
            m_per_deg_lng = 111_320.0 * math.cos(math.radians(center_lat))
            half_h_m = max(1.0, abs(north - south) * 0.5 * m_per_deg_lat)
            half_w_m = max(1.0, abs(east  - west ) * 0.5 * m_per_deg_lng)

            if abs(rot_deg) < 1e-6:
                shapes.append({
                    "type": "rect",
                    "north": north, "south": south, "east": east, "west": west,
                    "fillOpacity": 0.18,
                    "strokeColor": pal["stroke"],
                    "fillColor": pal["fill"],
                    "label": label_text,
                    "labelColor": pal["label"],
                    "labelFontSize": 16,
                    "labelAnchor": "bottom-right",
                    "labelInsetM": 30,
                    "info": info_html,
                })
            else:
                corners_local = [
                    (+half_w_m, +half_h_m),  # 右上
                    (-half_w_m, +half_h_m),  # 左上
                    (-half_w_m, -half_h_m),  # 左下
                    (+half_w_m, -half_h_m),  # 右下
                ]
                paths = []
                for ex, ny in corners_local:
                    exr, nyr = _rotate_east_north(ex, ny, rot_deg)
                    dlat, dlng = _meters_to_deg(center_lat, nyr, exr)
                    paths.append({"lat": center_lat + dlat, "lng": center_lng + dlng})

                inset = 40.0
                ex_lb, ny_lb = _rotate_east_north(+half_w_m - inset, -half_h_m + inset, rot_deg)
                dlat_lb, dlng_lb = _meters_to_deg(center_lat, ny_lb, ex_lb)
                label_pos = {"lat": center_lat + dlat_lb, "lng": center_lng + dlng_lb}

                shapes.append({
                    "type": "poly",
                    "paths": paths,
                    "fillOpacity": 0.18,
                    "strokeColor": pal["stroke"],
                    "fillColor": pal["fill"],
                    "label": label_text,
                    "labelColor": pal["label"],
                    "labelFontSize": 16,
                    "labelPos": label_pos,
                    "info": info_html,
                })

    return shapes, warnings

def build_geo_from_rows(rows: List[Dict]) -> Dict:
    if len(rows) < 2:
        raise RuntimeError("行数不足")

    map_center_row = rows[0]
    pin_center_row = rows[1] if len(rows) >= 2 else None
    other_rows     = rows[2:] if len(rows) >= 3 else []

    map_center = _apply_offset_if_possible(
        map_center_row.get("lat"), map_center_row.get("lng"),
        map_center_row.get("north_offset_m", 0.0), map_center_row.get("east_offset_m", 0.0)
    )
    if not map_center:
        raise RuntimeError("地図中心の緯度経度が未設定です。CSVを確認してください。")

    pin_center = None
    if pin_center_row:
        pin_center = _apply_offset_if_possible(
            pin_center_row.get("lat"), pin_center_row.get("lng"),
            pin_center_row.get("north_offset_m", 0.0), pin_center_row.get("east_offset_m", 0.0)
        )

    shapes, shape_warnings = _build_shapes(other_rows)

    places, place_warnings = [], []
    skipped_missing = 0
    shape_rows_count = 0

    for r in other_rows:
        raw_name = r.get("raw_name","")
        if _SHAPE_UL_RE.match(raw_name) or _SHAPE_LR_RE.match(raw_name):
            shape_rows_count += 1
            continue

        adj = _apply_offset_if_possible(
            r.get("lat"), r.get("lng"),
            r.get("north_offset_m", 0.0), r.get("east_offset_m", 0.0)
        )
        if not adj:
            skipped_missing += 1
            continue

        lat, lng = adj["lat"], adj["lng"]
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            skipped_missing += 1
            continue

        places.append({
            "name": r.get("name") or "(名称未設定)",
            "website": r.get("website", ""),
            "desc": r.get("desc", ""),
            "color": r.get("color", ""),   # ← 色
            "genre": r.get("genre", ""),   # ← ジャンル
            "price": r.get("price", ""),   # ← 価格帯
            "lat": lat,
            "lng": lng,
        })

    # 重複情報（参考用途・UIには出さない）
    key = lambda p: (round(p["lat"], 6), round(p["lng"], 6))
    dup_counter = Counter(key(p) for p in places)
    dup_notes = [f"{cnt} 件が同座標（{lat:.6f},{lng:.6f}）"
                 for (lat, lng), cnt in dup_counter.items() if cnt > 1]

    return {
        "map_center": map_center,
        "pin_center": pin_center,
        "places": places,
        "shapes": shapes,
        "shape_warnings": shape_warnings,
        "place_warnings": place_warnings,
        "place_stats": {
            "rows_total": len(other_rows),
            "shape_rows": shape_rows_count,
            "places_kept": len(places),
            "skipped_missing": skipped_missing,
            "dup_notes": dup_notes,
        },
    }
