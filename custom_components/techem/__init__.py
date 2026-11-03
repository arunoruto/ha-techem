"""Techem tenant portal (mieter.techem.de): monthly heating/water consumption."""

from __future__ import annotations

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import TechemClient
from .const import CONF_COOKIES
from .coordinator import TechemCoordinator

PLATFORMS = [Platform.SENSOR]

type TechemConfigEntry = ConfigEntry[TechemCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TechemConfigEntry) -> bool:
    # own session without a cookie jar: we manage the portal cookie ourselves
    session = async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())
    coordinator = TechemCoordinator(hass, entry, TechemClient(session, entry.data[CONF_COOKIES]))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TechemConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
