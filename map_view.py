# map_view.py
import json

def build_map_html(
    maps_js_api_key: str,
    center: dict,                 # {"lat":..., "lng":...}
    current_pin: dict | None,     # None or {"lat":..., "lng":...}
    places: list[dict],           # [{name, website, desc, lat, lng}]
    zoom: int = 13,
    height_px: int = 700,
) -> str:
    payload = {
        "center": center,
        "zoom": zoom,
        "current_pin": current_pin,
        "places": places,
    }
    payload_json = json.dumps(payload)

    return f"""
<div id="map" style="width:100%;height:{height_px}px;"></div>
<script>
const payload = {payload_json};

function initMap() {{
  const map = new google.maps.Map(document.getElementById('map'), {{
    center: payload.center,
    zoom: payload.zoom,
    mapTypeControl: true,
    streetViewControl: false
  }});

  const info = new google.maps.InfoWindow();

  // 店舗ピン
  payload.places.forEach((p) => {{
    const pos = {{lat: p.lat, lng: p.lng}};
    const marker = new google.maps.Marker({{ position: pos, map: map, title: p.name }});

    const link = p.website ? `<a href="${{p.website}}" target="_blank" rel="noopener">食べログURL</a>` : "";

    const html = `
      <div style="font-size:14px;line-height:1.6">
        <div style="font-size:16px;font-weight:bold;color:#333;">${{p.name}}</div>
        <div style="font-size:13px;color:#666;margin-top:4px;">${{p.desc || ""}}</div>
        <div style="margin-top:6px">${{link}}</div>
      </div>
    `;

    marker.addListener("click", () => {{
      info.setContent(html);
      info.open({{anchor: marker, map}});
    }});
  }});

  // 現在位置ピン（大きめ青ピン＋バウンド）
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
<script async src="https://maps.googleapis.com/maps/api/js?key={maps_js_api_key}&callback=initMap"></script>
"""
