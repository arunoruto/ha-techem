"""Config flow: paste the portal's session cookie."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .api import TechemAuthError, TechemClient, TechemError, parse_cookies
from .const import CONF_COOKIES, CONF_VALVES, CONF_WEATHER, DOMAIN

SCHEMA = vol.Schema({vol.Required("cookie"): TextSelector(TextSelectorConfig(multiline=True))})


class TechemConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TechemOptionsFlow()

    async def _check(self, text: str) -> tuple[str | None, dict | None, str | None]:
        cookies = parse_cookies(text)
        if not cookies:
            return "bad_cookie", None, None
        client = TechemClient(async_create_clientsession(self.hass, cookie_jar=aiohttp.DummyCookieJar()), cookies)
        try:
            user = await client.session_user()
            await client.units()
        except TechemAuthError:
            return "invalid_auth", None, None
        except (TechemError, aiohttp.ClientError, TimeoutError):
            return "cannot_connect", None, None
        return None, client.cookies, user

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input:
            error, cookies, user = await self._check(user_input["cookie"])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(user)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Techem", data={CONF_COOKIES: cookies})
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input:
            error, cookies, user = await self._check(user_input["cookie"])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(user)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(self._get_reauth_entry(), data={CONF_COOKIES: cookies})
        return self.async_show_form(step_id="reauth_confirm", data_schema=SCHEMA, errors=errors)


class TechemOptionsFlow(OptionsFlow):
    """Model inputs: radiator valves and whether to fetch weather from Open-Meteo."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(CONF_WEATHER, default=opts.get(CONF_WEATHER, True)): BooleanSelector(),
                vol.Optional(CONF_VALVES, default=opts.get(CONF_VALVES, [])): EntitySelector(
                    EntitySelectorConfig(domain="sensor", multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
