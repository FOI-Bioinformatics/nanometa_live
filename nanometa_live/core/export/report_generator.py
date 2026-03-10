"""
HTML Report Generator for Nanometa Live.

Produces self-contained HTML reports with inline Plotly charts,
suitable for offline viewing, printing, and archival.
"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from nanometa_live.core.utils.data_loaders import (
    get_qc_stats,
    load_fastp_data,
    load_kraken_data,
)
from nanometa_live.core.utils.sample_detector import (
    get_available_samples,
    resolve_analysis_directory,
)

logger = logging.getLogger(__name__)

# Plotly CDN version to embed (minified JS is fetched at build time or bundled)
_PLOTLY_CDN_URL = "https://cdn.plot.ly/plotly-2.35.2.min.js"


class ReportGenerator:
    """Generate self-contained HTML reports from nanometanf results."""

    def __init__(self, results_dir: str, config: Dict[str, Any]):
        self.results_dir = resolve_analysis_directory(results_dir)
        self.config = config
        self._plotly_js: Optional[str] = None

    def generate(
        self, output_dir: str, samples: Optional[List[str]] = None,
        include_raw: bool = True
    ) -> Path:
        """
        Generate complete export: HTML report + raw files + metadata.

        Args:
            output_dir: Directory to write the export into.
            samples: Specific samples to include, or None for all.
            include_raw: Whether to copy raw result files.

        Returns:
            Path to the generated report.html file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Discover samples
        all_samples = get_available_samples(self.results_dir)
        if samples:
            selected_samples = [s for s in samples if s in all_samples and s != "All Samples"]
        else:
            selected_samples = [s for s in all_samples if s != "All Samples"]

        if not selected_samples:
            selected_samples = [None]  # Aggregated view only

        # Collect data
        report_data = self._collect_data(selected_samples)

        # Build HTML
        html_content = self._build_html_report(report_data)
        report_file = output_path / "report.html"
        report_file.write_text(html_content, encoding="utf-8")
        logger.info("Report written to %s", report_file)

        # Copy raw files
        if include_raw:
            self._copy_raw_files(str(output_path))

        # Write metadata
        self._write_metadata(str(output_path), report_data)

        return report_file

    def _collect_data(self, samples: List[Optional[str]]) -> Dict[str, Any]:
        """Collect all data needed for the report."""
        # Aggregated data
        kraken_all = load_kraken_data(self.results_dir, None)
        qc_all = get_qc_stats(self.results_dir, None)
        fastp_all = load_fastp_data(self.results_dir, None)

        # Classification summary from aggregated kraken
        classified, unclassified = self._get_classification_counts(kraken_all)

        # Watchlist screening
        watched_results = self._screen_watchlist(kraken_all)

        # Alerts
        alerts = self._collect_alerts()

        # Per-sample data
        per_sample = {}
        for sample in samples:
            if sample is None:
                continue
            sample_kraken = load_kraken_data(self.results_dir, sample)
            sample_qc = get_qc_stats(self.results_dir, sample)
            s_classified, s_unclassified = self._get_classification_counts(sample_kraken)

            # Top organisms
            organisms = self._extract_organisms(sample_kraken)

            per_sample[sample] = {
                "classified": s_classified,
                "unclassified": s_unclassified,
                "qc": sample_qc,
                "organisms": organisms[:20],
            }

        return {
            "generated_at": datetime.now().isoformat(),
            "results_dir": self.results_dir,
            "config": {
                k: v for k, v in self.config.items()
                if isinstance(v, (str, int, float, bool, type(None)))
            },
            "sample_count": len([s for s in samples if s is not None]),
            "samples": [s for s in samples if s is not None],
            "classified_total": classified,
            "unclassified_total": unclassified,
            "qc_summary": qc_all,
            "fastp_summary": fastp_all,
            "watched_results": watched_results,
            "alerts": alerts,
            "per_sample": per_sample,
        }

    def _get_classification_counts(self, df: pd.DataFrame):
        """Extract classified/unclassified read counts from kraken dataframe."""
        if df.empty:
            return 0, 0
        unclassified_row = df[df["taxid"] == 0]
        root_row = df[df["taxid"] == 1]
        unclassified = int(unclassified_row["reads"].sum()) if not unclassified_row.empty else 0
        classified = int(root_row["cumul_reads"].sum()) if not root_row.empty else 0
        if classified == 0:
            # Fallback: sum all non-unclassified reads
            classified = int(df[df["taxid"] != 0]["reads"].sum())
        return classified, unclassified

    def _extract_organisms(self, df: pd.DataFrame, max_n: int = 20) -> List[Dict[str, Any]]:
        """Extract top organisms at species/genus level."""
        if df.empty:
            return []
        species = df[df["rank"].isin(["S", "G"])].copy()
        if species.empty:
            return []
        species = species.sort_values("reads", ascending=False).head(max_n)

        total_reads = df["reads"].sum()
        results = []
        for _, row in species.iterrows():
            abundance = (row["reads"] / total_reads * 100) if total_reads > 0 else 0
            results.append({
                "name": str(row["name"]).strip(),
                "taxid": int(row["taxid"]),
                "reads": int(row["reads"]),
                "rank": str(row["rank"]).strip(),
                "abundance": round(abundance, 2),
            })
        return results

    def _screen_watchlist(self, kraken_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Screen kraken results against configured watchlist."""
        results = []
        try:
            from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
            wm = get_watchlist_manager()
            active_entries = wm.get_active_entries()

            if kraken_df.empty or not active_entries:
                return results

            for entry in active_entries:
                taxid = entry.get("taxid")
                name = entry.get("name", "Unknown")
                threat_level = entry.get("threat_level", "unknown")

                matched_rows = kraken_df[kraken_df["taxid"] == taxid] if taxid else pd.DataFrame()
                if matched_rows.empty and name:
                    # Try name match
                    matched_rows = kraken_df[
                        kraken_df["name"].str.strip().str.lower() == name.lower().strip()
                    ]

                reads = int(matched_rows["reads"].sum()) if not matched_rows.empty else 0
                total = int(kraken_df["reads"].sum()) if not kraken_df.empty else 0
                abundance = (reads / total * 100) if total > 0 else 0

                results.append({
                    "name": name,
                    "taxid": taxid,
                    "threat_level": threat_level,
                    "reads": reads,
                    "abundance": round(abundance, 3),
                    "detected": reads > 0,
                })

        except Exception as e:
            logger.warning("Could not screen watchlist: %s", e)

        return results

    def _collect_alerts(self) -> List[Dict[str, Any]]:
        """Collect current alerts from the alert engine."""
        try:
            from nanometa_live.core.utils.alert_engine import get_alert_engine
            engine = get_alert_engine()
            return [a.to_dict() for a in engine.get_active_alerts()]
        except Exception as e:
            logger.warning("Could not collect alerts: %s", e)
            return []

    def _get_plotly_js(self) -> str:
        """Get Plotly.js source for inline embedding."""
        if self._plotly_js is not None:
            return self._plotly_js

        # Try to find a local copy bundled with Dash
        try:
            import dash
            dash_dir = Path(dash.__file__).parent
            # Dash bundles plotly.js in its package
            candidates = [
                dash_dir / "dcc" / "plotly.min.js",
                dash_dir / "dcc" / "async-plotlyjs.js",
            ]
            # Also check plotly's own bundled JS
            import plotly
            plotly_dir = Path(plotly.__file__).parent
            candidates.append(plotly_dir / "package_data" / "plotly.min.js")

            for candidate in candidates:
                if candidate.exists():
                    self._plotly_js = candidate.read_text(encoding="utf-8")
                    logger.info("Using local plotly.js from %s", candidate)
                    return self._plotly_js
        except Exception:
            pass

        # Fallback: use CDN reference (not fully self-contained but functional)
        logger.warning(
            "Could not find local plotly.js bundle. "
            "Report will reference CDN: %s", _PLOTLY_CDN_URL
        )
        self._plotly_js = ""
        return self._plotly_js

    def _build_html_report(self, data: Dict[str, Any]) -> str:
        """Build self-contained HTML string from collected data."""
        from jinja2 import Environment, FileSystemLoader

        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True,
        )
        env.filters["format_number"] = lambda v: f"{v:,}" if isinstance(v, (int, float)) else str(v)
        env.filters["format_pct"] = lambda v: f"{v:.1f}%" if isinstance(v, (int, float)) else str(v)

        template = env.get_template("report.html")

        # Build Plotly figures as JSON
        charts = self._build_charts(data)

        # Get plotly.js for embedding
        plotly_js = self._get_plotly_js()
        use_cdn = not plotly_js

        # Serialize charts dict to JSON for embedding in template script
        charts_json = json.dumps(charts)

        return template.render(
            data=data,
            charts=charts_json,
            plotly_js_inline=plotly_js,
            plotly_cdn_url=_PLOTLY_CDN_URL if use_cdn else "",
            generated_at=data["generated_at"],
            app_name="Nanometa Live",
        )

    def _build_charts(self, data: Dict[str, Any]) -> Dict[str, str]:
        """Build all Plotly charts and serialize to JSON."""
        charts = {}

        # Classification donut (aggregated)
        charts["classification_donut"] = self._fig_to_json(
            self._create_classification_donut(
                data["classified_total"],
                data["unclassified_total"],
                title="Overall Classification"
            )
        )

        # Per-sample donuts
        for sample, sdata in data.get("per_sample", {}).items():
            key = f"donut_{sample}"
            charts[key] = self._fig_to_json(
                self._create_classification_donut(
                    sdata["classified"],
                    sdata["unclassified"],
                    title=sample,
                    compact=True,
                )
            )

            # Organism abundance bar chart
            if sdata.get("organisms"):
                bar_key = f"organisms_{sample}"
                charts[bar_key] = self._fig_to_json(
                    self._create_organism_bar(sdata["organisms"], title=sample)
                )

        return charts

    def _create_classification_donut(
        self, classified: int, unclassified: int,
        title: str = "", compact: bool = False
    ) -> go.Figure:
        """Create classification donut chart for the report."""
        total = classified + unclassified
        if total == 0:
            fig = go.Figure()
            fig.add_annotation(text="No data", x=0.5, y=0.5, showarrow=False)
            fig.update_layout(height=200, margin=dict(l=10, r=10, t=30, b=10))
            return fig

        rate = classified / total * 100
        if rate >= 80:
            rate_color = "#28a745"
        elif rate >= 60:
            rate_color = "#ffc107"
        else:
            rate_color = "#dc3545"

        fig = go.Figure(go.Pie(
            labels=["Classified", "Unclassified"],
            values=[classified, unclassified],
            hole=0.6,
            marker=dict(
                colors=["#007bff", "#dee2e6"],
                line=dict(color="#ffffff", width=2)
            ),
            textinfo="percent",
            textposition="outside",
            hovertemplate="<b>%{label}</b><br>Count: %{value:,}<br>%{percent}<extra></extra>",
        ))

        fig.add_annotation(
            text=f"<b>{rate:.0f}%</b><br><span style='font-size:10px'>classified</span>",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=20, color=rate_color),
        )

        height = 220 if compact else 300
        fig.update_layout(
            title=dict(text=title, x=0.5, font=dict(size=14)),
            height=height,
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor="white",
            plot_bgcolor="white",
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.15, x=0.5, xanchor="center"),
        )
        return fig

    def _create_organism_bar(
        self, organisms: List[Dict[str, Any]], title: str = ""
    ) -> go.Figure:
        """Create horizontal bar chart of organism abundance."""
        if not organisms:
            fig = go.Figure()
            fig.add_annotation(text="No organisms detected", x=0.5, y=0.5, showarrow=False)
            return fig

        names = [o["name"][:40] for o in reversed(organisms)]
        reads = [o["reads"] for o in reversed(organisms)]
        abundances = [o["abundance"] for o in reversed(organisms)]

        fig = go.Figure(go.Bar(
            y=names,
            x=reads,
            orientation="h",
            marker=dict(color="#007bff", line=dict(color="#343a40", width=0.5)),
            hovertemplate="<b>%{y}</b><br>Reads: %{x:,}<br>Abundance: %{customdata:.2f}%<extra></extra>",
            customdata=abundances,
        ))

        height = max(250, len(organisms) * 25 + 80)
        fig.update_layout(
            title=dict(text=f"Top Organisms - {title}", x=0.5, font=dict(size=14)),
            xaxis=dict(title="Read Count"),
            yaxis=dict(title=""),
            height=height,
            margin=dict(l=200, r=30, t=40, b=40),
            paper_bgcolor="white",
            plot_bgcolor="white",
        )
        return fig

    @staticmethod
    def _fig_to_json(fig: go.Figure) -> str:
        """Serialize a Plotly figure to JSON for template embedding."""
        return pio.to_json(fig, validate=False)

    def _copy_raw_files(self, output_dir: str):
        """Copy raw result files to output_dir/raw/."""
        raw_dir = os.path.join(output_dir, "raw")
        subdirs = ["kraken2", "fastp", "validation"]

        for subdir in subdirs:
            src = os.path.join(self.results_dir, subdir)
            dst = os.path.join(raw_dir, subdir)
            if os.path.isdir(src):
                try:
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                    logger.info("Copied %s to %s", src, dst)
                except Exception as e:
                    logger.warning("Could not copy %s: %s", src, e)

    def _write_metadata(self, output_dir: str, data: Dict[str, Any]):
        """Write summary.json and metadata.json."""
        # summary.json - machine-readable results summary
        summary = {
            "generated_at": data["generated_at"],
            "sample_count": data["sample_count"],
            "samples": data["samples"],
            "classified_reads": data["classified_total"],
            "unclassified_reads": data["unclassified_total"],
            "total_reads": data["classified_total"] + data["unclassified_total"],
            "classification_rate": (
                round(data["classified_total"] / max(1, data["classified_total"] + data["unclassified_total"]) * 100, 2)
            ),
            "watched_species_detected": [
                w for w in data.get("watched_results", []) if w.get("detected")
            ],
            "alert_count": len(data.get("alerts", [])),
            "qc_source": data.get("qc_summary", {}).get("source", "none"),
        }

        summary_path = os.path.join(output_dir, "summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, default=str)

        # metadata.json - run configuration and provenance
        metadata = {
            "generated_at": data["generated_at"],
            "generator": "Nanometa Live Report Generator",
            "results_directory": data["results_dir"],
            "config": data.get("config", {}),
            "qc_summary": {
                k: v for k, v in data.get("qc_summary", {}).items()
                if isinstance(v, (str, int, float, bool, type(None)))
            },
            "fastp_summary": {
                k: v for k, v in data.get("fastp_summary", {}).items()
                if isinstance(v, (str, int, float, bool, type(None)))
            },
            "watchlist_entries": len(data.get("watched_results", [])),
            "alerts": data.get("alerts", []),
        }

        metadata_path = os.path.join(output_dir, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, default=str)

        logger.info("Metadata written to %s", output_dir)
