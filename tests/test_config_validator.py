"""Tests for the read-filtering and validation field ranges in
``nanometa_live.core.config.config_validator``.

The eight Configuration tab amplicon-related controls (chopper +
filtlong + kraken2 + minimap2 + validation_identity_threshold) need
range validation so an out-of-bounds or non-numeric value entered
through the GUI does not propagate to nanometanf as a broken Nextflow
parameter. Defaults match nanometanf's long-read defaults; out-of-range
inputs are silently reset to those defaults rather than raising,
following the existing validator pattern.
"""

import pytest

from nanometa_live.core.config.config_validator import validate_config


@pytest.fixture
def base_config():
    """Minimal config that satisfies the unrelated required fields.

    The validator raises on an empty config, so each test extends this
    base rather than starting from ``{}``.
    """
    return {"analysis_name": "amplicon-test"}


class TestChopperMinlength:
    def test_default_when_missing(self, base_config):
        result = validate_config(base_config)
        assert result["chopper_minlength"] == 1000

    def test_amplicon_value_passes(self, base_config):
        base_config["chopper_minlength"] = 100
        assert validate_config(base_config)["chopper_minlength"] == 100

    def test_zero_disables_filter(self, base_config):
        base_config["chopper_minlength"] = 0
        assert validate_config(base_config)["chopper_minlength"] == 0

    def test_negative_resets_to_default(self, base_config):
        base_config["chopper_minlength"] = -50
        assert validate_config(base_config)["chopper_minlength"] == 1000

    def test_above_max_resets_to_default(self, base_config):
        base_config["chopper_minlength"] = 60000
        assert validate_config(base_config)["chopper_minlength"] == 1000

    def test_non_int_resets_to_default(self, base_config):
        base_config["chopper_minlength"] = "1000"
        assert validate_config(base_config)["chopper_minlength"] == 1000

    def test_bool_resets_to_default(self, base_config):
        # Pythonic guard: True is an int, but 1 != "length 1" semantically.
        base_config["chopper_minlength"] = True
        assert validate_config(base_config)["chopper_minlength"] == 1000


class TestChopperQuality:
    def test_default_when_missing(self, base_config):
        assert validate_config(base_config)["chopper_quality"] == 10

    def test_amplicon_value_passes(self, base_config):
        base_config["chopper_quality"] = 7
        assert validate_config(base_config)["chopper_quality"] == 7

    def test_above_max_resets(self, base_config):
        base_config["chopper_quality"] = 50
        assert validate_config(base_config)["chopper_quality"] == 10

    def test_negative_resets(self, base_config):
        base_config["chopper_quality"] = -1
        assert validate_config(base_config)["chopper_quality"] == 10


class TestFiltlongMinLength:
    def test_default_when_missing(self, base_config):
        assert validate_config(base_config)["filtlong_min_length"] == 1000

    def test_amplicon_value_passes(self, base_config):
        base_config["filtlong_min_length"] = 200
        assert validate_config(base_config)["filtlong_min_length"] == 200

    def test_above_max_resets(self, base_config):
        base_config["filtlong_min_length"] = 99999
        assert validate_config(base_config)["filtlong_min_length"] == 1000


class TestKraken2Confidence:
    def test_default_when_missing(self, base_config):
        assert validate_config(base_config)["kraken2_confidence"] == 0.0

    def test_in_range(self, base_config):
        base_config["kraken2_confidence"] = 0.05
        assert validate_config(base_config)["kraken2_confidence"] == 0.05

    def test_upper_bound_inclusive(self, base_config):
        base_config["kraken2_confidence"] = 1.0
        assert validate_config(base_config)["kraken2_confidence"] == 1.0

    def test_above_max_resets(self, base_config):
        base_config["kraken2_confidence"] = 1.5
        assert validate_config(base_config)["kraken2_confidence"] == 0.0

    def test_negative_resets(self, base_config):
        base_config["kraken2_confidence"] = -0.1
        assert validate_config(base_config)["kraken2_confidence"] == 0.0


