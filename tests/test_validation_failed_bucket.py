"""A failed validation is not "no data".

``_compute_summary`` put status ``failed`` (the validation process itself
failed: a crashed BLAST, an unreadable output) in the No Data bucket, so a
parse error or tool crash read as "not checked". It is counted on its own
and the summary card names it.
"""

import pytest

from nanometa_live.app.layouts.validation_layout import create_validation_status_card
from nanometa_live.app.tabs.validation_tab_helpers import _compute_summary

pytestmark = pytest.mark.unit


def _text(node):
    if isinstance(node, (str, int)):
        return str(node)
    children = getattr(node, "children", None)
    if children is None:
        return ""
    if not isinstance(children, (list, tuple)):
        children = [children]
    return " ".join(_text(c) for c in children)


def test_failed_is_counted_apart_from_no_data():
    s = _compute_summary([{"status": "failed"}, {"status": "no_data"},
                          {"status": "confirmed"}])
    assert s["failed"] == 1
    assert s["no_data"] == 1
    assert s["confirmed"] == 1


def test_card_names_failed_validations():
    text = _text(create_validation_status_card(confirmed=1, no_data=1,
                                               failed=2, total=4))
    assert "2 validations failed" in text


def test_card_says_nothing_about_failures_when_there_are_none():
    text = _text(create_validation_status_card(confirmed=1, total=1))
    assert "failed" not in text.lower()
