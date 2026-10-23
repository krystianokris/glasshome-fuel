# Fuel Prices for GlassHome

Home Assistant bridge for the **Fuel Prices v1**, **Fuel Prices v2** and **Fuel Prices Mini** widgets by @krystian in the [GlassHome](https://glasshome.app) widget library.

It reads UK fuel prices from the [Fuel Prices UK](https://github.com/beecho01/Fuel-Prices-UK) integration (official UK Government Fuel Finder data) and hands them to the widgets. It can also fetch the Google static map used by Fuel Prices v2. It adds no entities and changes nothing in Home Assistant.

## What you need

- Home Assistant 2024.12 or newer, with [HACS](https://hacs.xyz).
- **Fuel Prices UK** (HACS custom repository `https://github.com/beecho01/Fuel-Prices-UK`) set up with your own Fuel Finder client ID and secret.
- GlassHome 1.4 or newer.
- Optional: a Google Cloud API key with **Maps Static API** enabled, for the map in Fuel Prices v2.

## Install

1. **Fuel Prices UK**
   1. HACS → ⋮ → *Custom repositories* → add `https://github.com/beecho01/Fuel-Prices-UK`, type *Integration* → *Download*.
   2. Restart Home Assistant.
   3. Register at the [Fuel Finder developer portal](https://www.developer.fuel-finder.service.gov.uk/public-api), create an Information Recipient app and copy the client ID and secret.
   4. *Settings → Devices & services → Add integration → Fuel Prices UK*. Enter the ID and secret, your location and a radius, and tick at least **E10** and **B7**.
2. **This bridge**
   1. HACS → ⋮ → *Custom repositories* → add `https://github.com/krystianokris/glasshome-fuel`, type *Integration* → *Download*.
   2. Restart Home Assistant.
   3. *Settings → Devices & services → Add integration → Fuel Prices for GlassHome*.
   4. Paste a Google Maps Static API key if you want the v2 map, or leave it empty. You can change it later under *Configure*.
3. **The widgets**
   1. In GlassHome, edit a dashboard → *Add widget* → library → search **Fuel Prices** (@krystian).
   2. Add **Fuel Prices v1**, **v2** or **Mini**. When GlassHome asks, allow the widget to use *Fuel Prices for GlassHome*.
   3. In the widget settings set *Place name on the tile* (for example your town) and the language.

Want to try a widget before setting anything up? Turn on **Demo data** in its settings.

## Troubleshooting

| The widget says | What to do |
|---|---|
| Finish setting up Fuel Prices UK | Fuel Prices UK is not installed or has no working entry. |
| Fuel Prices UK is still fetching data | Wait for its first update (a few minutes), then press refresh. |
| Prices unavailable | This bridge is not installed or Home Assistant was not restarted. Check *Settings → System → Logs*. |
| Google map: add the key… | Add a key under *Fuel Prices for GlassHome → Configure*. Without a key v2 shows a radar instead. |
| Google rejected the key | Enable **Maps Static API** for the key in Google Cloud and check its restrictions. The key is used from your Home Assistant server, so do not restrict it to websites. |

## Services

- `glasshome_fuel.search` returns stations, prices in pence per litre and distances around your Home Assistant home or a custom UK postcode or city.
- `glasshome_fuel.map` returns a Google static map (data URI) with pin positions for the stations.

Both only return data. Your Fuel Finder credentials stay in Fuel Prices UK and your Google key stays in Home Assistant; neither is sent to the widgets.

## Credits

Price data: UK Government Fuel Finder via [Fuel Prices UK](https://github.com/beecho01/Fuel-Prices-UK) by @beecho01. Postcode lookup: [postcodes.io](https://postcodes.io). City lookup: [Open-Meteo](https://open-meteo.com). Map: Google Maps Static API.

Not affiliated with the UK Government, GlassHome or Google. Always check the price at the pump.

## License

MIT
