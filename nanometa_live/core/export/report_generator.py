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
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from nanometa_live.core.export.report_charts import build_charts
from nanometa_live.core.utils.attribution import is_negative_control
from nanometa_live.core.utils.classification_loaders import load_kraken_data
from nanometa_live.core.utils.qc_loaders import get_qc_stats
from nanometa_live.core.utils.sample_detector import (
    get_available_samples,
    get_sample_file_mapping,
    resolve_analysis_directory,
)
from nanometa_live.app.tabs.dashboard_helpers import DEFAULT_LOW_READ_FLOOR
from nanometa_live.app.utils.callback_helpers import get_classification_stats

logger = logging.getLogger(__name__)

# Plotly CDN version to embed (minified JS is fetched at build time or bundled)
_PLOTLY_CDN_URL = "https://cdn.plot.ly/plotly-2.35.2.min.js"

# Result subdirectories copied into the export's raw/ folder. Covers both QC
# tools (fastp / seqkit are mutually exclusive), both validation paths, the
# taxpasta aggregates, and the Nextflow provenance under pipeline_info.
_RAW_SUBDIRS = (
    "kraken2",
    "fastp",
    "seqkit",
    "taxpasta",
    "validation",
    "on_demand_validation",
    "pipeline_info",
    # MultiQC report so the export's Pipeline Reports links resolve offline.
    "multiqc",
)

# Default ceiling on the raw payload. macOS bind-mounts and full result trees
# can be large; rather than silently copy gigabytes inside a blocking callback,
# the copy is skipped above this size with a clear log line. Override via the
# config key ``export_max_raw_bytes`` (0 disables the cap).
_DEFAULT_MAX_RAW_BYTES = 5 * 1024 ** 3  # 5 GiB

