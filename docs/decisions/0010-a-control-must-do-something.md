# 0010. A control must do something

**Status:** accepted (2026-08, extended 2026-09-03)

## Context

The Configuration tab carried an "Alert Threshold" whose tooltip promised
sensitivity and that nothing read, a "Clean temp files" switch with no
consumer, a port field that was saved and ignored, and a "Check Interval"
that reached only a logged legacy parameter. A slider for BLAST identity
was decorative because a back-compat shim read a key no widget could
change.

## Decision

Before adding a form field, decide what reads it; before removing one,
check whether the function exists elsewhere or whether wiring it would be
destructive. The three field lists (`apply_config_changes`,
`initialize_form_from_config`, `detect_form_changes`) and the session draft
stay key-compatible. Numeric fields are checked in the browser before the
server applies, and a rejected Apply leaves the dirty badge in place. Form
fallbacks come from `config_loader.default_config()`.

## Consequences

`validation_identity_threshold` is the one identity key and feeds both
pipeline parameters. `chopper_minlength` and `chopper_quality` are the one
read filter and travel under every QC tool's parameter names.

## Evidence

`tests/test_negative_controls_form_field.py`, `tests/test_deployment_gui_fixes.py`.
