"""
Alert Engine for Nanometa Live v2.0.

This module provides intelligent alert generation, prioritization, and tracking
for non-technical operators (first responders, laboratory personnel).
"""

from typing import List, Dict, Optional
from datetime import datetime, timedelta
from enum import Enum
import logging
import threading

from nanometa_live.core.utils.pathogen_database import (
    check_for_dangerous_pathogens,
)

logger = logging.getLogger(__name__)


# Maximum number of alerts to keep in history to prevent memory leaks
MAX_HISTORY_SIZE = 100


class AlertSeverity(Enum):
    """Alert severity levels with priority ordering."""
    CRITICAL = 1  # Immediate action required
    WARNING = 2   # Attention needed
    INFO = 3      # Informational only
    SUCCESS = 4   # Positive update


class AlertCategory(Enum):
    """Alert categories for organization."""
    SYSTEM = "system"
    QUALITY = "quality"
    DATA = "data"
    ANALYSIS = "analysis"
    COMPLETION = "completion"
    PATHOGEN = "pathogen"  # Dangerous pathogen detection alerts


class Alert:
    """Structured alert object."""

    def __init__(
        self,
        severity: AlertSeverity,
        category: AlertCategory,
        message: str,
        recommendation: Optional[str] = None,
        technical_details: Optional[str] = None,
        timestamp: Optional[datetime] = None
    ):
        self.severity = severity
        self.category = category
        self.message = message
        self.recommendation = recommendation
        self.technical_details = technical_details
        self.timestamp = timestamp or datetime.now()
        self.id = f"{self.category.value}_{self.timestamp.strftime('%Y%m%d%H%M%S')}"

    def to_dict(self) -> Dict:
        """Convert alert to dictionary for Dash components."""
        return {
            "id": self.id,
            "severity": self.severity.name.lower(),
            "category": self.category.value,
            "message": self.message,
            "recommendation": self.recommendation,
            "technical_details": self.technical_details,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "priority": self.severity.value
        }


