"""Per-sample attribution row + popovers for the pathogen alert cards.

Split out of ``pathogen_alert`` for the code-size gate; that module
re-exports every name, so importers are unaffected.
"""

import hashlib
from typing import Any, Dict, List, Optional

import dash_bootstrap_components as dbc
from dash import html


def _attribution_pill_id(samples: List[Dict[str, Any]], tier: str) -> str:
    """Stable id used as the Popover target for the "+N more" pill.

    Hashing the (tier, sample-name list) gives a deterministic id that
    survives re-renders within a tick but is unique across distinct
    pathogen alert cards on the page. dbc.Popover requires the target
    to exist in the layout when the page renders, so the id must be
    embedded in the chip itself.
    """
    seed = tier + "|" + "|".join(s.get("sample", "") for s in samples)
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()[:10]
    return f"alert-attribution-pill-{digest}"


# --- Per-tier chip color tokens (bg / border / text) ---
# Text token #664d03 is the CLAUDE.md-locked amber. The earlier
# #856404 here was Bootstrap's amber-on-amber default, which only
# clears AA at ~4.2:1 -- borderline for chip-size text.
_CHIP_COLORS = {
    "critical": ("#f8d7da", "rgba(114,28,36,0.35)", "#721c24"),
    "high":     ("#fff3cd", "rgba(102,77,3,0.35)",  "#664d03"),
    "watched":  ("#d1ecf1", "rgba(12,84,96,0.35)",  "#0c5460"),
}
_CHIP_NC    = ("#e9ecef", "#ced4da", "#6c757d")   # negative-control override
_CHIP_MORE  = ("#e9ecef", "#ced4da", "#495057")   # "+X more" pill


def _render_sample_attribution(
    samples: Optional[List[Dict[str, Any]]],
    tier: str,
    max_inline: int = 3,
    attribution_taxid: Optional[int] = None,
) -> Optional[html.Div]:
    """
    Render the "DETECTED IN:" attribution row for a pathogen alert card.

    Suppression rule:
      - Returns None when samples is empty.
      - A "watched" hit spanning more than one sample names its highest-count
        sample and summarises the rest as a "+N more" pill whose popover
        carries the full list. A chip per barcode is too heavy for a moderate
        hit at scale; naming none of them left the card saying a detection
        spanned barcodes without saying which.

    Chip colors are tier-specific with a negative-control override.
    Tooltip: "{reads} reads | {abundance}% of sample | #{rank} by read count"

    Args:
        samples: List of {sample, reads, abundance, is_negative_control} dicts,
                 already sorted descending by reads.
        tier:    "critical", "high", or "watched".
        max_inline: Maximum chips shown before a "+X more" pill (default 3).

    Returns:
        html.Div attribution row, or None when suppressed.
    """
    if not samples:
        return None

    # A multi-sample watched hit names its highest-count sample and summarises
    # the rest as a count pill. Chips per barcode stay suppressed here for the
    # component budget at 96 barcodes (round-2 scale audit), but naming none of
    # them left the card reading "DETECTED IN: 3 samples" while the critical
    # cards above it named theirs -- the operator could see that a moderate hit
    # spanned barcodes and not which (observed live, 2026-09-01). One chip is
    # 1/96th of the cost the original suppression was avoiding.
    summarise_only = tier == "watched" and len(samples) > 1
    if summarise_only:
        max_inline = 1

    # Determine chip palette for this tier
    tier_key = tier if tier in _CHIP_COLORS else "watched"
    bg, border, text = _CHIP_COLORS[tier_key]

    chip_style_base = {
        "borderRadius": "3px",
        "fontSize": "10px",
        "fontWeight": "500",
        "padding": "2px 7px",
        "border": f"1px solid {border}",
        "display": "inline-block",
        "lineHeight": "1.4",
    }

    # Build chips (truncate at max_inline)
    visible = samples[:max_inline]
    overflow = len(samples) - max_inline

    chips = []
    for rank, s in enumerate(visible, start=1):
        reads = s.get("reads", 0)
        abund = s.get("abundance", 0.0)
        label = s.get("sample", "")
        is_nc = s.get("is_negative_control", False)

        if is_nc:
            chip_bg, chip_border, chip_text = _CHIP_NC
            label = f"{label} (NC)"
        else:
            chip_bg, chip_border, chip_text = bg, border, text

        tooltip = f"{reads:,} reads | {abund:.2f}% of sample | #{rank} by read count"

        chips.append(
            html.Span(
                label,
                title=tooltip,
                style={
                    **chip_style_base,
                    "backgroundColor": chip_bg,
                    "borderColor": chip_border,
                    "color": chip_text,
                }
            )
        )

    popover_components = []
    if overflow > 0:
        pill_bg, pill_border, pill_text = _CHIP_MORE
        pill_id = _attribution_pill_id(samples, tier_key)
        # One form for every tier now that the watched tier also names its
        # top sample: "barcode06, +2 more" reads unambiguously, where
        # "barcode06, 3 samples" left the reader working out whether the
        # three included the one already named.
        pill_label = f"+{overflow} more"
        chips.append(
            html.Span(
                pill_label,
                id=pill_id,
                title=(
                    f"Click to see all {len(samples)} samples where this "
                    f"pathogen was detected"
                ),
                style={
                    **chip_style_base,
                    "backgroundColor": pill_bg,
                    "borderColor": pill_border,
                    "color": pill_text,
                    "cursor": "pointer",
                    "textDecoration": "underline dotted",
                    "textUnderlineOffset": "2px",
                }
            )
        )
        # Popover lists every sample, not just the overflow. Operators
        # asking "which barcodes carry this pathogen?" want the complete
        # list, not the tail.
        #
        # With an attribution taxid the popover ships EMPTY and its rows
        # are built on open by fill_attribution_popover from the shared
        # per-tick organisms memo: the eager version serialized one row
        # per SAMPLE per CARD every tick -- 17.8k-55k components at 24-96
        # barcodes x 129 hits (round-2 audit, 2026-08-22).
        if attribution_taxid is not None:
            popover_components.append(
                _build_lazy_attribution_popover(
                    pill_id, attribution_taxid, len(samples))
            )
        else:
            popover_components.append(
                _build_attribution_popover(samples, pill_id, tier_key)
            )

    return html.Div(
        [
            html.Span(
                [
                    html.Span("DETECTED IN:", className="dashboard-attribution-label-full"),
                    html.Span("IN:", className="dashboard-attribution-label-short"),
                ]
            ),
            *chips,
            *popover_components,
        ],
        className="dashboard-attribution-row",
    )


