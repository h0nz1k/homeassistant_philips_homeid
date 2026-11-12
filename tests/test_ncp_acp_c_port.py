"""Tests for the acp_c write port on FUSION Venus airfryers.

An HD9880 on FUSION advertises acp_c next to the read-only acp_s (issue #14).
These cover the transport side: the port maps, resolves, carries the AutoCook
properties unrenamed, and the port list is logged once at INFO.
"""

import json
import logging
import threading
import time

import pytest

from custom_components.philips_homeid.mqtt_api import (
    _NCP_PORT_MAP,
    FusionDeviceInfo,
    PhilipsMQTTClient,
)

LOGGER_NAME = "custom_components.philips_homeid.mqtt_api"


class _FakePaho:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos):
        self.published.append(json.loads(payload))


def _client(write_ports=("Control", "acp_c"), read_ports=("Status", "devcurst_s")):
    client = PhilipsMQTTClient(
        FusionDeviceInfo(
            thing_name="da-test",
            device_id="test",
            tenant="da",
            mqtt_host="host",
            platform_rest_url="url",
            model_name="HD9876",
        )
    )
    client._client = _FakePaho()
    client._connected = True
    client._discovered_ports = list(read_ports)
    client._discovered_write_ports = list(write_ports)
    return client


def _all_ports_reply(read, write):
    return {
        "cid": "1",
        "cn": "getAllPorts",
        "status": 0,
        "data": [{"portName": p, "direction": "read"} for p in read]
        + [{"portName": p, "direction": "write"} for p in write],
    }


def test_acp_c_maps_to_its_own_local_port():
    """acp_c is the write side; acp_s keeps feeding the autocook sensors."""
    assert _NCP_PORT_MAP["acp_c"] == "autocook_control"
    assert _NCP_PORT_MAP["acp_s"] == "autocook"


def test_autocook_control_resolves_to_acp_c():
    client = _client()

    assert client._resolve_ncp_port("autocook_control") == "acp_c"
    # The read port is untouched by the new entry.
    assert client._resolve_ncp_port("autocook") == "acp_s"


def test_an_acp_c_write_keeps_the_autocook_property_names():
    """The Venus Control renames (method, total_time) must not reach acp_c."""
    client = _client()
    assert client.is_venus

    client.send_port_command(
        "autocook_control", "setPort", {"UUID": "14", "u1": 3, "doneness": 0}
    )

    data = client._client.published[-1]["data"]
    assert data == {
        "portName": "acp_c",
        "properties": {"UUID": "14", "u1": 3, "doneness": 0},
    }


def test_has_write_port_follows_discovery():
    assert _client().has_write_port("acp_c")
    assert not _client(write_ports=("Control",)).has_write_port("acp_c")
    assert _client().discovered_write_ports == ["Control", "acp_c"]


def test_the_port_list_is_logged_once_at_info(caplog):
    client = _client(write_ports=(), read_ports=())
    client._enqueue_port_reads = lambda ports, new_round=False: None
    reply = _all_ports_reply(["Status", "acp_s"], ["Control", "acp_c"])

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client._handle_ncp_response(reply)
        client._handle_ncp_response(reply)

    infos = [
        r.getMessage()
        for r in caplog.records
        if r.name == LOGGER_NAME and r.levelno == logging.INFO
    ]
    assert infos == [
        (
            "NCP getAllPorts for HD9876: read=['Status', 'acp_s'] "
            "write=['Control', 'acp_c']"
        )
    ]
    assert client.has_write_port("acp_c")


def test_a_changed_port_list_is_logged_again(caplog):
    """A Venus 2 hides its control port in standby, so the list changes."""
    client = _client(write_ports=(), read_ports=())
    client._enqueue_port_reads = lambda ports, new_round=False: None

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client._handle_ncp_response(_all_ports_reply(["Status"], []))
        client._handle_ncp_response(_all_ports_reply(["Status"], ["acp_c"]))

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(infos) == 2


def _pending(client, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with client._lock:
            waiting = list(client._pending_writes)
        if waiting:
            return waiting[0]
        time.sleep(0.005)
    pytest.fail("no write was registered")


def test_the_whole_reply_comes_back_for_logging():
    client = _client()
    holder = {}

    def run():
        holder["result"] = client.send_port_command_and_wait_reply(
            "autocook_control", "setPort", {"UUID": "14"}, 2.0
        )

    thread = threading.Thread(target=run)
    thread.start()
    cid = _pending(client)
    reply = {
        "cid": cid,
        "cn": "setPort",
        "type": "response",
        "status": 8,
        "data": {"portName": "acp_c"},
    }
    client._handle_ncp_response(reply)
    thread.join(2)

    accepted, status, name, payload = holder["result"]
    assert (accepted, status, name) == (False, 8, "port_error")
    assert payload == reply


def test_a_lost_reply_returns_no_payload():
    client = _client()

    result = client.send_port_command_and_wait_reply(
        "autocook_control", "setPort", {"UUID": "14"}, 0.05
    )

    assert result == (False, None, "timeout", None)
