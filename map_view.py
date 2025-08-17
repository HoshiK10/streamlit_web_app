import json

def build_map_html(
    maps_js_api_key: str,
    center: dict,
    current_pin: dict | None,
    places: list[dict],
    zoom: int = 13,
    height_px: int = 700,
    shapes: list[dict] | None = None,
) -> str:
    """
    - places の各要素: {name, desc, website, color, genre, price, lat, lng, ...}
      * color は #RRGGBB / 色名 / rgb()/rgba() など CSS 色指定（空欄可）
    - shapes: rect / ellipse / poly をサポート（data_loader 側で生成）
    """
    payload = {
        "center": center,
        "zoom": zoom,
        "current_pin": current_pin,
        "places": places,
        "shapes": shapes or [],
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    template = r"""
<div id="map" style="width:100%;height:__HEIGHT__px;"></div>
<script>
const payload = __PAYLOAD__;

// === ユーティリティ ===
function escapeHtml(s){
  return String(s ?? "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}
function escapeAttr(s){
  return String(s ?? "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}
function isHttpUrl(u){
  return typeof u === "string" && /^https?:\/\//i.test((u||"").trim());
}
function darkenColor(hex, amount=0.25){
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex||"").trim());
  if (!m) return null;
  const num = parseInt(m[1], 16);
  let r=(num>>16)&255, g=(num>>8)&255, b=num&255;
  r=Math.max(0,Math.floor(r*(1-amount)));
  g=Math.max(0,Math.floor(g*(1-amount)));
  b=Math.max(0,Math.floor(b*(1-amount)));
  return "#" + ((1<<24)+(r<<16)+(g<<8)+b).toString(16).slice(1);
}
function makePinSvg(fill="#EF4444", stroke=null){
  const s = stroke || darkenColor(fill,0.3) || fill;
  const svg = `
<svg xmlns="http://www.w3.org/2000/svg" width="36" height="54" viewBox="0 0 36 54">
  <path fill="${fill}" stroke="${s}" d="M18 0c-9.94 0-18 8.06-18 18 0 12 18 36 18 36s18-24 18-36C36 8.06 27.94 0 18 0z"/>
  <circle cx="18" cy="18" r="6" fill="#ffffff"/>
</svg>`;
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}

// === 図形ユーティリティ ===
function metersToLatLngDelta(latDeg, northM, eastM){
  const mPerDegLat = 111320.0;
  const mPerDegLng = 111320.0 * Math.cos(latDeg * Math.PI/180);
  return { dlat: northM / mPerDegLat, dlng: mPerDegLng ? (eastM / mPerDegLng) : 0 };
}
function createEllipsePath(center, radiusNorthM, radiusEastM, rotationDeg=0, points=64){
  const path = [];
  const rot = rotationDeg * Math.PI/180;
  for (let i=0; i<points; i++){
    const theta = (i/points) * 2*Math.PI;
    const x = radiusEastM * Math.cos(theta);
    const y = radiusNorthM * Math.sin(theta);
    const xr = x * Math.cos(rot) - y * Math.sin(rot);
    const yr = x * Math.sin(rot) + y * Math.cos(rot);
    const d = metersToLatLngDelta(center.lat, yr, xr);
    path.push({lat: center.lat + d.dlat, lng: center.lng + d.dlng});
  }
  return path;
}
function groupPlacesByLatLng(places, precision=6){
  const groups = new Map();
  for (const p of places){
    const lat = Number(p.lat), lng = Number(p.lng);
    const key = lat.toFixed(precision) + "," + lng.toFixed(precision);
    if (!groups.has(key)) groups.set(key, { items: [] });
    groups.get(key).items.push(p);
  }
  return Array.from(groups.values());
}

// === メイン ===
function initMap(){
  // ラベルは API ロード後に定義（OverlayView を参照するため）
  class MapLabel extends google.maps.OverlayView {
    constructor(position, text, opts = {}){
      super();
      this.position = position;
      this.text = text;
      this.opts = Object.assign({
        color: "#333", fontSize: 16, fontWeight: "700", halo: true, zIndex: 1000
      }, opts);
      this.div = null;
    }
    onAdd(){
      this.div = document.createElement("div");
      this.div.style.position = "absolute";
      this.div.style.transform = "translate(-50%, -50%)";
      this.div.style.whiteSpace = "nowrap";
      this.div.style.pointerEvents = "none";
      this.div.style.userSelect = "none";
      this.div.style.zIndex = String(this.opts.zIndex);
      this.div.style.color = this.opts.color;
      this.div.style.fontWeight = this.opts.fontWeight;
      this.div.style.fontSize = this.opts.fontSize + "px";
      if (this.opts.halo){
        this.div.style.textShadow = "0 0 3px rgba(255,255,255,0.95), 0 0 6px rgba(255,255,255,0.8)";
      }
      this.div.innerHTML = this.text;
      // ラベルは floatPane（ポリゴンより前、InfoWindow より下）
      this.getPanes().floatPane.appendChild(this.div);
    }
    draw(){
      const proj = this.getProjection();
      if (!proj || !this.div) return;
      const p = proj.fromLatLngToDivPixel(this.position);
      if (p){ this.div.style.left = p.x + "px"; this.div.style.top = p.y + "px"; }
    }
    onRemove(){ if (this.div?.parentNode) this.div.parentNode.removeChild(this.div); this.div = null; }
  }

  const map = new google.maps.Map(document.getElementById('map'), {
    center: payload.center,
    zoom: payload.zoom,
    mapTypeControl: true,
    streetViewControl: false
  });

  const info = new google.maps.InfoWindow({ zIndex: 999999 });

  // ---- 店舗ピン（同一座標を1ピンにまとめ、吹き出し縦並び）----
  const placeGroups = groupPlacesByLatLng(payload.places, 6);
  placeGroups.forEach((g) => {
    const pos = { lat: Number(g.items[0].lat), lng: Number(g.items[0].lng) };

    const colors = Array.from(new Set(g.items.map(it => (it.color || "").trim()).filter(Boolean)));
    const bg = colors.length === 1 ? colors[0] : (g.items.length > 1 ? "#F59E0B" : "#EF4444");
    const icon = {
      url: makePinSvg(bg),
      anchor: new google.maps.Point(18, 52),
      scaledSize: new google.maps.Size(36, 54)
    };

    const marker = new google.maps.Marker({
      position: pos, map,
      title: g.items.length === 1 ? g.items[0].name : `${g.items.length} 件`,
      icon
    });

    let html = "";
    if (g.items.length === 1){
      const p = g.items[0];
      let websiteBlock = "";
      if (p.website){
        websiteBlock = isHttpUrl(p.website)
          ? `<a href="${escapeAttr(p.website)}" target="_blank" rel="noopener">食べログURL</a>`
          : `<div style="font-size:13px;color:#444;white-space:pre-wrap;word-break:break-word;">${escapeHtml(p.website)}</div>`;
      }
      html = `
        <div style="font-size:14px;line-height:1.6">
          <div style="font-size:16px;font-weight:bold;color:#333;">${escapeHtml(p.name)}</div>
          ${p.desc ? `<div style="font-size:13px;color:#666;margin-top:4px;">${escapeHtml(p.desc)}</div>` : ""}
          ${websiteBlock ? `<div style="margin-top:6px">${websiteBlock}</div>` : ""}
        </div>`;
    } else {
      const cards = g.items.map((it) => {
        let websiteBlock = "";
        if (it.website){
          websiteBlock = isHttpUrl(it.website)
            ? `<a href="${escapeAttr(it.website)}" target="_blank" rel="noopener">食べログURL</a>`
            : `<div style="font-size:13px;color:#444;white-space:pre-wrap;word-break:break-word;">${escapeHtml(it.website)}</div>`;
        }
        return `
          <div style="margin:6px 0;">
            <div style="font-size:16px;font-weight:bold;color:#333;">${escapeHtml(it.name)}</div>
            ${it.desc ? `<div style="font-size:13px;color:#666;margin-top:4px;">${escapeHtml(it.desc)}</div>` : ""}
            ${websiteBlock ? `<div style="margin-top:6px">${websiteBlock}</div>` : ""}
          </div>`;
      }).join('<hr style="border:none;border-top:1px solid #eee;margin:8px 0"/>');
      html = `<div style="max-height:220px;overflow:auto;padding-right:4px">${cards}</div>`;
    }

    marker.addListener("click", () => {
      info.setContent(html);
      info.open({ anchor: marker, map });
    });
  });

  // ---- 現在位置ピン ----
  if (payload.current_pin){
    new google.maps.Marker({
      position: payload.current_pin,
      map, title: "現在位置",
      icon: { url: "http://maps.google.com/mapfiles/ms/icons/blue-dot.png",
              scaledSize: new google.maps.Size(50, 50) },
      animation: google.maps.Animation.BOUNCE
    });
  }

  // ---- 領域（矩形・楕円・回転四角）＋ ラベル ----
  (payload.shapes || []).forEach((s) => {
    const commonOpts = {
      strokeColor: s.strokeColor || "#FF0000",
      strokeOpacity: (s.strokeOpacity ?? 0.8),
      strokeWeight: (s.strokeWeight ?? 2),
      fillColor: s.fillColor || "#FF0000",
      fillOpacity: (s.fillOpacity ?? 0.2),
      map
    };
    const labelColor = s.labelColor || commonOpts.strokeColor;
    const anchor = s.labelAnchor || "center";
    const insetM = (s.labelInsetM ?? 20);

    if (s.type === "rect"){
      const bounds = { north: s.north, south: s.south, east: s.east, west: s.west };
      const rect = new google.maps.Rectangle({ ...commonOpts, bounds });
      if (s.info){
        rect.addListener("click", () => {
          const c = { lat: (s.north + s.south)/2, lng: (s.east + s.west)/2 };
          const pos = new google.maps.LatLng(c.lat, c.lng);
          info.setContent(s.info);
          info.setPosition(pos);
          info.open({ map });
        });
      }
      if (s.label){
        const pos = (function rectAnchorLatLng(s, anchor="center", insetM=20){
          let lat, lng;
          if (anchor === "center"){ lat=(s.north+s.south)/2; lng=(s.east+s.west)/2; }
          else if (anchor === "bottom-right"){ lat=s.south; lng=s.east; const d=metersToLatLngDelta(lat, +insetM, -insetM); lat+=d.dlat; lng+=d.dlng; }
          else if (anchor === "top-left"){ lat=s.north; lng=s.west; const d=metersToLatLngDelta(lat, -insetM, +insetM); lat+=d.dlat; lng+=d.dlng; }
          else if (anchor === "top-right"){ lat=s.north; lng=s.east; const d=metersToLatLngDelta(lat, -insetM, -insetM); lat+=d.dlat; lng+=d.dlng; }
          else if (anchor === "bottom-left"){ lat=s.south; lng=s.west; const d=metersToLatLngDelta(lat, +insetM, +insetM); lat+=d.dlat; lng+=d.dlng; }
          else { lat=(s.north+s.south)/2; lng=(s.east+s.west)/2; }
          return new google.maps.LatLng(lat, lng);
        })(s, anchor, insetM);
        const lbl = new MapLabel(pos, s.label, {
          color: labelColor, fontSize: s.labelFontSize || 16, fontWeight: "700", halo: true
        });
        lbl.setMap(map);
      }
    } else if (s.type === "ellipse"){
      const center = s.center;
      const path = createEllipsePath(center, s.radiusNorthM, s.radiusEastM, s.rotationDeg || 0, s.points || 64);
      const poly = new google.maps.Polygon({ ...commonOpts, paths: path });
      if (s.info){
        poly.addListener("click", () => {
          info.setContent(s.info);
          info.setPosition(new google.maps.LatLng(center.lat, center.lng));
          info.open({ map });
        });
      }
      if (s.label){
        const pos = (function ellipseAnchorLatLng(s, anchor="center", insetM=40){
          const c = s.center;
          if (anchor === "center") return new google.maps.LatLng(c.lat, c.lng);
          let eastDir = 0, northDir = 0;
          if (anchor === "bottom-right"){ eastDir=+1; northDir=-1; }
          else if (anchor === "top-right"){ eastDir=+1; northDir=+1; }
          else if (anchor === "bottom-left"){ eastDir=-1; northDir=-1; }
          else if (anchor === "top-left"){ eastDir=-1; northDir=+1; }
          else return new google.maps.LatLng(c.lat, c.lng);
          const a = Math.max(0, (s.radiusEastM  || 0) - insetM);
          const b = Math.max(0, (s.radiusNorthM || 0) - insetM);
          const r = (s.rotationDeg || 0) * Math.PI/180;
          const eastM  = eastDir * a, northM = northDir * b;
          const xr = eastM * Math.cos(r) - northM * Math.sin(r);
          const yr = eastM * Math.sin(r) + northM * Math.cos(r);
          const d = metersToLatLngDelta(c.lat, yr, xr);
          return new google.maps.LatLng(c.lat + d.dlat, c.lng + d.dlng);
        })(s, anchor, insetM);
        const lbl = new MapLabel(pos, s.label, {
          color: labelColor, fontSize: s.labelFontSize || 16, fontWeight: "700", halo: true
        });
        lbl.setMap(map);
      }
    } else if (s.type === "poly"){
      const poly = new google.maps.Polygon({
        ...commonOpts,
        paths: (s.paths || []).map(p => ({lat: p.lat, lng: p.lng}))
      });
      if (s.info){
        const pts = s.paths || [];
        const c = pts.reduce((acc,p)=>({lat:acc.lat+p.lat,lng:acc.lng+p.lng}), {lat:0,lng:0});
        const center = new google.maps.LatLng(c.lat/Math.max(1,pts.length), c.lng/Math.max(1,pts.length));
        poly.addListener("click", () => {
          info.setContent(s.info);
          info.setPosition(center);
          info.open({ map });
        });
      }
      if (s.label){
        let pos = s.labelPos
          ? new google.maps.LatLng(s.labelPos.lat, s.labelPos.lng)
          : (()=>{ const pts=s.paths||[]; const c=pts.reduce((a,p)=>({lat:a.lat+p.lat,lng:a.lng+p.lng}),{lat:0,lng:0}); return new google.maps.LatLng(c.lat/Math.max(1,pts.length), c.lng/Math.max(1,pts.length)); })();
        const offNorthM = s.labelOffsetNorthM || 0;
        const offEastM  = s.labelOffsetEastM  || 0;
        if (offNorthM !== 0 || offEastM !== 0){
          const d = metersToLatLngDelta(pos.lat(), offNorthM, offEastM);
          pos = new google.maps.LatLng(pos.lat() + d.dlat, pos.lng() + d.dlng);
        }
        const lbl = new MapLabel(pos, s.label, {
          color: labelColor, fontSize: s.labelFontSize || 16, fontWeight: "700", halo: true
        });
        lbl.setMap(map);
      }
    }
  });
}

// Streamlit の srcdoc でも確実に呼ばれるように
window.initMap = initMap;
</script>
<script async src="https://maps.googleapis.com/maps/api/js?key=__API_KEY__&callback=initMap"></script>
"""
    html = (
        template
        .replace("__HEIGHT__", str(height_px))
        .replace("__API_KEY__", maps_js_api_key)
        .replace("__PAYLOAD__", payload_json)
    )
    return html