def _build_lazy_attribution_popover(
    target_id: str, attribution_taxid: int, n_samples: int
) -> dbc.Popover:
    """Empty popover shell; rows arrive on open from the organisms memo."""
    return dbc.Popover(
        [
            dbc.PopoverHeader(
                f"All {n_samples} samples (sorted by read count)",
                style={"fontSize": "12px", "fontWeight": "600"},
            ),
            dbc.PopoverBody(
                html.Div(
                    id={"type": "attr-popover-body",
                        "taxid": int(attribution_taxid)}),
                style={"maxHeight": "320px", "overflowY": "auto",
                       "padding": "8px 12px"},
            ),
        ],
        id={"type": "attr-popover", "taxid": int(attribution_taxid)},
        target=target_id,
        trigger="legacy",
        placement="bottom",
        hide_arrow=False,
    )


def attribution_popover_rows(samples: List[Dict[str, Any]]) -> List[html.Div]:
    """Popover rows: one per sample with reads + abundance, NC-marked."""
    rows = []
    for rank, s in enumerate(samples, start=1):
        sample_label = s.get("sample", "")
        reads = s.get("reads", 0)
        abund = s.get("abundance", 0.0)
        is_nc = s.get("is_negative_control", False)
        suffix = " (NC)" if is_nc else ""
        text_color = "#6c757d" if is_nc else None
        rows.append(
            html.Div(
                [
                    html.Span(
                        f"{rank}.",
                        style={
                            "display": "inline-block",
                            "width": "1.6em",
                            "color": "#6c757d",
                            "fontVariantNumeric": "tabular-nums",
                        },
                    ),
                    html.Span(
                        f"{sample_label}{suffix}",
                        style={
                            "fontWeight": "600",
                            "marginRight": "0.5em",
                            "color": text_color or "inherit",
                        },
                    ),
                    html.Span(
                        f"{reads:,} reads ({abund:.2f}%)",
                        style={"color": "#6c757d", "fontSize": "0.85em"},
                    ),
                ],
                style={"padding": "2px 0", "fontSize": "12px"},
            )
        )
    return rows


def _build_attribution_popover(
    samples: List[Dict[str, Any]],
    target_id: str,
    tier_key: str,
) -> dbc.Popover:
    """Popover listing every triggering sample with reads + abundance.

    Hung off the "+N more" pill so an operator can answer the clinical
    question "which of 24 barcodes carries this pathogen?" Closes
    P0-T01 from docs/audit-2026-04-28-throughput-ux.md, where the pill
    was a non-interactive dead end. Eager form; the alert panel uses the
    lazy shell above.
    """
    return dbc.Popover(
        [
            dbc.PopoverHeader(
                f"All {len(samples)} samples (sorted by read count)",
                style={"fontSize": "12px", "fontWeight": "600"},
            ),
            dbc.PopoverBody(
                attribution_popover_rows(samples),
                style={"maxHeight": "320px", "overflowY": "auto", "padding": "8px 12px"},
            ),
        ],
        target=target_id,
        trigger="legacy",
        placement="bottom",
        hide_arrow=False,
    )
