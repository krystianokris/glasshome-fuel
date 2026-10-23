"""Google Static Maps geometry and image transport. No key leaves Home Assistant."""
import base64
import math
from urllib.parse import urlencode

WIDTH = HEIGHT = 640
MAX_IMAGE_BYTES = 2_000_000
EARTH_RADIUS = 6378137

class MapError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def coordinate(lat, lon):
    if isinstance(lat, bool) or isinstance(lon, bool):
        raise MapError("invalid_map_location")
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise MapError("invalid_map_location") from None
    if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 85 or abs(lon) > 180:
        raise MapError("invalid_map_location")
    return lat, lon

def world(lat, lon):
    sine = math.sin(math.radians(lat))
    return ((lon + 180) / 360, .5 - math.log((1 + sine) / (1 - sine)) / (4 * math.pi))

def location(x, y):
    return (math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y)))), x * 360 - 180)

def viewport(home, stations, radius, unit):
    home = coordinate(home["latitude"], home["longitude"])
    if not isinstance(stations, list) or len(stations) > 20:
        raise MapError("invalid_map_location")
    cleaned, ids = [], set()
    for station in stations:
        identifier = str(station["id"])
        if not identifier or len(identifier) > 100 or identifier in ids:
            raise MapError("invalid_map_location")
        lat, lon = coordinate(station["latitude"], station["longitude"])
        cleaned.append({"id": identifier, "latitude": lat, "longitude": lon})
        ids.add(identifier)
    if unit not in ("mi", "km") or isinstance(radius, bool) or not 1 <= float(radius) <= 100:
        raise MapError("invalid_map_location")
    points = [world(*home)] + [world(s["latitude"], s["longitude"]) for s in cleaned]
    xmin, xmax = min(p[0] for p in points), max(p[0] for p in points)
    ymin, ymax = min(p[1] for p in points), max(p[1] for p in points)
    # Fit home + displayed stations, excluding the radius. Reserve bottom space
    # for Google's original attribution, which must remain fully visible.
    zoom = 13
    while zoom > 1 and ((xmax-xmin)*256*2**zoom > 512 or (ymax-ymin)*256*2**zoom > 448):
        zoom -= 1
    scale = 256 * 2**zoom
    cx, cy = (xmin+xmax)/2, (ymin+ymax)/2 + 32/scale
    latitude, longitude = location(cx, cy)
    def pixel(point):
        return {"x": (point[0]-cx)*scale + WIDTH/2, "y": (point[1]-cy)*scale + HEIGHT/2}
    pins = [{"id": s["id"], **pixel(point)} for s, point in zip(cleaned, points[1:])]
    metres_per_pixel = 2*math.pi*EARTH_RADIUS*math.cos(math.radians(home[0]))/scale
    return {"width": WIDTH, "height": HEIGHT, "zoom": zoom,
            "centre": {"latitude": latitude, "longitude": longitude},
            "home": pixel(points[0]), "pins": pins,
            "radiusPixels": float(radius)*(1609.34 if unit == "mi" else 1000)/metres_per_pixel}

def request_parameters(view, api_key):
    return [
        ("center", f'{view["centre"]["latitude"]:.7f},{view["centre"]["longitude"]:.7f}'),
        ("zoom", str(view["zoom"])), ("size", "640x640"), ("scale", "1"),
        ("format", "png32"), ("maptype", "roadmap"),
        ("style", "element:geometry|color:0x17263d"),
        ("style", "element:labels.text.fill|color:0xabc0d6"),
        ("style", "element:labels.text.stroke|color:0x17263d"),
        ("style", "feature:road|element:geometry|color:0x34465e"),
        ("style", "feature:road.highway|element:geometry|color:0x52677d"),
        ("style", "feature:water|element:geometry|color:0x0e1a2d"),
        ("style", "feature:poi|element:labels|visibility:off"),
        ("key", api_key),
    ]

async def render_map(session, api_key, home, stations, radius, unit):
    if not api_key:
        raise MapError("google_key_required")
    view = viewport(home, stations, radius, unit)
    # A fixed HTTPS endpoint; callers cannot supply a host, URL or credential.
    url = "https://maps.googleapis.com/maps/api/staticmap?" + urlencode(request_parameters(view, api_key))
    try:
        async with session.get(url, timeout=30) as response:
            if response.status in (401, 403):
                raise MapError("google_request_denied")
            if response.status != 200:
                raise MapError("google_map_unavailable")
            if not response.headers.get("Content-Type", "").lower().startswith("image/png"):
                raise MapError("google_map_unavailable")
            chunks, length = [], 0
            async for chunk in response.content.iter_chunked(65536):
                length += len(chunk)
                if length > MAX_IMAGE_BYTES:
                    raise MapError("google_map_unavailable")
                chunks.append(chunk)
            image = b"".join(chunks)
            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise MapError("google_map_unavailable")
    except MapError:
        raise
    except Exception:
        # aiohttp errors can include the request URL/key. Return only a code.
        raise MapError("google_map_unavailable") from None
    return {**view, "image": "data:image/png;base64," + base64.b64encode(image).decode("ascii")}
