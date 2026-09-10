"""Binding a non-loopback host prints what it exposes.

The dashboard has no authentication. On 127.0.0.1 that is the single-user
posture the design assumes; on 0.0.0.0 it is an unauthenticated control
surface, and the operator must be told so at the moment they choose it.
"""

import pytest

from nanometa_live.app.utils.network_posture import LOOPBACK_HOSTS, exposure_warning

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("host", sorted(LOOPBACK_HOSTS) + ["LOCALHOST", " 127.0.0.1 "])
def test_loopback_hosts_produce_no_warning(host):
    assert exposure_warning(host) is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "myhost.example"])
def test_reachable_hosts_name_what_is_exposed(host):
    text = exposure_warning(host)
    assert text is not None
    assert host in text
    assert "no authentication" in text
    assert "start and stop" in text.lower()
    assert "127.0.0.1" in text


def test_run_server_prints_the_warning_for_a_reachable_host(capsys):
    from nanometa_live.app.__main__ import _run_server

    app = type("App", (), {"run": staticmethod(lambda **kw: None)})()
    _run_server(app, host="0.0.0.0", port=8050, debug=False)
    err = capsys.readouterr().err
    assert "0.0.0.0" in err and "no authentication" in err


def test_run_server_is_silent_on_loopback(capsys):
    from nanometa_live.app.__main__ import _run_server

    app = type("App", (), {"run": staticmethod(lambda **kw: None)})()
    _run_server(app, host="127.0.0.1", port=8050, debug=False)
    assert capsys.readouterr().err == ""
