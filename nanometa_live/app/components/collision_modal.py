"""Output-directory collision modal.

Rendered into the main app layout and triggered by
``start_or_prompt_stop`` when the user clicks Start with an output
directory that already contains nanometanf results. Three actions
are offered, with "Move existing to subfolder" as the default
(safest, no data loss).

Component contract:
    create_collision_modal()
        Returns a dbc.Modal with a fixed component tree. The body
        contents (which subdirs were found, the outdir path) are
        populated via callbacks at runtime by writing to the
        ``collision-modal-body`` Div's ``children`` prop.

Element ids the callbacks rely on:
    collision-modal             dbc.Modal (is_open prop is toggled)
    collision-modal-body        Div whose children describe the find
    collision-archive-btn       primary button: archive + start fresh
    collision-resume-btn        secondary button: continue with -resume
    collision-cancel-btn        light button: close, no run
"""

from __future__ import annotations

from typing import List

import dash_bootstrap_components as dbc
from dash import html


def create_collision_modal() -> dbc.Modal:
    """Build the static modal scaffold; body contents are filled later."""
    return dbc.Modal(
        [
            dbc.ModalHeader(
                dbc.ModalTitle(
                    [
                        html.I(
                            className="bi bi-folder-fill text-warning me-2"
                        ),
                        "Results already exist in this folder",
                    ]
                ),
                close_button=True,
            ),
            dbc.ModalBody(id="collision-modal-body"),
            dbc.ModalFooter(
                [
                    dbc.Button(
                        "Cancel",
                        id="collision-cancel-btn",
                        color="light",
                        className="me-2",
                    ),
                    dbc.Button(
                        [
                            html.I(className="bi bi-play-fill me-2"),
                            "Continue (resume)",
                        ],
                        id="collision-resume-btn",
                        color="secondary",
                        className="me-2",
                    ),
                    dbc.Button(
                        [
                            html.I(className="bi bi-archive-fill me-2"),
                            "Move existing & start fresh",
                        ],
                        id="collision-archive-btn",
                        color="primary",
                    ),
                ]
            ),
        ],
        id="collision-modal",
        is_open=False,
        centered=True,
        size="lg",
        backdrop="static",
    )


def render_collision_body(outdir: str, found: List[str]) -> html.Div:
    """Return the body children for the modal given the detection result.

    Kept as a pure function so it can be unit-tested without spinning
    up the Dash callback graph.
    """
    if not found:
        # Should not normally render; defensive fallback.
        return html.Div(
            "No existing results were detected. You can safely start.",
            className="text-muted small",
        )

    subdir_chips = [
        dbc.Badge(
            name + "/",
            color="warning",
            text_color="dark",
            className="me-1 mb-1",
        )
        for name in found
    ]

    return html.Div(
        [
            html.P(
                [
                    html.Strong("Output directory:"),
                    html.Code(
                        outdir,
                        className="ms-2",
                        style={"wordBreak": "break-all"},
                    ),
                ],
                className="mb-2",
            ),
            html.P(
                "The following result subdirectories already contain "
                "files from a previous run:",
                className="mb-2",
            ),
            html.Div(subdir_chips, className="mb-3"),
            html.Hr(),
            html.P(
                [
                    html.Strong("What would you like to do?"),
                ],
                className="mb-2",
            ),
            html.Ul(
                [
                    html.Li(
                        [
                            html.Strong("Move existing & start fresh"),
                            " -- ",
                            "Renames the subdirectories above into a "
                            "timestamped ",
                            html.Code("_archive_<time>/"),
                            " subfolder so the new run starts clean. "
                            "(Recommended.)",
                        ],
                        className="mb-2",
                    ),
                    html.Li(
                        [
                            html.Strong("Continue (resume)"),
                            " -- ",
                            "Reuses the existing results and asks "
                            "Nextflow to skip already-completed steps "
                            "via ",
                            html.Code("-resume"),
                            ". Only safe when the new input is the same "
                            "as the previous run.",
                        ],
                        className="mb-2",
                    ),
                    html.Li(
                        [
                            html.Strong("Cancel"),
                            " -- ",
                            "Close this dialog so you can change the "
                            "Results Output Directory in the "
                            "Configuration tab.",
                        ]
                    ),
                ],
                className="mb-0",
            ),
        ]
    )
