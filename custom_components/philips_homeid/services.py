"""Developer actions for Philips HomeID.

autocook_probe writes one built-in AutoCook program to the acp_c port of a
FUSION Venus airfryer and logs what the appliance answers. It exists to settle
the open questions about that port (its schema, and whether a start must
follow) on real hardware, and only works with the experimental FUSION AutoCook
option on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    AUTOCOOK_VARIANT_UUID_ONLY,
    AUTOCOOK_VARIANTS,
    DEFAULT_PROBE_STOP_AFTER,
    DEFAULT_PROBE_WATCH,
    DOMAIN,
    SERVICE_AUTOCOOK_PROBE,
)

if TYPE_CHECKING:
    from .coordinator import PhilipsHomeIDCoordinator

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_UUID = "uuid"
ATTR_VARIANT = "variant"
ATTR_AMOUNT = "amount"
ATTR_DONENESS = "doneness"
ATTR_START_AFTER = "start_after"
ATTR_STOP_AFTER = "stop_after_seconds"
ATTR_WATCH = "watch_seconds"

AUTOCOOK_PROBE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_UUID): vol.All(vol.Coerce(str), vol.Match(r"^\d+$")),
        vol.Optional(ATTR_VARIANT, default=AUTOCOOK_VARIANT_UUID_ONLY): vol.In(
            AUTOCOOK_VARIANTS
        ),
        # The HD9876 asks for a basket fill level of 1 to 7.
        vol.Optional(ATTR_AMOUNT): vol.All(vol.Coerce(int), vol.Range(min=1, max=7)),
        vol.Optional(ATTR_DONENESS): vol.All(vol.Coerce(int), vol.Range(min=0, max=10)),
        vol.Optional(ATTR_START_AFTER, default=False): cv.boolean,
        vol.Optional(ATTR_STOP_AFTER, default=DEFAULT_PROBE_STOP_AFTER): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=300)
        ),
        vol.Optional(ATTR_WATCH, default=DEFAULT_PROBE_WATCH): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=600)
        ),
    }
)


def _probe_target(
    hass: HomeAssistant, entry_id: str | None
) -> PhilipsHomeIDCoordinator:
    """Return the coordinator a probe is meant for."""
    coordinators: dict[str, Any] = hass.data.get(DOMAIN, {})
    if entry_id is not None:
        coordinator = coordinators.get(entry_id)
        if coordinator is None:
            raise ServiceValidationError(f"No loaded Philips HomeID entry {entry_id}")
        candidates = [coordinator]
    else:
        candidates = [
            c
            for c in coordinators.values()
            if getattr(c, "experimental_fusion_autocook", False)
        ]
        if len(candidates) != 1:
            raise ServiceValidationError(
                "Name the config_entry_id: "
                f"{len(candidates)} entries have the experimental FUSION "
                "AutoCook option on"
            )
    coordinator = candidates[0]
    if coordinator.mqtt_client is None:
        raise ServiceValidationError("autocook_probe only works on FUSION devices")
    if not coordinator.experimental_fusion_autocook:
        raise ServiceValidationError(
            "Turn on the experimental FUSION AutoCook option first"
        )
    return coordinator


async def _async_autocook_probe(call: ServiceCall) -> ServiceResponse:
    """Run one acp_c probe and return its report."""
    data = call.data
    coordinator = _probe_target(call.hass, data.get(ATTR_CONFIG_ENTRY_ID))
    report = await coordinator.async_autocook_probe(
        data[ATTR_UUID],
        data[ATTR_VARIANT],
        amount=data.get(ATTR_AMOUNT),
        doneness=data.get(ATTR_DONENESS),
        start_after=data[ATTR_START_AFTER],
        stop_after_seconds=data[ATTR_STOP_AFTER],
        watch_seconds=data[ATTR_WATCH],
    )
    return dict(report)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's developer actions."""
    if hass.services.has_service(DOMAIN, SERVICE_AUTOCOOK_PROBE):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_AUTOCOOK_PROBE,
        _async_autocook_probe,
        schema=AUTOCOOK_PROBE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