# macOS AppleDouble sidecars (and .DS_Store) written onto non-HFS+ volumes;
# excluded from the copy so they do not pollute the export or trip Nextflow if
# the raw tree is ever re-used. See the macOS bind-mount note in CLAUDE.md.
_IGNORE_SIDECARS = shutil.ignore_patterns("._*", ".DS_Store")


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

        # Raw files are copied BEFORE the Pipeline Reports links below are
        # built, and the links are derived from what actually landed under
        # raw/ rather than from a bare include_raw bool. Previously the
        # links were built first (in _collect_data) and the copy ran
        # afterward: a size-cap skip or a partial subdir failure left
        # "Pipeline Reports" hrefs pointing at a raw/ tree that was never
        # created (or missing that one subdir), with nothing in the HTML to
        # explain the 404s. See _copy_raw_files_verbose / raw_skip_reason.
        raw_files_included: List[str] = []
        raw_skip_reason: Optional[str] = None
        if include_raw:
            raw_files_included, raw_skip_reason = self._copy_raw_files_verbose(
                str(output_path)
            )

        report_data = self._collect_data(
            selected_samples,
            include_raw=include_raw,
            copied_raw_subdirs=raw_files_included,
            raw_skip_reason=raw_skip_reason,
        )
        report_data["raw_files_included"] = raw_files_included

        # Build HTML
        html_content = self._build_html_report(report_data)
        report_file = output_path / "report.html"
        report_file.write_text(html_content, encoding="utf-8")
        logger.info("Report written to %s", report_file)

        # Write metadata
        self._write_metadata(str(output_path), report_data)

        return report_file

    def _collect_data(
        self,
        samples: List[Optional[str]],
        include_raw: bool = True,
        copied_raw_subdirs: Optional[List[str]] = None,
        raw_skip_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Collect all data needed for the report."""
        # Aggregated data. get_qc_stats already abstracts fastp/seqkit (the two
        # are mutually exclusive), so a separate fastp-only summary is dropped.
        kraken_all = load_kraken_data(self.results_dir, None)
        qc_all = get_qc_stats(self.results_dir, None)

        # Classification summary from aggregated kraken
        classified, unclassified = self._get_classification_counts(kraken_all)

        # Per-sample kraken frames are loaded up front so the watchlist screen
        # can attribute each hit to the samples it came from. An aggregate-only
        # screen tells the operator a pathogen is present but not where.
        sample_frames = {
            sample: load_kraken_data(self.results_dir, sample)
            for sample in samples if sample is not None
        }

        # Watchlist screening
        watched_results = self._screen_watchlist(kraken_all, sample_frames)

        # Alerts (pathogen + QC) from the post-run watchlist screen and QC stats.
        alerts = self._collect_alerts(qc_stats=qc_all, watched_results=watched_results)

        # Pipeline reports (MultiQC, Nextflow) -- linked only for subdirs that
        # were ACTUALLY copied under raw/ (copied_raw_subdirs), not merely
        # "include_raw was requested". A report whose top-level subdir (e.g.
        # multiqc/, pipeline_info/) was skipped by the size cap or failed to
        # copy would otherwise get a link that 404s with no explanation.
        pipeline_reports = []
        if include_raw:
            from nanometa_live.core.utils.reports_loader import export_report_links
            copied_set = set(copied_raw_subdirs or [])
            pipeline_reports = [
                {"label": r["label"], "href": f"raw/{r['relpath']}"}
                for r in export_report_links(self.results_dir)
                if r["relpath"].split("/", 1)[0] in copied_set
            ]

        per_sample = self._per_sample_data(samples, sample_frames)

        return {
            # Timezone-aware local timestamp (carries the UTC offset) so an
            # archived report is unambiguous about when it was generated.
            "generated_at": datetime.now().astimezone().isoformat(),
            "results_dir": self.results_dir,
            "config": {
                k: v for k, v in self.config.items()
                if isinstance(v, (str, int, float, bool, type(None)))
            },
            "sample_count": len([s for s in samples if s is not None]),
            "samples": [s for s in samples if s is not None],
            "classified_total": classified,
            "unclassified_total": unclassified,
            # Read depth for the decision banner's INSUFFICIENT READS gate.
            # The floor is anchored to min_reads_for_validation so the report
            # and the dashboard agree on what counts as too shallow to call a
            # negative; see dashboard_helpers.select_verdict.
            "total_reads": classified + unclassified,
            "low_read_floor": self._low_read_floor(),
            "qc_summary": qc_all,
            "watched_results": watched_results,
            "alerts": alerts,
            "per_sample": per_sample,
            "pipeline_reports": pipeline_reports,
            "raw_skip_reason": raw_skip_reason,
        }

    def _low_read_floor(self) -> int:
        """Reads below which a negative result has not been earned.

        Anchored to ``min_reads_for_validation`` so the report and the
        dashboard agree on what counts as too shallow to call an absence; see
        dashboard_helpers.select_verdict.
        """
        return int(
            self.config.get("min_reads_for_validation") or DEFAULT_LOW_READ_FLOOR
        )

    def _get_classification_counts(self, df: pd.DataFrame):
        """Classified/unclassified read counts via the canonical helper.

        Delegates to ``get_classification_stats`` (root.cumul_reads +
        unclassified.cumul_reads) rather than re-deriving the counts. The old
        local fallback summed the per-rank ``reads`` column, which collapses to
        zero in the degenerate single-read case where every read is parked at
        root -- the exact pattern CLAUDE.md warns against.
        """
        classified, unclassified, _rate = get_classification_stats(df)
        return classified, unclassified

    def _per_sample_data(self, samples, sample_frames) -> Dict[str, Any]:
        """Per-sample classification counts, QC, organisms and subspecies.

        Subspecies are collected into their OWN list rather than merged into
        ``organisms``: ranking a species against its own children reads as
        double counting even though each row's percentage is correct alone.
        The list is empty on databases that do not resolve below species, and
        the template omits the section entirely in that case.
        """
        # ``_manifest.json`` PREDICTS output files from the sample list and
        # active tools; it does not verify them (bin/write_manifest.py runs
        # in its own work dir and cannot see the publishDir). A sample whose
        # QC/Kraken2 stage failed -- absorbed by conf/error_isolation.config
        # -- is listed exactly like a healthy one. The dashboard's sample
        # selector compensates by comparing available-samples against the
        # on-disk file mapping; the export had no equivalent, so a failed
        # barcode rendered as an ordinary "clean" sample (0 reads, 0
        # organisms) in the archived artifact with nothing to distinguish it
        # from a genuine negative.
        file_mapping = get_sample_file_mapping(self.results_dir)

        per_sample: Dict[str, Any] = {}
        for sample in samples:
            if sample is None:
                continue
            sample_kraken = sample_frames[sample]
            sample_qc = get_qc_stats(self.results_dir, sample)
            s_classified, s_unclassified = self._get_classification_counts(
                sample_kraken
            )
            per_sample[sample] = {
                "classified": s_classified,
                "unclassified": s_unclassified,
                "qc": sample_qc,
                "organisms": self._extract_organisms(sample_kraken)[:20],
                "subspecies": self._extract_organisms(
                    sample_kraken, ranks=("S1", "S2", "S3"),
                )[:20],
                "attempted_no_output": not file_mapping.get(sample),
            }
        return per_sample

    def _extract_organisms(
        self, df: pd.DataFrame, max_n: int = 20, ranks: tuple = ("S",),
    ) -> List[Dict[str, Any]]:
        """Extract the top organisms at the given rank(s).

        Species rank (``S``) only by default: the previous S+G filter
        double-counted, since a genus row's reads already include its species'
        reads. Abundance is read from Kraken2's own ``%`` column (the
        authoritative per-clade fraction of total reads) -- the prior
        reads/sum(reads) used the per-rank ``reads`` column as denominator,
        which over-states abundance and can push the listed values past 100%.

        ``ranks`` exists so subspecies can be listed in their OWN table.
        Mixing them into this one would rank a species against its own
        children -- F. tularensis at 99.87% beside F. t. holarctica at 64% --
        which reads as double counting even though each row's percentage is
        correct on its own.
        """
        if df.empty or "rank" not in df.columns:
            return []
        wanted = {str(r).strip() for r in ranks}
        species = df[df["rank"].astype(str).str.strip().isin(wanted)].copy()
        if species.empty:
            return []
        species = species.sort_values("reads", ascending=False).head(max_n)

        if "%" in species.columns:
            abundance = species["%"].fillna(0).astype(float)
        elif "fraction_total_reads" in species.columns:
            abundance = species["fraction_total_reads"].fillna(0).astype(float) * 100
        else:
            # Last resort: fraction of total (classified + unclassified) reads.
            classified, unclassified, _rate = get_classification_stats(df)
            total = classified + unclassified
            abundance = (species["reads"].astype(float) / total * 100) if total > 0 else 0.0
        species["_abundance"] = abundance

        results = []
        for _, row in species.iterrows():
            results.append({
                "name": str(row["name"]).strip(),
                "taxid": int(row["taxid"]),
                "reads": int(row["reads"]),
                "rank": str(row["rank"]).strip(),
                "abundance": round(float(row["_abundance"]), 2),
            })
        return results

    def _match_entry_rows(
        self,
        df: pd.DataFrame,
        match_id: Optional[int],
        entry_name: Optional[str],
    ) -> pd.DataFrame:
        """Rows of *df* belonging to one watchlist entry.

        Match by the Kraken2 database taxid (``db_taxid`` for GTDB/custom DBs,
        else the NCBI taxid), then fall back to an exact name match -- the same
        precedence the dashboard uses.
        """
        if df.empty:
            return df
        matched = (
            df[df["taxid"] == match_id] if match_id else df.iloc[0:0]
        )
        if matched.empty and entry_name:
            names_lower = df["name"].astype(str).str.strip().str.lower()
            matched = df[names_lower == entry_name.strip().lower()]
        return matched

    def _attribute_entry_to_samples(
        self,
        sample_frames: Dict[str, pd.DataFrame],
        match_id: Optional[int],
        entry_name: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Per-sample read counts for one watchlist entry, highest first.

        Each row carries ``is_negative_control`` so ``_screen_watchlist`` can
        split declared controls out of the triggering-sample list without a
        second pass over the frames -- see the "Negative controls" contract
        in CLAUDE.md, mirrored here from ``core.utils.attribution`` (the same
        resolver the dashboard's verdict banner uses).
        """
        rows: List[Dict[str, Any]] = []
        for sample, df in (sample_frames or {}).items():
            if df is None or df.empty:
                continue
            matched = self._match_entry_rows(df, match_id, entry_name)
            if matched.empty:
                continue
            read_col = "cumul_reads" if "cumul_reads" in df.columns else "reads"
            reads = int(matched[read_col].sum())
            if reads <= 0:
                continue
            classified, unclassified, _rate = get_classification_stats(df)
            total = classified + unclassified
            rows.append({
                "sample": sample,
                "reads": reads,
                "abundance": round((reads / total * 100) if total > 0 else 0, 3),
                "is_negative_control": is_negative_control(sample, self.config),
            })
        rows.sort(key=lambda r: r["reads"], reverse=True)
        return rows

    def _screen_watchlist(
        self,
        kraken_df: pd.DataFrame,
        sample_frames: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> List[Dict[str, Any]]:
        """Screen kraken results against the active watchlist.

        Emits one row per active entry (detected and not) so the report's
        Watched Organisms table and decision banner reflect the full screen.
        Each detected row carries a ``samples`` breakdown so the archived
        artifact says which barcode a hit came from, not just that the run
        contained it.

        ``get_active_entries()`` returns ``Dict[int, WatchlistEntry]`` -- the
        prior code iterated it as a list of dicts (``entry.get(...)``), which
        raised ``AttributeError`` on the first entry, was swallowed by the
        broad except, and left every exported report showing an empty,
        all-clear screen even when watchlist pathogens were present.
        """
        results: List[Dict[str, Any]] = []
        try:
            from nanometa_live.core.watchlist.watchlist_manager import get_watchlist_manager
            wm = get_watchlist_manager()
            if not wm._loaded:
                wm.load_config(self.config)
            active_entries = wm.get_active_entries()

            if kraken_df.empty or not active_entries:
                return results

            # Denominator is total reads (classified + unclassified), matching
            # the dashboard tiles -- not the per-rank reads column.
            classified, unclassified, _rate = get_classification_stats(kraken_df)
            total = classified + unclassified
            read_col = "cumul_reads" if "cumul_reads" in kraken_df.columns else "reads"

            for entry in active_entries.values():
                row = self._screen_watchlist_entry(
                    entry, kraken_df, sample_frames, read_col, total,
                )
                if row is not None:
                    results.append(row)

        except Exception as e:
            logger.exception("Could not screen watchlist: %s", e)

        return results

    def _screen_watchlist_entry(
        self,
        entry: Any,
        kraken_df: pd.DataFrame,
        sample_frames: Optional[Dict[str, pd.DataFrame]],
        read_col: str,
        total: int,
    ) -> Optional[Dict[str, Any]]:
        """Screen ONE watchlist entry against ``kraken_df``; return its report
        row, or ``None`` on failure.

        Isolated per entry on purpose: one malformed entry (missing field,
        bad type, a pandas error on its rows) must cost only that entry, not
        abort ``_screen_watchlist``'s loop. With the whole loop in one try, a
        single bad entry blanked the screen for every organism and the
        report rendered a false "NOT SCREENED" -- while a true positive
        later in iteration order was dropped.
        """
        try:
            threat = entry.threat_level
            threat_level = threat.value if hasattr(threat, "value") else str(threat)

            match_id = getattr(entry, "db_taxid", None) or entry.taxid
            matched = self._match_entry_rows(kraken_df, match_id, entry.name)

            reads = int(matched[read_col].sum()) if not matched.empty else 0
            abundance = (reads / total * 100) if total > 0 else 0
            per_sample = (
                self._attribute_entry_to_samples(
                    sample_frames, match_id, entry.name
                ) if reads > 0 else []
            )

            # Negative controls are reported alongside a detection, never
            # acted on: they are split out of the triggering list here, but
            # a control-carried-only hit still shows as "detected" -- a
            # contaminated control never makes a real aggregate positive
            # disappear. Mirrors the dashboard's build_pathogen_attribution.
            triggering_samples = [
                s for s in per_sample if not s.get("is_negative_control")
            ]
            negative_control_rows = [
                s for s in per_sample if s.get("is_negative_control")
            ]
            nc_reads = sum(s["reads"] for s in negative_control_rows)
            positive_reads = sum(s["reads"] for s in triggering_samples)
            nc_fraction = (
                (nc_reads / positive_reads * 100)
                if (negative_control_rows and positive_reads)
                else None
            )

            return {
                "name": entry.name,
                "taxid": entry.taxid,
                "threat_level": threat_level,
                "reads": reads,
                "abundance": round(abundance, 3),
                "detected": reads > 0,
                "samples": per_sample,
                "triggering_samples": triggering_samples,
                "negative_control_rows": negative_control_rows,
                "negative_control_fraction": nc_fraction,
                "control_only": bool(
                    negative_control_rows and not triggering_samples
                ),
            }
        except Exception:
            logger.exception(
                "Could not screen watchlist entry %r; the remaining "
                "entries are still screened",
                getattr(entry, "name", entry),
            )
            return None

    def _collect_alerts(self, qc_stats=None, watched_results=None) -> List[Dict[str, Any]]:
        """Generate the report's alerts from the post-run state.

        Previously called a non-existent ``get_alert_engine().get_active_alerts()``
        -- the AttributeError was swallowed, so every exported report had an empty
        Alerts section. Use the real ``generate_alerts(status, samples, ...)`` API
        with the data the report already has: QC stats and the watchlist screen
        (so pathogen + QC alerts surface). An export has no live backend status or
        per-sample stream, so those are passed empty. Degrades to [] on any
        problem -- alerts are a secondary section.
        """
        try:
            from nanometa_live.core.utils.alert_engine import get_alert_engine
            engine = get_alert_engine()
            watched_results = watched_results or []
            detected = [
                {"name": w.get("name"), "taxid": w.get("taxid"), "reads": w.get("reads", 0)}
                for w in watched_results if w.get("detected")
            ]
            watched_species = [
                {"name": w.get("name"), "taxid": w.get("taxid"),
                 "threat_level": w.get("threat_level")}
                for w in watched_results
            ]
            return engine.generate_alerts(
                {}, [], qc_stats=qc_stats,
                detected_organisms=detected, watched_species=watched_species,
            )
        except Exception as e:  # noqa: BLE001 -- alerts are best-effort
            logger.debug("Could not generate alerts for report: %s", e, exc_info=True)
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
        except (ImportError, AttributeError, FileNotFoundError, PermissionError, OSError, UnicodeDecodeError):
            pass

        # No local bundle. In offline mode a CDN reference is useless (and a
        # dangling external request when the report is opened), so the caller
        # must not emit one -- see _build_html_report. Surface the degradation
        # clearly rather than silently shipping a chart-less "self-contained"
        # report.
        if self.config.get("offline_mode"):
            logger.error(
                "No local plotly.js bundle found and offline_mode is set: "
                "the exported report's charts will not render. Install plotly "
                "with its bundled package_data, or export with network access."
            )
        else:
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

        # Get plotly.js for embedding. Only reference the CDN when a local
        # bundle is unavailable AND we are not offline -- an offline report
        # that points at a CDN just fails to load with a dangling request.
        plotly_js = self._get_plotly_js()
        use_cdn = (not plotly_js) and not self.config.get("offline_mode")

        # Serialize charts dict to JSON for embedding in template script.
        # The template embeds this with ``| safe`` inside a <script> element,
        # and json.dumps does not escape "/": a string in the chart payload
        # containing the literal "</script>" (a sample or organism name --
        # watchlist YAML upload is an external-input path) terminates the
        # script element at the HTML-parser level and any following markup
        # executes in the reader's browser. Escaping "</" as "<\/" is a
        # JSON-transparent HTML-breakout guard: identical data, no parseable
        # close tag.
        charts_json = json.dumps(charts).replace("</", "<\\/")

        return template.render(
            data=data,
            charts=charts_json,
            plotly_js_inline=plotly_js,
            plotly_cdn_url=_PLOTLY_CDN_URL if use_cdn else "",
            generated_at=data["generated_at"],
            app_name="Nanometa Live",
        )

    def _build_charts(self, data: Dict[str, Any]) -> Dict[str, str]:
        """Build all Plotly charts and serialize to JSON.

        Delegates to ``report_charts.build_charts`` -- a pure function with
        no instance state -- split out during the 2026-08-16 code-size
        remediation. Kept as an instance method (rather than calling the
        module function directly from ``_build_html_report``) so existing
        callers can still monkeypatch it per-instance, as
        ``TestChartJsonCannotBreakOutOfScript`` does.
        """
        return build_charts(data)

    @staticmethod
    def _dir_size(path: str) -> int:
        """Total size in bytes of files under ``path`` (sidecars excluded)."""
        total = 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                if f.startswith("._") or f == ".DS_Store":
                    continue
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    def _raw_copy_plan(self) -> Tuple[List[str], Optional[str]]:
        """``_RAW_SUBDIRS`` present on disk, and a reason when the whole copy
        must be skipped for exceeding the size cap.

        Split out of ``_copy_raw_files`` so ``generate()`` can learn about a
        cap-triggered skip (for the HTML note and metadata.json) without
        duplicating the size-cap arithmetic.
        """
        present = [
            s for s in _RAW_SUBDIRS
            if os.path.isdir(os.path.join(self.results_dir, s))
        ]

        cap = self.config.get("export_max_raw_bytes", _DEFAULT_MAX_RAW_BYTES)
        if cap and present:
            total = sum(self._dir_size(os.path.join(self.results_dir, s)) for s in present)
            if total > cap:
                reason = (
                    f"Raw files omitted: the payload ({total / 1024 ** 3:.1f} GiB) "
                    f"exceeds the {cap / 1024 ** 3:.1f} GiB export cap "
                    "(set export_max_raw_bytes to override). The HTML report "
                    "and metadata below are otherwise complete; only the raw/ "
                    "directory and its Pipeline Reports links are affected."
                )
                logger.warning(reason)
                return [], reason
        return present, None

    def _copy_raw_files_verbose(self, output_dir: str) -> Tuple[List[str], Optional[str]]:
        """Copy raw result subdirs into ``output_dir/raw/``.

        Returns ``(copied, skip_reason)``. ``skip_reason`` is set when the
        whole copy was skipped by the size cap, or when one or more (but not
        all) subdirs failed to copy -- the caller surfaces this in the HTML
        and metadata.json instead of leaving a dangling ``raw/`` link with no
        explanation for the 404. AppleDouble/.DS_Store sidecars are excluded.
        """
        present, skip_reason = self._raw_copy_plan()
        if skip_reason:
            return [], skip_reason

        raw_dir = os.path.join(output_dir, "raw")
        copied: List[str] = []
        failed: List[str] = []
        for subdir in present:
            src = os.path.join(self.results_dir, subdir)
            dst = os.path.join(raw_dir, subdir)
            try:
                shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_IGNORE_SIDECARS)
                copied.append(subdir)
                logger.info("Copied %s to %s", src, dst)
            except (FileNotFoundError, PermissionError, OSError, shutil.Error) as e:
                logger.exception("Could not copy %s: %s", src, e)
                failed.append(subdir)

        partial_reason = None
        if failed:
            partial_reason = (
                "Raw files partially omitted: " + ", ".join(failed) +
                " could not be copied (see application log for details). "
                "Other raw subdirs and their Pipeline Reports links are "
                "unaffected."
            )
            logger.warning(partial_reason)
        return copied, partial_reason

    def _copy_raw_files(self, output_dir: str) -> List[str]:
        """Copy raw result subdirs into ``output_dir/raw/``.

        Returns the list of subdirs actually copied. Thin wrapper over
        ``_copy_raw_files_verbose`` for callers (and existing tests) that
        only need the copied list, not the skip reason.
        """
        return self._copy_raw_files_verbose(output_dir)[0]

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
            "watchlist_entries": len(data.get("watched_results", [])),
            "alerts": data.get("alerts", []),
            "raw_files_included": data.get("raw_files_included", []),
            # Explicit record of a size-cap or partial-copy skip so a reader
            # of this sidecar (not just the HTML) can tell "raw/ is missing
            # on purpose, here's why" apart from "the export is broken".
            "raw_skip_reason": data.get("raw_skip_reason"),
        }

        metadata_path = os.path.join(output_dir, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, default=str)

        logger.info("Metadata written to %s", output_dir)