class AlertEngine:
    """
    Central alert generation and tracking engine.

    Generates operator-friendly alerts based on system state and analysis metrics.
    """

    def __init__(self, alert_history_hours: int = 24):
        """
        Initialize alert engine.

        Args:
            alert_history_hours: How long to keep alerts in history (default: 24 hours)
        """
        self.alert_history: List[Alert] = []
        self.alert_history_hours = alert_history_hours
        self.alert_rules = self._initialize_alert_rules()

    def _initialize_alert_rules(self) -> Dict:
        """
        Define alert rules and thresholds.

        Thresholds are set for nanopore sequencing data where:
        - Q10-15 is typical mean quality
        - Q20% (% bases at Q20+) of 50-70% is normal
        - Q20% > 60% is good quality for nanopore

        Returns:
            Dictionary of rule configurations
        """
        return {
            "quality": {
                "critical_pass_rate": 40,   # % - Below this = critical (very poor)
                "warning_pass_rate": 55,    # % - Below this = warning (needs attention)
                "critical_classified": 20,  # % - Below this = critical
                "warning_classified": 40    # % - Below this = warning
            },
            "data": {
                "min_reads_per_sample": 100,
                "stalled_time_minutes": 15,  # No new data for this long = alert
                "low_yield_threshold": 1000  # Total reads below this = concern
            },
            "system": {
                "max_error_count": 5,
                "max_pending_files": 50
            }
        }

    def generate_alerts(
        self,
        status: Dict,
        samples: List[Dict],
        qc_stats: Optional[Dict] = None,
        detected_organisms: Optional[List[Dict]] = None,
        watched_species: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Generate alerts based on current system state.

        Args:
            status: Backend status dictionary
            samples: List of sample information dictionaries
            qc_stats: Optional QC statistics
            detected_organisms: Optional list of detected organisms from Kraken2
            watched_species: Optional list of user-configured species to watch

        Returns:
            List of alert dictionaries sorted by priority
        """
        alerts = []

        # PRIORITY 1: Pathogen alerts (most critical - check first)
        if detected_organisms:
            alerts.extend(self._check_dangerous_pathogens(
                detected_organisms,
                watched_species
            ))

        # System status alerts
        alerts.extend(self._check_system_status(status))

        # Sample quality alerts
        alerts.extend(self._check_sample_quality(samples))

        # QC statistics alerts
        if qc_stats:
            alerts.extend(self._check_qc_stats(qc_stats))

        # Data processing alerts
        alerts.extend(self._check_data_processing(status, samples))

        # Update alert history
        self._update_alert_history(alerts)

        # Remove old alerts and duplicates
        alerts = self._deduplicate_alerts(alerts)

        # Sort by priority (severity)
        alerts_sorted = sorted(alerts, key=lambda x: x.severity.value)

        return [alert.to_dict() for alert in alerts_sorted]

    def _check_system_status(self, status: Dict) -> List[Alert]:
        """Check for system-level alerts."""
        alerts = []

        # Only show "not running" alert if we have processed data available
        # This avoids showing the alert immediately when dashboard starts
        # or right after analysis completes
        if not status.get("running", False):
            # Check if we have samples processed - if so, analysis is complete, not idle
            samples_processed = status.get("samples_processed", 0)
            if samples_processed == 0:
                # No data yet - show info alert but only if explicitly requested
                # Skip this alert to reduce noise on dashboard startup
                pass

        error_count = status.get("error_count", 0)
        if error_count >= self.alert_rules["system"]["max_error_count"]:
            alerts.append(Alert(
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.SYSTEM,
                message=f"Multiple errors detected ({error_count} errors)",
                recommendation="Check logs and contact bioinformatics support",
                technical_details=f"Error count: {error_count}"
            ))
        elif error_count > 0:
            alerts.append(Alert(
                severity=AlertSeverity.WARNING,
                category=AlertCategory.SYSTEM,
                message=f"{error_count} error(s) detected during processing",
                recommendation="Review error details and continue monitoring"
            ))

        return alerts

    def _check_sample_quality(self, samples: List[Dict]) -> List[Alert]:
        """Check for sample quality issues."""
        alerts = []

        if not samples or len(samples) == 0:
            alerts.append(Alert(
                severity=AlertSeverity.INFO,
                category=AlertCategory.DATA,
                message="No samples detected yet",
                recommendation="Ensure sequencing data is being generated"
            ))
            return alerts

        # Check each sample for quality issues
        low_quality_samples = []
        low_yield_samples = []

        for sample in samples:
            sample_name = sample.get("name", "Unknown")
            pass_rate = sample.get("pass_rate", 100)
            reads = sample.get("reads", 0)

            # Pass rate check
            if pass_rate < self.alert_rules["quality"]["critical_pass_rate"]:
                low_quality_samples.append((sample_name, pass_rate))

            # Read yield check
            if reads < self.alert_rules["data"]["min_reads_per_sample"]:
                low_yield_samples.append((sample_name, reads))

        if low_quality_samples:
            sample_list = ", ".join([f"{name} ({rate:.1f}%)" for name, rate in low_quality_samples[:3]])
            alerts.append(Alert(
                severity=AlertSeverity.CRITICAL,
                category=AlertCategory.QUALITY,
                message=f"Low quality detected in {len(low_quality_samples)} sample(s): {sample_list}",
                recommendation="Check sequencing conditions and sample preparation",
                technical_details=f"Pass rate below {self.alert_rules['quality']['critical_pass_rate']}%"
            ))

        if low_yield_samples:
            sample_list = ", ".join([f"{name} ({reads} reads)" for name, reads in low_yield_samples[:3]])
            alerts.append(Alert(
                severity=AlertSeverity.INFO,
                category=AlertCategory.DATA,
                message=f"Low yield in {len(low_yield_samples)} sample(s): {sample_list}",
                recommendation="Continue monitoring - yield may increase over time"
            ))

        return alerts

    def _check_dangerous_pathogens(
        self,
        detected_organisms: List[Dict],
        watched_species: Optional[List[Dict]] = None
    ) -> List[Alert]:
        """
        Check for dangerous pathogens in classification results.

        Uses the pathogen database to identify CDC Category A/B/C agents,
        WHO priority pathogens, and user-configured species of interest.

        Args:
            detected_organisms: List of detected organisms with 'taxid', 'name', 'reads'
            watched_species: Optional user-configured watchlist

        Returns:
            List of Alert objects for detected pathogens
        """
        alerts = []

        try:
            # Use the pathogen database to check for dangerous organisms
            dangerous_detections = check_for_dangerous_pathogens(
                detected_organisms,
                watched_species
            )

            for detection in dangerous_detections:
                threat_level = detection.get("threat_level", "moderate")
                pathogen_name = detection.get("name", "Unknown organism")
                common_name = detection.get("common_name", "")
                reads = detection.get("reads", 0)
                abundance = detection.get("abundance", 0.0)
                action = detection.get("action_required", "Follow biosafety protocols")
                category_info = detection.get("category", "")

                # Determine alert severity based on threat level
                if threat_level == "critical":
                    severity = AlertSeverity.CRITICAL
                    display_name = f"{pathogen_name}"
                    if common_name:
                        display_name = f"{pathogen_name} ({common_name})"

                    alerts.append(Alert(
                        severity=severity,
                        category=AlertCategory.PATHOGEN,
                        message=f"CRITICAL PATHOGEN: {display_name} detected ({reads:,} reads)",
                        recommendation=action,
                        technical_details=(
                            f"TaxID: {detection.get('taxid')}, "
                            f"Abundance: {abundance:.2f}%, "
                            f"Category: {category_info}"
                        )
                    ))

                elif threat_level in ["high", "high_risk"]:
                    severity = AlertSeverity.WARNING
                    display_name = pathogen_name
                    if common_name:
                        display_name = f"{pathogen_name} ({common_name})"

                    alerts.append(Alert(
                        severity=severity,
                        category=AlertCategory.PATHOGEN,
                        message=f"HIGH RISK: {display_name} detected ({reads:,} reads)",
                        recommendation=action,
                        technical_details=(
                            f"TaxID: {detection.get('taxid')}, "
                            f"Abundance: {abundance:.2f}%"
                        )
                    ))

                elif threat_level == "moderate":
                    alerts.append(Alert(
                        severity=AlertSeverity.WARNING,
                        category=AlertCategory.PATHOGEN,
                        message=f"Watched species: {pathogen_name} detected ({reads:,} reads)",
                        recommendation="Monitor and document according to protocols",
                        technical_details=f"TaxID: {detection.get('taxid')}, Abundance: {abundance:.2f}%"
                    ))

                else:  # low or info
                    alerts.append(Alert(
                        severity=AlertSeverity.INFO,
                        category=AlertCategory.PATHOGEN,
                        message=f"Species of interest: {pathogen_name} ({reads:,} reads)",
                        recommendation="No action required - documented for reference"
                    ))

            # Log summary if pathogens detected
            if dangerous_detections:
                critical_count = sum(
                    1 for d in dangerous_detections
                    if d.get("threat_level") == "critical"
                )
                high_count = sum(
                    1 for d in dangerous_detections
                    if d.get("threat_level") in ["high", "high_risk"]
                )

                if critical_count > 0:
                    logger.warning(
                        f"PATHOGEN ALERT: {critical_count} critical pathogen(s) detected!"
                    )
                elif high_count > 0:
                    logger.warning(
                        f"PATHOGEN ALERT: {high_count} high-risk pathogen(s) detected"
                    )

        except Exception as e:
            logger.error(f"Error checking for dangerous pathogens: {e}")
            # Don't fail silently - add an error alert
            alerts.append(Alert(
                severity=AlertSeverity.WARNING,
                category=AlertCategory.SYSTEM,
                message="Unable to check pathogen database",
                recommendation="Contact bioinformatics support",
                technical_details=str(e)
            ))

        return alerts

    def _check_qc_stats(self, qc_stats: Dict) -> List[Alert]:
        """Check QC statistics for issues."""
        alerts = []

        total_reads = qc_stats.get("total_reads", 0)
        pass_rate = qc_stats.get("pass_rate", 100)
        classified_rate = qc_stats.get("classified_rate", 0)

        # Overall pass rate
        if pass_rate < self.alert_rules["quality"]["warning_pass_rate"]:
            severity = (AlertSeverity.CRITICAL if pass_rate < self.alert_rules["quality"]["critical_pass_rate"]
                       else AlertSeverity.WARNING)
            alerts.append(Alert(
                severity=severity,
                category=AlertCategory.QUALITY,
                message=f"Overall quality is {pass_rate:.1f}% (target: >{self.alert_rules['quality']['warning_pass_rate']}%)",
                recommendation="Review sequencing conditions and flowcell health",
                technical_details=f"Pass rate: {pass_rate:.1f}%, Total reads: {total_reads}"
            ))

        # Classification rate
        if classified_rate < self.alert_rules["quality"]["warning_classified"]:
            severity = (AlertSeverity.CRITICAL if classified_rate < self.alert_rules["quality"]["critical_classified"]
                       else AlertSeverity.WARNING)
            alerts.append(Alert(
                severity=severity,
                category=AlertCategory.ANALYSIS,
                message=f"Low organism identification: {classified_rate:.1f}% of sequences classified",
                recommendation="Verify database selection matches expected sample content",
                technical_details=f"Classified: {classified_rate:.1f}%"
            ))

        return alerts

    def _check_data_processing(self, status: Dict, samples: List[Dict]) -> List[Alert]:
        """Check data processing status."""
        alerts = []

        pending_files = status.get("pending_files", 0)
        processed_files = status.get("processed_files", 0)

        if pending_files > self.alert_rules["system"]["max_pending_files"]:
            alerts.append(Alert(
                severity=AlertSeverity.INFO,
                category=AlertCategory.SYSTEM,
                message=f"High number of pending files: {pending_files} files waiting",
                recommendation="System is processing - this is normal during high data generation",
                technical_details=f"Processed: {processed_files}, Pending: {pending_files}"
            ))

        # Check if analysis completed successfully
        if status.get("completed", False) and not status.get("running", False):
            total_reads = sum(s.get("reads", 0) for s in samples)
            alerts.append(Alert(
                severity=AlertSeverity.SUCCESS,
                category=AlertCategory.COMPLETION,
                message=f"Analysis completed: {total_reads:,} DNA sequences from {len(samples)} sample(s)",
                recommendation="Review results and generate report"
            ))

        return alerts

    def _update_alert_history(self, new_alerts: List[Alert]):
        """Add new alerts to history and remove old ones."""
        # Add new alerts
        self.alert_history.extend(new_alerts)

        # Remove alerts older than retention period
        cutoff_time = datetime.now() - timedelta(hours=self.alert_history_hours)
        self.alert_history = [
            alert for alert in self.alert_history
            if alert.timestamp > cutoff_time
        ]

        # Enforce maximum history size to prevent memory leaks
        if len(self.alert_history) > MAX_HISTORY_SIZE:
            # Keep only the most recent alerts
            self.alert_history = self.alert_history[-MAX_HISTORY_SIZE:]

    def _deduplicate_alerts(self, alerts: List[Alert]) -> List[Alert]:
        """
        Remove duplicate alerts based on message content.

        Args:
            alerts: List of Alert objects

        Returns:
            Deduplicated list of alerts
        """
        seen_messages = set()
        unique_alerts = []

        for alert in alerts:
            if alert.message not in seen_messages:
                seen_messages.add(alert.message)
                unique_alerts.append(alert)

        return unique_alerts

    def get_alert_summary(self) -> Dict[str, int]:
        """
        Get summary counts of current alerts by severity.

        Returns:
            Dictionary with counts by severity level
        """
        summary = {
            "critical": 0,
            "warning": 0,
            "info": 0,
            "success": 0
        }

        for alert in self.alert_history:
            severity_key = alert.severity.name.lower()
            summary[severity_key] = summary.get(severity_key, 0) + 1

        return summary

    def clear_alerts(self, category: Optional[AlertCategory] = None):
        """
        Clear alerts, optionally filtered by category.

        Args:
            category: If provided, only clear alerts from this category
        """
        if category:
            self.alert_history = [
                alert for alert in self.alert_history
                if alert.category != category
            ]
        else:
            self.alert_history.clear()


# Global alert engine instance -- protected by lock against concurrent initialization.
_alert_engine = None
_alert_engine_lock = threading.Lock()


def get_alert_engine() -> AlertEngine:
    """
    Get or create the global alert engine instance (thread-safe).

    Returns:
        AlertEngine instance
    """
    global _alert_engine
    if _alert_engine is not None:
        return _alert_engine
    with _alert_engine_lock:
        if _alert_engine is None:
            _alert_engine = AlertEngine()
        return _alert_engine
