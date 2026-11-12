"""Tests for the experimental AutoCook start on FUSION Venus airfryers.

Off by default, offered only when the appliance advertises acp_c, and the
developer probe stops any cook it sets off. The coordinator methods run for
real against a stub transport that records what would be published.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from custom_components.philips_homeid import coordinator as coordinator_module
from custom_components.philips_homeid import services
from custom_components.philips_homeid.const import (
    CONF_EXPERIMENTAL_FUSION_AUTOCOOK,
    CONF_FUSION_AUTOCOOK_START_AFTER,
    CONF_FUSION_AUTOCOOK_VARIANT,
)
from custom_components.philips_homeid.coordinator import (
    PhilipsHomeIDCoordinator,
    build_autocook_payload,
)
from custom_components.philips_homeid.services import AUTOCOOK_PROBE_SCHEMA
from custom_components.philips_homeid.util import REDACTED, redact_for_log

C = PhilipsHomeIDCoordinator
SIGNED = "https://bucket.example/prog.bin?X-Amz-Signature=secret123"


class _Hass:
    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class _Client:
    """Stands in for PhilipsMQTTClient and answers each port as configured."""

    def __init__(self, stub, write_ports, answers):
        self._stub = stub
        self._write_ports = list(write_ports)
        self._answers = answers
        self.sent = []

    @property
    def discovered_write_ports(self):
        return list(self._write_ports)

    def has_write_port(self, port):
        return port in self._write_ports

    def send_port_command_and_wait_reply(self, port, command, props, timeout):
        self.sent.append((port, props))
        answer = self._answers.get(port, (True, 0, "ok"))
        reply = {"cid": "x", "cn": command, "status": answer[1], "data": {}}
        if port == "autocook_control":
            reply["data"] = {"portName": "acp_c", "properties": {"url": SIGNED}}
        if port == "control" and props == {"status": "cooking"} and answer[0]:
            self._stub.status = self._stub.start_becomes
        return (*answer, reply if answer[1] is not None else None)


class _Stub:
    """Runs the real experimental AutoCook code on a stub appliance."""

    async_autocook_send = C.async_autocook_send
    async_autocook_probe = C.async_autocook_probe
    experimental_fusion_autocook = C.experimental_fusion_autocook
    fusion_autocook_available = C.fusion_autocook_available
    _fusion_autocook_write = C._fusion_autocook_write
    _autocook_probe_watchdog = C._autocook_probe_watchdog
    _cancel_autocook_probe = C._cancel_autocook_probe
    _autocook_snapshot = C._autocook_snapshot
    _airfryer_drawer_open = C._airfryer_drawer_open
    _current_autocook_amount = C._current_autocook_amount
    _fusion_wake_status = "mainmenu"

    def __init__(
        self,
        options=None,
        write_ports=("Control", "acp_c"),
        answers=None,
        status="mainmenu",
        drawer_open=False,
        autocook=None,
        fusion=True,
        start_becomes="cooking",
    ):
        self.hass = _Hass()
        self.config_entry = SimpleNamespace(
            options={CONF_EXPERIMENTAL_FUSION_AUTOCOOK: True, **(options or {})}
        )
        self._is_fusion = fusion
        self.status = status
        self.start_becomes = start_becomes
        self.drawer_open = drawer_open
        self._autocook = autocook
        self.mqtt_client = _Client(self, write_ports, answers or {}) if fusion else None
        self._autocook_selected_uuid = "14"
        self._autocook_probe_task = None
        self.commands = []
        self.stops = 0

    @property
    def _state(self):
        properties = {
            "airfryer": {"status": self.status, "drawer_open": self.drawer_open}
        }
        if self._autocook is not None:
            properties["autocook"] = self._autocook
        return SimpleNamespace(properties=properties)

    def _get_airfryer_status(self):
        return self.status

    async def _ensure_fusion_control_port(self):
        return True

    async def _mqtt_command(self, port, props):
        self.commands.append((port, props))
        if props.get("status") == "mainmenu":
            self.status = "mainmenu"
        return True

    async def _wait_for_status(self, target, timeout=10):
        return self.status == target

    async def async_airfryer_stop(self):
        self.stops += 1
        self.status = "mainmenu"
        return True

    def _create_tracked_task(self, coro):
        return asyncio.get_running_loop().create_task(coro)


@pytest.fixture(autouse=True)
def fast_watchdog(monkeypatch):
    monkeypatch.setattr(coordinator_module, "_PROBE_POLL_INTERVAL", 0.01)


# Payload variants


def test_the_uuid_only_variant_matches_the_local_put():
    assert build_autocook_payload("14", "uuid_only", 3, 2) == {"UUID": "14"}


def test_the_amount_variant_adds_u1():
    assert build_autocook_payload("14", "uuid_amount", 3) == {"UUID": "14", "u1": 3}


def test_the_doneness_variant_adds_both():
    assert build_autocook_payload("14", "uuid_amount_doneness", 3, 2) == {
        "UUID": "14",
        "u1": 3,
        "doneness": 2,
    }


def test_missing_amount_and_doneness_fall_back_to_defaults():
    assert build_autocook_payload("14", "uuid_amount_doneness") == {
        "UUID": "14",
        "u1": 1,
        "doneness": 0,
    }


def test_an_unknown_variant_is_refused():
    with pytest.raises(ValueError):
        build_autocook_payload("14", "uuid_url")


# Gating


def test_offered_only_with_the_option_and_acp_c():
    assert _Stub().fusion_autocook_available()
    assert not _Stub(
        options={CONF_EXPERIMENTAL_FUSION_AUTOCOOK: False}
    ).fusion_autocook_available()
    assert not _Stub(write_ports=("Control",)).fusion_autocook_available()
    assert not _Stub(fusion=False).fusion_autocook_available()


def test_the_option_is_off_by_default():
    stub = _Stub()
    stub.config_entry.options = {}

    assert not stub.experimental_fusion_autocook
    assert not stub.fusion_autocook_available()


@pytest.mark.asyncio
async def test_send_does_nothing_with_the_option_off():
    stub = _Stub(options={CONF_EXPERIMENTAL_FUSION_AUTOCOOK: False})

    assert await stub.async_autocook_send() is False
    assert stub.mqtt_client.sent == []
    assert stub.commands == []


@pytest.mark.asyncio
async def test_send_does_nothing_without_acp_c():
    stub = _Stub(write_ports=("Control",))

    assert await stub.async_autocook_send() is False
    assert stub.mqtt_client.sent == []


@pytest.mark.asyncio
async def test_send_writes_the_configured_variant_and_amount():
    stub = _Stub(
        options={CONF_FUSION_AUTOCOOK_VARIANT: "uuid_amount"},
        autocook={"UUID": "14", "u1": 3},
    )

    assert await stub.async_autocook_send() is True
    assert stub.mqtt_client.sent == [("autocook_control", {"UUID": "14", "u1": 3})]


@pytest.mark.asyncio
async def test_send_starts_after_the_write_when_asked():
    stub = _Stub(options={CONF_FUSION_AUTOCOOK_START_AFTER: True})

    assert await stub.async_autocook_send() is True
    assert stub.mqtt_client.sent == [
        ("autocook_control", {"UUID": "14"}),
        ("control", {"status": "cooking"}),
    ]


@pytest.mark.asyncio
async def test_a_refused_write_is_not_followed_by_a_start():
    stub = _Stub(
        options={CONF_FUSION_AUTOCOOK_START_AFTER: True},
        answers={"autocook_control": (False, 8, "port_error")},
    )

    assert await stub.async_autocook_send() is False
    assert stub.mqtt_client.sent == [("autocook_control", {"UUID": "14"})]


@pytest.mark.asyncio
async def test_a_lost_reply_counts_as_sent():
    """from_ncp is QoS 0, as _mqtt_command already allows for."""
    stub = _Stub(answers={"autocook_control": (False, None, "timeout")})

    assert await stub.async_autocook_send() is True


@pytest.mark.asyncio
async def test_standby_is_woken_to_mainmenu_first():
    stub = _Stub(status="standby")

    report = await stub._fusion_autocook_write("14", "uuid_only")

    assert stub.commands == [("control", {"status": "mainmenu"})]
    assert report["woke"] is True
    assert report["result"] == "accepted"


@pytest.mark.asyncio
async def test_nothing_is_written_with_the_drawer_out():
    """A start pending on the drawer goes ahead once it is pushed back in."""
    stub = _Stub(drawer_open=True)

    report = await stub._fusion_autocook_write("14", "uuid_only", start_after=True)

    assert report["result"] == "drawer_open"
    assert stub.mqtt_client.sent == []


# Probe


@pytest.mark.asyncio
async def test_the_probe_needs_the_option():
    stub = _Stub(options={CONF_EXPERIMENTAL_FUSION_AUTOCOOK: False})

    report = await stub.async_autocook_probe("14")

    assert report["result"] == "option_disabled"
    assert stub.mqtt_client.sent == []


@pytest.mark.asyncio
async def test_the_probe_refuses_a_running_cook():
    stub = _Stub(status="cooking")

    report = await stub.async_autocook_probe("14")

    assert report["result"] == "busy"
    assert stub.mqtt_client.sent == []
    assert stub.stops == 0


@pytest.mark.asyncio
async def test_the_probe_reports_a_missing_acp_c():
    stub = _Stub(write_ports=("Control",))

    report = await stub.async_autocook_probe("14", watch_seconds=0.05)
    await stub._autocook_probe_task

    assert report["result"] == "acp_c_not_advertised"
    assert report["write_ports"] == ["Control"]
    assert stub.mqtt_client.sent == []


@pytest.mark.asyncio
async def test_the_probe_stops_the_cook_it_started():
    stub = _Stub()

    report = await stub.async_autocook_probe(
        "14", "uuid_amount", amount=3, start_after=True, stop_after_seconds=0
    )
    await asyncio.wait_for(stub._autocook_probe_task, 2)

    assert report["result"] == "accepted"
    assert report["start"]["verdict"] == "ok"
    assert stub.mqtt_client.sent == [
        ("autocook_control", {"UUID": "14", "u1": 3}),
        ("control", {"status": "cooking"}),
    ]
    assert stub.stops == 1
    assert stub.status == "mainmenu"


@pytest.mark.asyncio
async def test_the_stop_waits_stop_after_seconds():
    stub = _Stub()

    await stub.async_autocook_probe("14", start_after=True, stop_after_seconds=0.2)
    await asyncio.sleep(0.05)
    assert stub.stops == 0
    await asyncio.wait_for(stub._autocook_probe_task, 2)

    assert stub.stops == 1


@pytest.mark.asyncio
async def test_a_start_waiting_on_the_drawer_is_stopped_too():
    """user_action after a start means it will heat once the drawer closes."""
    stub = _Stub(start_becomes="user_action")

    await stub.async_autocook_probe("14", start_after=True, stop_after_seconds=0)
    await asyncio.wait_for(stub._autocook_probe_task, 2)

    assert stub.stops == 1


@pytest.mark.asyncio
async def test_a_probe_that_starts_nothing_stops_nothing():
    stub = _Stub(start_becomes="precook")

    await stub.async_autocook_probe(
        "14", start_after=True, stop_after_seconds=0, watch_seconds=0.05
    )
    await asyncio.wait_for(stub._autocook_probe_task, 2)

    assert stub.stops == 0
    assert stub.status == "precook"


@pytest.mark.asyncio
async def test_a_cook_already_ended_is_not_stopped_again():
    stub = _Stub()

    await stub.async_autocook_probe("14", start_after=True, stop_after_seconds=0.1)
    await asyncio.sleep(0.03)
    stub.status = "mainmenu"  # stopped on the panel
    await asyncio.wait_for(stub._autocook_probe_task, 2)

    assert stub.stops == 0


# Redaction


def test_redaction_removes_urls_and_credentials():
    data = {
        "UUID": "14",
        "url": SIGNED,
        "access_token": "a",
        "refreshToken": "b",
        "nested": [{"note": f"see {SIGNED}"}],
    }

    assert redact_for_log(data) == {
        "UUID": "14",
        "url": REDACTED,
        "access_token": REDACTED,
        "refreshToken": REDACTED,
        "nested": [{"note": f"see {REDACTED}"}],
    }


@pytest.mark.asyncio
async def test_the_probe_never_logs_the_signed_url(caplog):
    stub = _Stub(autocook={"UUID": "14", "u1": 3, "url": SIGNED})

    with caplog.at_level(logging.DEBUG):
        report = await stub.async_autocook_probe("14", watch_seconds=0.05)
        await asyncio.wait_for(stub._autocook_probe_task, 2)

    assert "secret123" not in caplog.text
    assert "secret123" not in repr(report)
    assert report["reply"]["data"]["properties"]["url"] == REDACTED
    assert "AutoCook over FUSION reply" in caplog.text


# Service schema


def test_the_service_schema_defaults():
    data = AUTOCOOK_PROBE_SCHEMA({"uuid": 14})

    assert data == {
        "uuid": "14",
        "variant": "uuid_only",
        "start_after": False,
        "stop_after_seconds": 20,
        "watch_seconds": 60,
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"uuid": "14", "variant": "uuid_url"},
        {"uuid": "14", "amount": 8},
        {"uuid": "fries"},
        {"uuid": "14", "stop_after_seconds": 301},
    ],
)
def test_the_service_schema_refuses_bad_input(bad):
    # services.vol: Home Assistant swaps voluptuous for probatio on import.
    with pytest.raises(services.vol.Invalid):
        AUTOCOOK_PROBE_SCHEMA(bad)


# Options


def test_the_options_default_to_off_and_uuid_only():
    from custom_components.philips_homeid.config_flow import (
        _experimental_fusion_autocook_schema,
    )

    schema = services.vol.Schema(_experimental_fusion_autocook_schema({}))

    assert schema({}) == {
        CONF_EXPERIMENTAL_FUSION_AUTOCOOK: False,
        CONF_FUSION_AUTOCOOK_VARIANT: "uuid_only",
        CONF_FUSION_AUTOCOOK_START_AFTER: False,
    }
    with pytest.raises(services.vol.Invalid):
        schema({CONF_FUSION_AUTOCOOK_VARIANT: "uuid_url"})
