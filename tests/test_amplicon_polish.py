"""Amplicon-audit polish items (2026-08-17 evening).

Three fixes:

1. The "0 disables" length-filter trap: nanometanf's schema sets
   ``minimum: 1`` on ``chopper_minlength`` / ``filtlong_min_length``, so a 0
   saved by the GUI failed nf-schema at launch. The form floor, the save-time
   range check, and the launch-time coercion now all agree on 1.
2. N50 grading is amplicon-aware: the whole-genome bands marked every
   short-amplicon run red even when the N50 equals the amplicon length by
   design.
3. Assembly is operator-reachable: ``enable_assembly`` / ``assembler`` have
   config defaults, flow through parameter mapping, and are wired into the
   Configuration form via the field registry.
"""

import pytest

pytestmark = pytest.mark.unit


class TestMinLengthZeroTrap:
    def test_coerce_zero_to_one(self):
        from nanometa_live.core.config.parameter_mapping import _coerce_min_length
        assert _coerce_min_length(0, "chopper_minlength") == 1

    def test_coerce_negative_to_one(self):
        from nanometa_live.core.config.parameter_mapping import _coerce_min_length
        assert _coerce_min_length(-5, "chopper_minlength") == 1

    def test_coerce_missing_to_default(self):
        from nanometa_live.core.config.parameter_mapping import _coerce_min_length
        assert _coerce_min_length(None, "chopper_minlength") == 1000

    def test_coerce_valid_passthrough(self):
        from nanometa_live.core.config.parameter_mapping import _coerce_min_length
        assert _coerce_min_length(300, "chopper_minlength") == 300

    @staticmethod
    def _range_errors(**overrides):
        import inspect
        from nanometa_live.app.tabs.config_tab_helpers import _validate_numeric_ranges
        kwargs = {
            name: None
            for name in inspect.signature(_validate_numeric_ranges).parameters
        }
        kwargs.update(overrides)
        return _validate_numeric_ranges(**kwargs)

    def test_range_check_rejects_zero(self):
        assert any("Chopper minimum length" in e
                   for e in self._range_errors(chopper_minlength=0))
        assert any("Filtlong minimum length" in e
                   for e in self._range_errors(filtlong_minlength=0))

    def test_range_check_accepts_one(self):
        assert not any(
            "minimum length" in e
            for e in self._range_errors(chopper_minlength=1, filtlong_minlength=1)
        )

    def test_form_min_is_one(self):
        from nanometa_live.app.components.config_form import create_config_form
        from tests.test_amplicon_settings import _find_by_id
        form = create_config_form()
        for field_id in ("chopper-minlength-input", "filtlong-minlength-input"):
            widget = _find_by_id(form, field_id)
            assert widget is not None
            assert widget.min == 1, f"{field_id} must not offer the launch-breaking 0"

    def test_no_length_filter_copy_advises_zero(self):
        # "Set to 0 to disable" on the LENGTH filters fails nf-schema at
        # launch; the advice must not survive in the form copy. (Confidence
        # and hit-group fields legitimately accept 0 and keep their text.)
        from nanometa_live.app.components.config_form import create_config_form
        text = str(create_config_form())
        assert "Set to 0 to disable" not in text
        assert "amplicons; 0 disables" not in text
        assert "1 disables" in text


class TestN50AmpliconBands:
    def _card_str(self, n50, amplicon_mode):
        from nanometa_live.app.components.organism_components import ReadStatisticsCard
        return str(ReadStatisticsCard(
            mean_length=400.0, n50=n50, gc_content=50.0,
            source="seqkit", amplicon_mode=amplicon_mode,
        ))

    def test_amplicon_n50_not_red(self):
        # A 460 bp V3-V4 amplicon has N50 ~460 by design; the whole-genome
        # bands rendered it with the danger icon.
        out = self._card_str(460, amplicon_mode=True)
        assert "x-circle-fill" not in out
        assert "check-circle-fill" in out

    def test_wgs_short_n50_still_red(self):
        out = self._card_str(460, amplicon_mode=False)
        assert "x-circle-fill" in out

    def test_amplicon_very_short_n50_still_red(self):
        out = self._card_str(80, amplicon_mode=True)
        assert "x-circle-fill" in out


class TestAssemblyExposure:
    def test_default_config_keys(self, tmp_path):
        from nanometa_live.core.config.config_loader import ConfigLoader
        cfg = ConfigLoader(str(tmp_path)).create_default_config()
        assert cfg["enable_assembly"] is False
        assert cfg["assembler"] == "flye"

    def test_registry_carries_assembly_fields(self):
        from nanometa_live.app.tabs.config_field_registry import CONFIG_FORM_FIELDS
        mapping = dict(CONFIG_FORM_FIELDS)
        assert mapping["enable-assembly-input"] == "enable_assembly"
        assert mapping["assembler-input"] == "assembler"

    def test_form_renders_assembly_widgets(self):
        from nanometa_live.app.components.config_form import create_config_form
        from tests.test_amplicon_settings import _find_by_id
        form = create_config_form()
        switch = _find_by_id(form, "enable-assembly-input")
        select = _find_by_id(form, "assembler-input")
        assert switch is not None and switch.value is False
        assert select is not None and select.value == "flye"
        assert {o["value"] for o in select.options} == {"flye", "miniasm"}

    @staticmethod
    def _base_config(tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "reads.fastq.gz").write_bytes(b"")
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        return {
            "nanopore_output_directory": str(input_dir),
            "kraken_db": str(tmp_path / "kraken_db"),
            "results_output_directory": str(results_dir),
            "processing_mode": "batch",
            "sample_handling": "single_sample",
            "blast_validation": False,
        }

    def test_parameter_mapping_routes_assembly(self, tmp_path):
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params
        cfg = self._base_config(tmp_path)
        cfg.update({"enable_assembly": True, "assembler": "miniasm"})
        params = create_nextflow_params(cfg)
        assert params["enable_assembly"] is True
        assert params["assembler"] == "miniasm"

    def test_parameter_mapping_assembly_defaults_off(self, tmp_path):
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params
        params = create_nextflow_params(self._base_config(tmp_path))
        assert params["enable_assembly"] is False
        assert params["assembler"] == "flye"

    def test_parameter_mapping_coerces_unknown_assembler(self, tmp_path):
        # A value outside nanometanf's enum (flye/miniasm) would fail schema
        # validation at launch; the mapping must coerce it.
        from nanometa_live.core.config.parameter_mapping import create_nextflow_params
        cfg = self._base_config(tmp_path)
        cfg.update({"enable_assembly": True, "assembler": "canu"})
        params = create_nextflow_params(cfg)
        assert params["assembler"] == "flye"
