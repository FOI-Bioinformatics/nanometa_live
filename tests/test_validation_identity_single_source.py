"""The validation-identity control must actually reach BLAST.

``blast_perc_identity`` was built as::

    config.get("min_perc_identity", config.get("validation_identity_threshold", 90))

a back-compat shim whose own comment said "New configs only carry the
latter". That premise was false: ``create_default_config`` wrote
``min_perc_identity: 90`` into every config, and no GUI widget could change
it. So the legacy key was always present and always won, and the shim was
not a fallback -- it was the only path.

The dangerous direction is downward. An operator who lowers the identity
threshold to catch a divergent strain whose sequence has drifted from the
reference gets no change at all: BLAST keeps filtering at 90, hits below
that are never produced, and nothing reports that the search did not widen.
"""

from __future__ import annotations

import pytest

from nanometa_live.core.config.parameter_mapping import create_nextflow_params

pytestmark = pytest.mark.unit


#: The minimum a config needs for create_nextflow_params to build at all.
#: Nothing here bears on the identity threshold under test.
_BASE = {
    "nanopore_output_directory": "/tmp/nanometa-identity-test/fastq",
    "results_output_directory": "/tmp/nanometa-identity-test/results",
    "kraken_db": "/tmp/nanometa-identity-test/db",
    "blast_validation": True,
}


def _identity_params(config):
    params = create_nextflow_params({**_BASE, **config})
    return params.get("blast_perc_identity"), params.get(
        "validation_identity_threshold"
    )


class TestTheSliderReachesBlast:
    @pytest.mark.parametrize("value", [80, 85, 95, 99])
    def test_the_blast_filter_follows_the_configured_threshold(self, value):
        blast, reported = _identity_params({"validation_identity_threshold": value})

        assert blast == value, (
            f"the operator asked for {value}% identity and BLAST was told "
            f"{blast}%; the control does not reach the filter"
        )
        assert reported == value

    def test_lowering_the_threshold_actually_widens_the_search(self):
        """The missed-detection direction, stated as its own case.

        A divergent or engineered strain is exactly what an operator lowers
        this control for. If BLAST keeps filtering at the default, the hits
        they widened the search to catch are never produced.
        """
        blast, _ = _identity_params({"validation_identity_threshold": 80})

        assert blast == 80, (
            "lowering the identity threshold did not widen the BLAST filter, "
            "so reads from a divergent strain are silently never reported"
        )

    def test_the_two_emitted_params_never_disagree(self):
        """They describe one threshold and must not drift apart."""
        for value in (75, 90, 97):
            blast, reported = _identity_params(
                {"validation_identity_threshold": value}
            )
            assert blast == reported, (
                f"BLAST filters at {blast}% while the reported threshold is "
                f"{reported}%; these describe the same setting"
            )

    def test_the_default_still_applies_when_nothing_is_configured(self):
        blast, reported = _identity_params({})
        assert blast == 90
        assert reported == 90.0


class TestTheLegacyKeyIsGone:
    def test_create_default_config_no_longer_writes_min_perc_identity(self):
        """The key's presence in every default config is what broke this.

        Leaving it out of the defaults is what makes
        validation_identity_threshold the single source rather than a value
        that is always shadowed.
        """
        import tempfile

        from nanometa_live.core.config.config_loader import ConfigLoader

        config = ConfigLoader(tempfile.mkdtemp()).create_default_config()

        assert "min_perc_identity" not in config, (
            "create_default_config still writes the legacy min_perc_identity "
            "key, which shadows the GUI control in every config it creates"
        )

    def test_a_config_carrying_the_legacy_key_does_not_shadow_the_control(self):
        """Old configs on disk still exist; they must not win.

        Honouring the legacy key would reinstate the defect for exactly the
        operators most likely to have an old config lying around.
        """
        blast, _ = _identity_params({
            "min_perc_identity": 90,
            "validation_identity_threshold": 80,
        })

        assert blast == 80, (
            "a stale min_perc_identity in an existing config still overrides "
            "the operator's current setting"
        )
