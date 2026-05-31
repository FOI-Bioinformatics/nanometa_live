"""
Plotly Theme Configuration for Nanometa Live.

Provides consistent, professional styling for all Plotly visualizations
in the dashboard. Optimized for scientific/medical applications with
emphasis on clarity and accessibility.
"""

import plotly.io as pio
import plotly.graph_objects as go
from typing import Dict, Any


# Color palette aligned with CSS variables
COLORS = {
    # Status colors (traffic light system)
    "safe": "#28a745",
    "safe_light": "#d4edda",
    "warning": "#ffc107",
    "warning_light": "#fff3cd",
    "danger": "#dc3545",
    "danger_light": "#f8d7da",
    "critical": "#8b0000",
    "info": "#17a2b8",
    "info_light": "#d1ecf1",

    # Threat level colors
    "threat_critical": "#8b0000",
    "threat_high": "#dc3545",
    "threat_moderate": "#fd7e14",
    "threat_low": "#28a745",
    "threat_unknown": "#6c757d",

    # UI colors
    "primary": "#007bff",
    "secondary": "#6c757d",
    "dark": "#343a40",
    "light": "#f8f9fa",
    "white": "#ffffff",
    "gray_100": "#f8f9fa",
    "gray_200": "#e9ecef",
    "gray_300": "#dee2e6",
    "gray_400": "#ced4da",
    "gray_500": "#adb5bd",
    "gray_600": "#6c757d",
    "gray_700": "#495057",
    "gray_800": "#343a40",
    "gray_900": "#212529",
}

# Color sequences for charts
COLORWAY_DEFAULT = [
    "#007bff",  # Primary blue
    "#28a745",  # Green
    "#dc3545",  # Red
    "#ffc107",  # Yellow
    "#17a2b8",  # Cyan
    "#6f42c1",  # Purple
    "#fd7e14",  # Orange
    "#20c997",  # Teal
    "#e83e8c",  # Pink
    "#6c757d",  # Gray
]

# Viridis-based palette for colorblind accessibility
COLORWAY_VIRIDIS = [
    "#440154",
    "#482878",
    "#3e4989",
    "#31688e",
    "#26828e",
    "#1f9e89",
    "#35b779",
    "#6ece58",
    "#b5de2b",
    "#fde725",
]

# Standard chart configuration for dcc.Graph components
CHART_CONFIG = {
    "displayModeBar": True,
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {"format": "png", "height": 800, "width": 1200, "scale": 2}
}


def get_nanometa_template() -> Dict[str, Any]:
    """
    Generate the Nanometa Live Plotly template.

    Returns:
        Dict containing the full template specification
    """
    return {
        "layout": {
            # Preserve operator zoom/pan/selection across the periodic figure
            # rebuilds that drive the live dashboard. A constant value is all
            # Plotly needs -- it is compared per-graph between successive
            # figures, so one shared constant keeps each chart's view stable
            # without coupling unrelated graphs.
            "uirevision": "nanometa",

            # Background colors
            "paper_bgcolor": COLORS["white"],
            "plot_bgcolor": COLORS["white"],

            # Font configuration
            "font": {
                "family": "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
                "size": 13,
                "color": COLORS["gray_700"]
            },

            # Title styling
            "title": {
                "font": {
                    "family": "Inter, system-ui, sans-serif",
                    "size": 20,
                    "color": COLORS["gray_800"]
                },
                "x": 0.5,
                "xanchor": "center",
                "yanchor": "top"
            },

            # X-axis defaults
            "xaxis": {
                "showgrid": True,
                "gridcolor": COLORS["gray_200"],
                "gridwidth": 1,
                "zeroline": True,
                "zerolinecolor": COLORS["gray_400"],
                "zerolinewidth": 1,
                "linecolor": COLORS["gray_400"],
                "linewidth": 1,
                "tickfont": {"size": 12, "color": COLORS["gray_600"]},
                "title": {"font": {"size": 13, "color": COLORS["gray_700"]}}
            },

            # Y-axis defaults
            "yaxis": {
                "showgrid": True,
                "gridcolor": COLORS["gray_200"],
                "gridwidth": 1,
                "zeroline": True,
                "zerolinecolor": COLORS["gray_400"],
                "zerolinewidth": 1,
                "linecolor": COLORS["gray_400"],
                "linewidth": 1,
                "tickfont": {"size": 12, "color": COLORS["gray_600"]},
                "title": {"font": {"size": 13, "color": COLORS["gray_700"]}}
            },

            # Color sequence
            "colorway": COLORWAY_DEFAULT,

            # Hover behavior
            "hovermode": "closest",
            "hoverlabel": {
                "bgcolor": COLORS["white"],
                "bordercolor": COLORS["gray_400"],
                "font": {
                    "family": "Inter, system-ui, sans-serif",
                    "size": 12,
                    "color": COLORS["gray_700"]
                },
                "namelength": -1
            },

            # Legend
            "legend": {
                "bgcolor": "rgba(255, 255, 255, 0.8)",
                "bordercolor": COLORS["gray_300"],
                "borderwidth": 1,
                "font": {"size": 11, "color": COLORS["gray_700"]},
                "orientation": "h",
                "yanchor": "bottom",
                "y": -0.2,
                "xanchor": "center",
                "x": 0.5
            },

            # Margins
            "margin": {"l": 60, "r": 40, "t": 60, "b": 60},

            # Annotations defaults
            "annotationdefaults": {
                "font": {"size": 11, "color": COLORS["gray_700"]},
                "showarrow": False
            },

            # Transition for smooth updates
            "transition": {
                "duration": 300,
                "easing": "cubic-in-out"
            }
        },

        # Data trace defaults
        "data": {
            "bar": [{
                "marker": {
                    "line": {"color": COLORS["gray_800"], "width": 0.5}
                },
                "opacity": 0.9
            }],
            "scatter": [{
                "marker": {
                    "line": {"color": COLORS["white"], "width": 1}
                }
            }],
            "pie": [{
                "marker": {
                    "line": {"color": COLORS["white"], "width": 2}
                },
                "textfont": {"size": 11}
            }],
            "indicator": [{
                "title": {"font": {"size": 14, "color": COLORS["gray_600"]}},
                "number": {"font": {"size": 36, "color": COLORS["gray_800"]}}
            }]
        }
    }


