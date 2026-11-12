"""Tests for which entities the experimental FUSION AutoCook start creates.

The AutoCook select and send button stay local-only unless the experimental
option is on and the appliance advertised acp_c.
"""

from types import SimpleNamespace

import pytest

from custom_components.philips_homeid import button, select
from custom_components.philips_homeid.const import DOMAIN


class _Coordinator:
    def __init__(self, fusion=True, available=False, autocook_reported=False):
        self.device_info = SimpleNamespace(model_name="HD9876", airfryer_port=None)
        self.device_id = "dev"
        self.mqtt_client = object() if fusion else None
        self._available = available
        self._autocook_reported = autocook_reported

    def fusion_autocook_available(self):
        return self._available

    def has_property(self, key, nested=None):
        if key == "autocook":
            return self._autocook_reported
        return True

    def my_preset_options(self):
        return {}

    def register_new_property_callback(self, callback):
        return lambda: None


def _setup(coordinator):
    hass = SimpleNamespace(data={DOMAIN: {"entry": coordinator}})
    entry = SimpleNamespace(
        entry_id="entry", data={}, async_on_unload=lambda unregister: None
    )
    return hass, entry


async def _button_keys(monkeypatch, coordinator):
    monkeypatch.setattr(
        button, "PhilipsHomeIDButton", lambda c, description, i: description.key
    )
    added = []
    hass, entry = _setup(coordinator)
    await button.async_setup_entry(hass, entry, lambda e, *a, **kw: added.extend(e))
    return added


async def _select_names(monkeypatch, coordinator):
    for name in (
        "PhilipsHomeIDCookingMethodSelect",
        "PhilipsHomeIDMyPresetSelect",
        "PhilipsHomeIDAutoCookProgramSelect",
    ):
        monkeypatch.setattr(select, name, lambda c, i, name=name: name)
    added = []
    hass, entry = _setup(coordinator)
    await select.async_setup_entry(hass, entry, lambda e, *a, **kw: added.extend(e))
    return added


@pytest.mark.asyncio
async def test_no_fusion_autocook_button_by_default(monkeypatch):
    keys = await _button_keys(monkeypatch, _Coordinator(available=False))

    assert "airfryer_autocook_send" not in keys
    assert "airfryer_stop" in keys


@pytest.mark.asyncio
async def test_the_fusion_autocook_button_once_available(monkeypatch):
    keys = await _button_keys(monkeypatch, _Coordinator(available=True))

    assert keys.count("airfryer_autocook_send") == 1


@pytest.mark.asyncio
async def test_no_fusion_autocook_select_by_default(monkeypatch):
    """acp_s reporting a program is not enough without the option and acp_c."""
    names = await _select_names(
        monkeypatch, _Coordinator(available=False, autocook_reported=True)
    )

    assert "PhilipsHomeIDAutoCookProgramSelect" not in names


@pytest.mark.asyncio
async def test_the_fusion_autocook_select_once_available(monkeypatch):
    names = await _select_names(monkeypatch, _Coordinator(available=True))

    assert names.count("PhilipsHomeIDAutoCookProgramSelect") == 1


@pytest.mark.asyncio
async def test_the_local_autocook_select_is_unchanged(monkeypatch):
    names = await _select_names(
        monkeypatch, _Coordinator(fusion=False, autocook_reported=True)
    )

    assert "PhilipsHomeIDAutoCookProgramSelect" in names