class TestKraken2MinimumHitGroups:
    def test_default_when_missing(self, base_config):
        assert validate_config(base_config)["kraken2_minimum_hit_groups"] == 0

    def test_in_range(self, base_config):
        base_config["kraken2_minimum_hit_groups"] = 3
        assert validate_config(base_config)["kraken2_minimum_hit_groups"] == 3

    def test_above_max_resets(self, base_config):
        base_config["kraken2_minimum_hit_groups"] = 50
        assert validate_config(base_config)["kraken2_minimum_hit_groups"] == 0


class TestValidationIdentityThreshold:
    def test_default_when_missing(self, base_config):
        assert validate_config(base_config)["validation_identity_threshold"] == 90.0

    def test_amplicon_relaxed_value(self, base_config):
        base_config["validation_identity_threshold"] = 80.0
        assert (
            validate_config(base_config)["validation_identity_threshold"] == 80.0
        )

    def test_above_max_resets(self, base_config):
        base_config["validation_identity_threshold"] = 110
        assert (
            validate_config(base_config)["validation_identity_threshold"] == 90.0
        )

    def test_negative_resets(self, base_config):
        base_config["validation_identity_threshold"] = -5
        assert (
            validate_config(base_config)["validation_identity_threshold"] == 90.0
        )

    def test_int_accepted_as_float_input(self, base_config):
        base_config["validation_identity_threshold"] = 95
        assert (
            validate_config(base_config)["validation_identity_threshold"] == 95
        )


class TestMinimap2Preset:
    def test_default_when_missing(self, base_config):
        assert validate_config(base_config)["minimap2_preset"] == "map-ont"

    @pytest.mark.parametrize(
        "value", ["map-ont", "sr", "asm5", "asm10", "asm20"]
    )
    def test_accepted_presets(self, base_config, value):
        base_config["minimap2_preset"] = value
        assert validate_config(base_config)["minimap2_preset"] == value

    def test_unknown_preset_resets(self, base_config):
        base_config["minimap2_preset"] = "splice"
        assert validate_config(base_config)["minimap2_preset"] == "map-ont"

    def test_non_string_resets(self, base_config):
        base_config["minimap2_preset"] = 5
        assert validate_config(base_config)["minimap2_preset"] == "map-ont"


class TestMinimap2MinMapq:
    def test_default_when_missing(self, base_config):
        assert validate_config(base_config)["minimap2_min_mapq"] == 10

    def test_amplicon_relaxed_value(self, base_config):
        base_config["minimap2_min_mapq"] = 5
        assert validate_config(base_config)["minimap2_min_mapq"] == 5

    def test_above_max_resets(self, base_config):
        base_config["minimap2_min_mapq"] = 100
        assert validate_config(base_config)["minimap2_min_mapq"] == 10

    def test_negative_resets(self, base_config):
        base_config["minimap2_min_mapq"] = -1
        assert validate_config(base_config)["minimap2_min_mapq"] == 10


class TestAmpliconPresetRoundTrip:
    """The recommended amplicon preset from the audit should pass
    validation unchanged. If any single field is rejected by the
    range checks the operator-facing preset is broken."""

    def test_amplicon_preset_passes_unchanged(self, base_config):
        amplicon = {
            "chopper_minlength": 100,
            "chopper_quality": 7,
            "filtlong_min_length": 100,
            "validation_identity_threshold": 80.0,
            "minimap2_preset": "sr",
            "minimap2_min_mapq": 5,
            "kraken2_confidence": 0.05,
            "kraken2_minimum_hit_groups": 2,
        }
        base_config.update(amplicon)
        result = validate_config(base_config)
        for key, expected in amplicon.items():
            assert result[key] == expected, (
                f"{key} rejected by validator (got {result[key]!r}, "
                f"expected {expected!r})"
            )
