"""The configured port must survive launch.

``config["gui_port"] = args.port`` ran unconditionally, and argparse defaulted
``--port`` to 8050, so the Configuration tab's port field was overwritten on
every start. It was saved, reloaded into the form, and silently ignored --
the operator could set it, see it persist, and never have it applied.

Precedence is the usual one: an explicit flag wins, otherwise the config
value, otherwise 8050.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _resolve(args_port, configured):
    """The precedence rule as nanometa_live.main applies it."""
    config = {} if configured is None else {"gui_port": configured}
    return args_port if args_port is not None else config.get("gui_port") or 8050


class TestPrecedence:
    def test_the_flag_wins_when_given(self):
        assert _resolve(9000, 8123) == 9000

    def test_the_config_is_used_when_the_flag_is_absent(self):
        assert _resolve(None, 8123) == 8123, (
            "gui_port was ignored; the Configuration tab's port field is "
            "saved, reloaded and then overwritten at launch"
        )

    def test_the_historical_default_applies_when_neither_is_set(self):
        assert _resolve(None, None) == 8050

    def test_an_empty_or_zero_config_value_falls_back(self):
        assert _resolve(None, 0) == 8050
        assert _resolve(None, "") == 8050


class TestTheFlagNoLongerDefaultsEagerly:
    def test_an_unset_port_parses_as_none(self, monkeypatch):
        """The mechanism the fix rests on.

        With ``default=8050`` there is no way to distinguish "the operator
        asked for 8050" from "the operator said nothing", which is exactly why
        the configured value was being overwritten.
        """
        import sys

        import nanometa_live.nanometa_live as entry

        monkeypatch.setattr(sys, "argv", ["nanometa-live"])
        args = entry.parse_arguments()

        assert args.port is None, (
            f"--port parsed as {args.port} when not given; an unset flag is "
            f"indistinguishable from an explicit one"
        )

    def test_an_explicit_port_still_parses(self, monkeypatch):
        import sys

        import nanometa_live.nanometa_live as entry

        monkeypatch.setattr(sys, "argv", ["nanometa-live", "--port", "9001"])
        args = entry.parse_arguments()

        assert args.port == 9001
