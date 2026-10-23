"""Read-only bridge from Fuel Prices UK to GlassHome widgets, plus an optional Google static map."""
from datetime import datetime, timedelta, timezone

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_API_KEY, DATA_KEYS, DOMAIN
from .google_map import MapError, render_map
from .provider import FuelError, FuelSearch, build_result, coordinates, normalize_fuel_prices_uk

CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): vol.Schema({})}, extra=vol.ALLOW_EXTRA)

SEARCH_SCHEMA = vol.Schema(
    {
        vol.Optional("source", default="fuel_prices_uk"): vol.In(["fuel_prices_uk", "asda"]),
        vol.Optional("location_mode", default="home"): vol.In(["home", "custom"]),
        vol.Optional("country", default="GB"): vol.In(["GB", "PL", "DE", "FR", "IE"]),
        vol.Optional("location", default=""): vol.All(str, vol.Length(max=120)),
        vol.Optional("radius", default=10): vol.All(vol.Coerce(float), vol.Range(min=1, max=100)),
        vol.Optional("unit", default="mi"): vol.In(["mi", "km"]),
        vol.Optional("fuel", default="E10"): vol.In(["E10", "E5", "B7", "SDV"]),
        vol.Optional("limit", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
        vol.Optional("sort", default="price"): vol.In(["price", "distance"]),
    }
)

MAP_SCHEMA = vol.Schema(
    {
        vol.Required("home"): {
            vol.Required("latitude"): vol.Coerce(float),
            vol.Required("longitude"): vol.Coerce(float),
        },
        vol.Required("stations"): vol.All(
            [
                {
                    vol.Required("id"): vol.All(str, vol.Length(min=1, max=100)),
                    vol.Required("latitude"): vol.Coerce(float),
                    vol.Required("longitude"): vol.Coerce(float),
                }
            ],
            vol.Length(max=20),
        ),
        vol.Required("radius"): vol.All(vol.Coerce(float), vol.Range(min=1, max=100)),
        vol.Required("unit"): vol.In(["mi", "km"]),
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    session = async_get_clientsession(hass)

    async def get_json(url):
        async with session.get(url, timeout=25, headers={"User-Agent": "GlassHome-Fuel/0.1"}) as response:
            response.raise_for_status()
            return await response.json(content_type=None)

    engine = FuelSearch(get_json)
    hass.data[DOMAIN] = engine
    hass.data.setdefault(DATA_KEYS, {})

    async def search(call: ServiceCall):
        options = dict(call.data)
        source = options.pop("source", "fuel_prices_uk")
        mode = options.pop("location_mode", "home")
        if options["country"] != "GB":
            return {"error": {"code": "country_unsupported"}}
        try:
            if mode == "home":
                lat, lon = coordinates(hass.config.latitude, hass.config.longitude)
                centre = {"latitude": lat, "longitude": lon, "label": hass.config.location_name or "Home", "mode": "home"}
            else:
                if len(options["location"].strip()) < 2:
                    return {"error": {"code": "location_required"}}
                centre = dict(await engine.resolve(options["location"], options["country"]), mode="custom")
            if source == "asda":
                # Never silently substitute a single retailer for the selected Fuel Finder source.
                options["location"] = options["location"] or "Home"
                return await engine.search(**options, centre=centre)
            coordinators = hass.data.get("fuel_prices_uk", {})
            ready = [c for c in coordinators.values() if getattr(c, "api_client", None)] if isinstance(coordinators, dict) else []
            if not ready:
                return {"error": {"code": "integration_setup_required"}, "centre": centre}
            client = ready[0].api_client
            radius_km = options["radius"] * (1.609344 if options["unit"] == "mi" else 1)
            rows = await client.get_stations_within_radius(centre["latitude"], centre["longitude"], radius_km)
            age = getattr(client, "data_age_seconds", None)
            if age is None or age < 0 or age > 48 * 3600:
                return {"error": {"code": "source_not_ready"}, "centre": centre}
            data = normalize_fuel_prices_uk(rows, datetime.now(timezone.utc) - timedelta(seconds=age))
            return build_result(
                data, centre, options["radius"], options["unit"], options["fuel"], options["limit"], options["sort"], options["country"]
            )
        except FuelError:
            return {"error": {"code": "location_or_source_error"}}
        except Exception:
            # API-client errors can contain authentication details; never expose them to widgets.
            return {"error": {"code": "source_unavailable"}}

    async def map_image(call: ServiceCall):
        api_key = next((key for key in hass.data[DATA_KEYS].values() if key), None)
        try:
            return await render_map(session, api_key, call.data["home"], call.data["stations"], call.data["radius"], call.data["unit"])
        except MapError as error:
            return {"error": {"code": error.code}}
        except Exception:
            return {"error": {"code": "google_map_unavailable"}}

    hass.services.async_register(DOMAIN, "search", search, schema=SEARCH_SCHEMA, supports_response=SupportsResponse.ONLY)
    hass.services.async_register(DOMAIN, "map", map_image, schema=MAP_SCHEMA, supports_response=SupportsResponse.ONLY)
    return True


def _key(entry: ConfigEntry) -> str:
    return (entry.options.get(CONF_API_KEY) or entry.data.get(CONF_API_KEY) or "").strip()


async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    hass.data[DATA_KEYS][entry.entry_id] = _key(entry)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DATA_KEYS, {})[entry.entry_id] = _key(entry)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.get(DATA_KEYS, {}).pop(entry.entry_id, None)
    return True
