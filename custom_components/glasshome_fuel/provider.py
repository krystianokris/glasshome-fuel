"""Provider adapters and search logic. No Home Assistant imports: independently testable."""
import asyncio
import math
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, quote
from zoneinfo import ZoneInfo

ASDA_URL = "https://storelocator.asda.com/fuel_prices_data.json"
MAX_AGE_HOURS = 48

class FuelError(Exception):
    pass

def distance_km(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2-lat1, math.radians(b[1]-a[1])
    x = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(x)))

def coordinates(lat, lon):
    if isinstance(lat, bool) or isinstance(lon, bool) or lat is None or lon is None:
        raise ValueError("Invalid coordinates")
    lat, lon = float(lat), float(lon)
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid coordinates")
    return lat, lon

class AsdaAdapter:
    country = "GB"
    currency = "GBP"
    price_unit = "p/L"
    source = "Asda public feed"
    coverage = "Asda only — not all UK stations"
    url = ASDA_URL

    def normalize(self, payload, now=None):
        now = now or datetime.now(timezone.utc)
        try:
            updated = datetime.strptime(payload["last_updated"], "%d/%m/%Y %H:%M:%S").replace(tzinfo=ZoneInfo("Europe/London"))
            age = (now-updated).total_seconds()/3600
            if age < -1 or age > MAX_AGE_HOURS:
                raise FuelError("Asda feed is outdated or has an invalid timestamp. Prices hidden.")
            if not isinstance(payload["stations"], list) or not payload["stations"]:
                raise ValueError("Missing stations")
        except (KeyError, TypeError, ValueError) as error:
            raise FuelError("Invalid Asda feed format or timestamp.") from error
        stations, seen = [], set()
        for item in payload["stations"]:
            try:
                lat, lon = coordinates(item["location"]["latitude"], item["location"]["longitude"])
                identifier = str(item["site_id"])
                if not identifier or identifier in seen:
                    continue
                prices = {}
                for key in ("E10", "E5", "B7", "SDV"):
                    value = item.get("prices", {}).get(key)
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 < value < 1000:
                        prices[key] = value
                if not prices:
                    continue
                stations.append({"id": identifier, "brand": str(item.get("brand", "Asda")), "address": str(item.get("address", "")), "postcode": str(item.get("postcode", "")), "latitude": lat, "longitude": lon, "prices": prices})
                seen.add(identifier)
            except (KeyError, TypeError, ValueError):
                continue
        if not stations:
            raise FuelError("No valid stations in Asda feed.")
        return {"stations": stations, "updated": updated.isoformat(), "source": self.source, "coverage": self.coverage, "sourceUrl": self.url, "currency": self.currency, "priceUnit": self.price_unit}

# New countries implement the same normalize() contract and explicitly declare units.
# They must be registered only after their actual source and licensing are verified.
ADAPTERS = {"GB": AsdaAdapter()}

class FuelSearch:
    def __init__(self, get_json, clock=time.monotonic, now=lambda: datetime.now(timezone.utc)):
        self.get_json, self.clock, self.now = get_json, clock, now
        self.cache = None
        self.locations = {}
        self.lock = asyncio.Lock()

    async def resolve(self, query, country):
        key = (query.strip().casefold(), country)
        cached = self.locations.get(key)
        if cached and self.clock()-cached[0] < 86400:
            return cached[1]
        postcode = re.sub(r"\s+", "", query).upper()
        if country == "GB" and re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}", postcode):
            data = await self.get_json("https://api.postcodes.io/postcodes/" + quote(postcode))
            result = data.get("result")
            if not result:
                raise FuelError("UK postcode not found.")
            lat, lon = coordinates(result.get("latitude"), result.get("longitude"))
            centre = {"latitude": lat, "longitude": lon, "label": result["postcode"] + " · " + str(result.get("admin_district") or "UK")}
        else:
            data = await self.get_json("https://geocoding-api.open-meteo.com/v1/search?" + urlencode({"name": query.strip(), "countryCode": country, "count": 5, "language": "en", "format": "json"}))
            results = [r for r in data.get("results", []) if r.get("country_code") == country]
            if not results:
                raise FuelError("City not found. Use a full postcode or city, region.")
            result = results[0]
            lat, lon = coordinates(result.get("latitude"), result.get("longitude"))
            centre = {"latitude": lat, "longitude": lon, "label": " · ".join(filter(None, [result["name"], result.get("admin1"), result.get("country_code")]))}
        if len(self.locations) >= 128:
            self.locations.pop(next(iter(self.locations)))
        self.locations[key] = (self.clock(), centre)
        return centre

    async def search(self, country="GB", location="", radius=10, unit="mi", fuel="E10", limit=5, sort="price", centre=None):
        if country not in ADAPTERS:
            raise FuelError("No verified price adapter for this country yet. Select United Kingdom.")
        if unit not in ("mi", "km") or fuel not in ("E10", "E5", "B7", "SDV") or sort not in ("price", "distance"):
            raise FuelError("Invalid search options.")
        if not isinstance(location, str) or not 2 <= len(location.strip()) <= 120 or not math.isfinite(float(radius)) or not 1 <= float(radius) <= 100 or not 1 <= int(limit) <= 20:
            raise FuelError("Invalid location, radius or station count.")
        adapter = ADAPTERS[country]
        centre = centre or await self.resolve(location, country)
        async with self.lock:
            if not self.cache or self.clock()-self.cache[0] >= 900:
                try:
                    payload = await self.get_json(adapter.url)
                    adapter.normalize(payload, self.now())
                    self.cache = (self.clock(), payload)
                except Exception:
                    # Never replace failed refreshes with silently stale prices.
                    raise FuelError("Asda prices could not be refreshed. Try again later.")
            data = adapter.normalize(self.cache[1], self.now())
        return build_result(data, centre, radius, unit, fuel, limit, sort, country, self.now())

