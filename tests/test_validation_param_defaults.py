"""A launch parameter's fallback must equal the configured default.

``ConfigLoader.load_config`` merges ``default_config()`` on read, so a
divergent ``.get(key, literal)`` in the launch mapping is invisible for any
config that came off disk -- and decisive for one built in code (the CLI, a
test harness, a bundle-rebased config) or one predating the key. That is the
``min_reads_for_validation`` 50-against-10 trap the round-5 config audit named
on the form side; ``_validation_params`` had two of its own (audit 2026-11-06,
finding 20):

- ``validation_method`` fell back to ``blast`` where the default is
  ``minimap2`` -- a method 5-10x slower per pair that the operator never
  chose;
- ``e_val_cutoff`` fell back to ``1e-10`` where the default is ``0.01``, two
  orders of magnitude stricter, which drops true hits from confirmation
  testing and so weakens a result the report presents as confirmation.

This pins every fallback in that function against ``default_config()`` by
construction, so a new one cannot diverge.
"""

import pytest

from nanometa_live.core.config.config_loader import default_config
from nanometa_live.core.config.parameter_mapping import _validation_params

pytestmark = pytest.mark.unit


# Launch param -> the config key it falls back on.
FALLBACKS = {
    "validation_method": "validation_method",
    "validation_hit_rate_threshold": "validation_hit_rate_threshold",
    "validation_identity_threshold": "validation_identity_threshold",
    "minimap2_min_mapq": "minimap2_min_mapq",
    "minimap2_preset": "minimap2_preset",
}


@pytest.fixture
def empty_config_params():
    """What a config carrying none of these keys sends to the pipeline."""
    return _validation_params({}, True, True)


class TestFallbacksMatchTheDefaults:
    @pytest.mark.parametrize("param,key", sorted(FALLBACKS.items()))
    def test_each_fallback_equals_default_config(
        self, empty_config_params, param, key
    ):
        assert empty_config_params[param] == default_config()[key], (
            f"{param} falls back to {empty_config_params[param]!r} while "
            f"default_config() says {default_config()[key]!r}; a config "
            "without that key runs differently from one that has it"
        )

    def test_the_blast_evalue_fallback_is_the_configured_cutoff(
        self, empty_config_params
    ):
        """blast_evalue is a coerced form of e_val_cutoff, not a copy."""
        assert empty_config_params["blast_evalue"] == pytest.approx(
            float(default_config()["e_val_cutoff"])
        ), (
            "the e-value fallback was 1e-10 against a default of 0.01 -- two "
            "orders of magnitude stricter, so confirmation testing dropped "
            "true hits"
        )

    def test_blast_perc_identity_follows_the_identity_threshold(
        self, empty_config_params
    ):
        assert empty_config_params["blast_perc_identity"] == int(round(
            float(default_config()["validation_identity_threshold"])
        ))


class TestExplicitValuesStillWin:
    def test_a_configured_method_is_not_overridden(self):
        params = _validation_params({"validation_method": "both"}, True, True)
        assert params["validation_method"] == "both"

    def test_a_configured_evalue_is_not_overridden(self):
        params = _validation_params({"e_val_cutoff": 1e-20}, True, True)
        assert params["blast_evalue"] == pytest.approx(1e-20)

    def test_a_configured_mapq_is_not_overridden(self):
        params = _validation_params({"minimap2_min_mapq": 0}, True, True)
        assert params["minimap2_min_mapq"] == 0