def get_dark_mode_template() -> Dict[str, Any]:
    """
    Generate dark mode variant of the Nanometa template.

    Returns:
        Dict containing the dark mode template specification
    """
    dark_colors = {
        "bg_primary": "#1a1d21",
        "bg_secondary": "#212529",
        "text_primary": "#f8f9fa",
        "text_secondary": "#adb5bd",
        "border": "#495057",
        "grid": "#343a40"
    }

    return {
        "layout": {
            # See get_nanometa_template: preserve UI state across live rebuilds.
            "uirevision": "nanometa",
            "paper_bgcolor": dark_colors["bg_primary"],
            "plot_bgcolor": dark_colors["bg_secondary"],
            "font": {
                "family": "Inter, system-ui, sans-serif",
                "size": 12,
                "color": dark_colors["text_primary"]
            },
            "title": {
                "font": {"color": dark_colors["text_primary"]}
            },
            "xaxis": {
                "gridcolor": dark_colors["grid"],
                "zerolinecolor": dark_colors["border"],
                "linecolor": dark_colors["border"],
                "tickfont": {"color": dark_colors["text_secondary"]}
            },
            "yaxis": {
                "gridcolor": dark_colors["grid"],
                "zerolinecolor": dark_colors["border"],
                "linecolor": dark_colors["border"],
                "tickfont": {"color": dark_colors["text_secondary"]}
            },
            "hoverlabel": {
                "bgcolor": dark_colors["bg_secondary"],
                "bordercolor": dark_colors["border"],
                "font": {"color": dark_colors["text_primary"]}
            },
            "legend": {
                "bgcolor": "rgba(33, 37, 41, 0.8)",
                "bordercolor": dark_colors["border"],
                "font": {"color": dark_colors["text_secondary"]}
            },
            "colorway": COLORWAY_DEFAULT
        }
    }


def register_templates():
    """Register custom templates with Plotly."""
    # Register main template
    pio.templates["nanometa"] = go.layout.Template(get_nanometa_template())

    # Register dark mode template
    pio.templates["nanometa_dark"] = go.layout.Template(get_dark_mode_template())

    # Note: Template combination (nanometa+seaborn) is handled automatically
    # by Plotly when using template="seaborn+nanometa" in figure creation


def set_default_template(dark_mode: bool = False):
    """
    Set the default Plotly template.

    Args:
        dark_mode: If True, use dark mode template
    """
    register_templates()

    if dark_mode:
        pio.templates.default = "nanometa_dark"
    else:
        pio.templates.default = "nanometa"


def apply_theme_to_figure(
    fig: go.Figure,
    dark_mode: bool = False
) -> go.Figure:
    """
    Apply Nanometa theme to an existing figure.

    Args:
        fig: Plotly Figure object
        dark_mode: If True, apply dark mode styling

    Returns:
        Updated Figure with theme applied
    """
    if "nanometa" not in pio.templates:
        register_templates()

    template = "nanometa_dark" if dark_mode else "nanometa"
    fig.update_layout(template=template)

    return fig


def get_current_template() -> str:
    """Return the currently active Plotly template name."""
    return pio.templates.default or "nanometa"


def get_threat_color(threat_level: str) -> str:
    """
    Get the appropriate color for a threat level.

    Args:
        threat_level: One of 'critical', 'high', 'moderate', 'low', 'unknown'

    Returns:
        Hex color string
    """
    color_map = {
        "critical": COLORS["threat_critical"],
        "high": COLORS["threat_high"],
        "moderate": COLORS["threat_moderate"],
        "low": COLORS["threat_low"],
        "unknown": COLORS["threat_unknown"]
    }
    return color_map.get(threat_level.lower(), COLORS["threat_unknown"])


def get_status_color(status: str) -> str:
    """
    Get the appropriate color for a status.

    Args:
        status: One of 'success', 'warning', 'danger', 'info'

    Returns:
        Hex color string
    """
    color_map = {
        "success": COLORS["safe"],
        "good": COLORS["safe"],
        "warning": COLORS["warning"],
        "danger": COLORS["danger"],
        "error": COLORS["danger"],
        "info": COLORS["info"]
    }
    return color_map.get(status.lower(), COLORS["secondary"])


# Theme configurations for export
LIGHT_THEME = get_nanometa_template()
DARK_THEME = get_dark_mode_template()


def _safe_register_templates():
    """
    Safely register templates, handling import-time errors.
    Called lazily when templates are first needed.
    """
    try:
        if "nanometa" not in pio.templates:
            register_templates()
    except Exception:
        # Templates will be registered when first used
        pass


# Try to register templates on import, but don't fail if not possible
_safe_register_templates()