def normalize_fuel_prices_uk(rows, checked_at):
    """Adapt normalized Fuel Prices UK dictionaries. Authentication remains in that integration."""
    if not isinstance(rows, list):
        raise FuelError("Unsupported Fuel Prices UK station format.")
    stations, seen = [], set()
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            position = row.get("location") or {}
            lat, lon = coordinates(row.get("latitude", position.get("latitude")), row.get("longitude", position.get("longitude")))
            identifier = str(row.get("id") or row.get("site_id") or "")
            if not identifier or identifier in seen:
                continue
            prices, timestamps = {}, {}
            for fuel in ("E10", "E5", "B7", "SDV"):
                item = row.get("prices", {}).get(fuel)
                value = item.get("price") if isinstance(item, dict) else item
                if value is None or isinstance(value, bool) or value == "":
                    continue
                # Fuel Prices UK's price_parser.coerce_price returns GBP/litre.
                # Our adapter contract and widget consistently use pence/litre.
                value = float(value) * 100
                if math.isfinite(value) and 0 < value < 1000:
                    prices[fuel] = value
                    timestamps[fuel] = (item.get("last_updated") or item.get("timestamp")) if isinstance(item, dict) else row.get("last_updated")
            if not prices:
                continue
            address = row.get("address") or position.get("address") or row.get("name") or ""
            if isinstance(address, dict):
                address = ", ".join(str(address.get(k)) for k in ("address_line_1", "address_line_2", "city") if address.get(k))
            stations.append({"id": identifier, "brand": str(row.get("brand") or row.get("name") or "Independent"), "address": str(address), "postcode": str(row.get("postcode") or position.get("postcode") or ""), "latitude": lat, "longitude": lon, "prices": prices, "priceTimestamps": timestamps})
            seen.add(identifier)
        except (TypeError, ValueError, KeyError):
            continue
    return {"stations": stations, "updated": checked_at.isoformat(), "source": "Fuel Prices UK", "coverage": "UK Government Fuel Finder · participating retailers", "sourceUrl": "https://github.com/beecho01/Fuel-Prices-UK", "currency": "GBP", "priceUnit": "p/L", "freshnessKind": "checked"}

def build_result(data, centre, radius, unit, fuel, limit, sort, country="GB", now=None):
    radius_km = float(radius) * (1.609344 if unit == "mi" else 1)
    matches = []
    for station in data["stations"]:
        distance = distance_km((centre["latitude"], centre["longitude"]), (station["latitude"], station["longitude"]))
        if distance <= radius_km and fuel in station["prices"]:
            matches.append({**station, "price": station["prices"][fuel], "priceUpdated": station.get("priceTimestamps", {}).get(fuel), "distance": distance/(1.609344 if unit == "mi" else 1), "distanceKm": distance})
    matches.sort(key=lambda s: (s["price"], s["distanceKm"], s["id"]) if sort == "price" else (s["distanceKm"], s["price"], s["id"]))
    return {**{k:v for k,v in data.items() if k != "stations"}, "stations": matches[:int(limit)], "total": len(matches), "cheapest": min((s["price"] for s in matches), default=None), "centre": centre, "country": country, "fuel": fuel, "radius": radius, "unit": unit, "sort": sort, "fetchedAt": (now or datetime.now(timezone.utc)).isoformat(), "locationAttribution": "Home Assistant; GeoNames / Open-Meteo; postcodes.io / ONS"}
