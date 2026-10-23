"""Set up the bridge from the UI. The Google key is optional and can be changed later under Configure."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_API_KEY, DOMAIN

KEY_FIELD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


class GlassHomeFuelFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(
                title="Fuel Prices for GlassHome",
                data={CONF_API_KEY: (user_input.get(CONF_API_KEY) or "").strip()},
            )
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Optional(CONF_API_KEY, default=""): KEY_FIELD}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GlassHomeFuelOptions()


class GlassHomeFuelOptions(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data={CONF_API_KEY: (user_input.get(CONF_API_KEY) or "").strip()})
        current = self.config_entry.options.get(CONF_API_KEY, self.config_entry.data.get(CONF_API_KEY, ""))
        return self.async_show_form(step_id="init", data_schema=vol.Schema({vol.Optional(CONF_API_KEY, default=current): KEY_FIELD}))
