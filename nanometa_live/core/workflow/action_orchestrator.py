"""
Action Orchestration System for Nanometa Live v2.0.

Provides intelligent workflow guidance and recommended actions for operators
in high-pressure situations. Designed for first responders and laboratory
personnel who need clear, actionable guidance.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ActionPriority(Enum):
    """Action priority levels for operator guidance."""
    IMMEDIATE = 1      # Drop everything, act now
    URGENT = 2         # Act within minutes
    IMPORTANT = 3      # Act within hours
    ROUTINE = 4        # Can wait until convenient


class ActionCategory(Enum):
    """Categories of actions for organization."""
    ALERT_RESPONSE = "alert_response"      # Respond to critical alerts
    DATA_REVIEW = "data_review"            # Review analysis results
    QUALITY_CHECK = "quality_check"        # Quality assurance tasks
    REPORTING = "reporting"                # Generate reports
    COMMUNICATION = "communication"        # Notify stakeholders
    TROUBLESHOOTING = "troubleshooting"    # Fix problems
    CONFIGURATION = "configuration"        # Adjust settings


@dataclass
class Action:
    """
    Structured action for operator guidance.
    """
    id: str
    priority: ActionPriority
    category: ActionCategory
    title: str
    description: str
    button_text: str
    button_id: str

    # Context
    reason: str                                    # Why this action is needed
    consequence: Optional[str] = None              # What happens if not done
    estimated_time: Optional[str] = None           # How long it takes

    # Guidance
    prerequisites: List[str] = field(default_factory=list)  # What's needed first
    steps: List[str] = field(default_factory=list)          # How to do it

    # Status
    completed: bool = False
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Dash components."""
        return {
            "id": self.id,
            "priority": self.priority.name.lower(),
            "category": self.category.value,
            "title": self.title,
            "description": self.description,
            "button_text": self.button_text,
            "button_id": self.button_id,
            "reason": self.reason,
            "consequence": self.consequence,
            "estimated_time": self.estimated_time,
            "prerequisites": self.prerequisites,
            "steps": self.steps,
            "completed": self.completed,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }


class ActionOrchestrator:
    """
    Intelligent action recommendation system.

    Analyzes current system state and provides prioritized,
    actionable guidance for operators.
    """

    def __init__(self):
        """Initialize action orchestrator."""
        self.active_actions: List[Action] = []
        self.completed_actions: List[Action] = []
        self.action_history: List[Action] = []

    def generate_recommended_actions(
        self,
        system_status: Dict[str, Any],
        alerts: List[Dict[str, Any]],
        samples: List[Dict[str, Any]],
        config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Generate prioritized list of recommended actions based on system state.

        Args:
            system_status: Current system status
            alerts: Active alerts
            samples: Sample information
            config: Application configuration

        Returns:
            List of action dictionaries sorted by priority
        """
        actions = []

        # Critical alerts require immediate action
        actions.extend(self._generate_alert_response_actions(alerts))

        # Quality issues need attention
        actions.extend(self._generate_quality_check_actions(samples))

        # Completion triggers reporting
        if system_status.get("completed", False):
            actions.extend(self._generate_reporting_actions(system_status, samples))

        # Running analysis suggests monitoring
        if system_status.get("running", False):
            actions.extend(self._generate_monitoring_actions(system_status))

        # Configuration validation
        actions.extend(self._generate_configuration_actions(config))

        # Sort by priority
        actions_sorted = sorted(actions, key=lambda x: x.priority.value)

        # Update active actions
        self.active_actions = actions_sorted

        return [action.to_dict() for action in actions_sorted]

    def _generate_alert_response_actions(
        self,
        alerts: List[Dict[str, Any]]
    ) -> List[Action]:
        """Generate actions in response to active alerts."""
        actions = []

        # Count alerts by severity
        critical_count = sum(1 for a in alerts if a.get("severity") == "critical")
        warning_count = sum(1 for a in alerts if a.get("severity") == "warning")

        if critical_count > 0:
            # Critical alerts require immediate investigation
            actions.append(Action(
                id="investigate_critical_alerts",
                priority=ActionPriority.IMMEDIATE,
                category=ActionCategory.ALERT_RESPONSE,
                title="Investigate Critical Issues",
                description=f"{critical_count} critical issue{'s' if critical_count > 1 else ''} detected requiring immediate attention",
                button_text="View Critical Alerts",
                button_id="view-critical-alerts-btn",
                reason="Critical issues can indicate sequencing problems or serious quality concerns",
                consequence="Delayed response may result in wasted resources or unreliable results",
                estimated_time="5-10 minutes",
                prerequisites=[],
                steps=[
                    "Review each critical alert in the Alerts panel",
                    "Follow recommended actions for each alert",
                    "Check sample quality in QC tab for affected samples",
                    "Contact bioinformatics support if needed"
                ]
            ))

        if warning_count > 2:
            # Multiple warnings suggest system review needed
            actions.append(Action(
                id="review_system_warnings",
                priority=ActionPriority.URGENT,
                category=ActionCategory.ALERT_RESPONSE,
                title="Review System Warnings",
                description=f"{warning_count} warnings detected - system review recommended",
                button_text="Review Warnings",
                button_id="review-warnings-btn",
                reason="Multiple warnings may indicate degrading quality or configuration issues",
                estimated_time="10-15 minutes",
                steps=[
                    "Review warnings in Alerts panel",
                    "Check if warnings are related (same issue affecting multiple samples)",
                    "Verify sequencing conditions (temperature, flow cell status)",
                    "Consider adjusting parameters if quality is consistently low"
                ]
            ))

        # Species of interest detection
        species_alerts = [a for a in alerts if "species of interest" in a.get("message", "").lower()]
        if species_alerts:
            actions.append(Action(
                id="review_species_detection",
                priority=ActionPriority.IMMEDIATE,
                category=ActionCategory.ALERT_RESPONSE,
                title="Species of Interest Detected",
                description=f"{len(species_alerts)} target organism{'s' if len(species_alerts) > 1 else ''} identified",
                button_text="Review Detections",
                button_id="review-species-btn",
                reason="Target organisms detected require verification and reporting",
                consequence="Delayed reporting may impact response time for critical pathogens",
                estimated_time="15-20 minutes",
                prerequisites=["Verify species identification in Classification tab"],
                steps=[
                    "Navigate to Classification tab",
                    "Verify species identification confidence",
                    "Check read counts for detected species",
                    "Generate detailed report for authorities",
                    "Follow reporting protocol for detected organisms"
                ]
            ))

        return actions

    def _generate_quality_check_actions(
        self,
        samples: List[Dict[str, Any]]
    ) -> List[Action]:
        """Generate actions for quality assurance."""
        actions = []

        # Check for low quality samples
        poor_quality = [s for s in samples if s.get("quality") == "Poor" or s.get("status") == "issue"]

        if poor_quality:
            actions.append(Action(
                id="investigate_poor_quality",
                priority=ActionPriority.URGENT,
                category=ActionCategory.QUALITY_CHECK,
                title="Investigate Poor Quality Samples",
                description=f"{len(poor_quality)} sample{'s' if len(poor_quality) > 1 else ''} with quality issues",
                button_text="View QC Report",
                button_id="view-qc-report-btn",
                reason="Poor quality data may produce unreliable results",
                consequence="Continued processing may waste resources on unusable data",
                estimated_time="10-15 minutes",
                steps=[
                    "Navigate to QC tab",
                    "Review quality metrics for affected samples",
                    "Check filtering statistics (removal reasons)",
                    "Verify sequencing conditions are optimal",
                    "Consider re-running affected samples if critical"
                ]
            ))

        # Check for low yield samples
        low_yield = [s for s in samples if isinstance(s.get("reads"), str) and
                    int(s.get("reads", "0").replace(",", "")) < 1000]

        if low_yield and not poor_quality:  # Don't double-alert
            actions.append(Action(
                id="review_low_yield",
                priority=ActionPriority.IMPORTANT,
                category=ActionCategory.QUALITY_CHECK,
                title="Low Yield Samples Detected",
                description=f"{len(low_yield)} sample{'s' if len(low_yield) > 1 else ''} with low read counts",
                button_text="Check Yield",
                button_id="check-yield-btn",
                reason="Low yield may indicate loading issues or early termination",
                estimated_time="5 minutes",
                steps=[
                    "Verify sequencing run is complete",
                    "Check if run was stopped early",
                    "Review sample loading concentration",
                    "Consider extending run time if still active"
                ]
            ))

        return actions

    def _generate_reporting_actions(
        self,
        system_status: Dict[str, Any],
        samples: List[Dict[str, Any]]
    ) -> List[Action]:
        """Generate reporting and documentation actions."""
        actions = []

        # Analysis complete - generate report
        actions.append(Action(
            id="generate_final_report",
            priority=ActionPriority.URGENT,
            category=ActionCategory.REPORTING,
            title="Generate Final Report",
            description="Analysis complete - ready to generate comprehensive report",
            button_text="Generate Report",
            button_id="generate-report-btn",
            reason="Completed analysis should be documented for records and decision-making",
            estimated_time="5 minutes",
            prerequisites=["Verify all samples processed successfully"],
            steps=[
                "Review final results in all tabs",
                "Verify no critical issues remain",
                "Click 'Generate Report' button",
                "Select report format (PDF or Excel)",
                "Add any relevant notes or observations",
                "Save report to designated location"
            ]
        ))

        # If organisms detected, suggest detailed species report
        total_organisms = system_status.get("organisms_detected", 0)
        if total_organisms > 0:
            actions.append(Action(
                id="export_species_list",
                priority=ActionPriority.IMPORTANT,
                category=ActionCategory.REPORTING,
                title="Export Organism List",
                description=f"{total_organisms} organism{'s' if total_organisms != 1 else ''} identified - export detailed list",
                button_text="Export List",
                button_id="export-species-btn",
                reason="Detailed organism list useful for further analysis and reporting",
                estimated_time="2 minutes",
                steps=[
                    "Navigate to Classification tab",
                    "Review organism identifications",
                    "Click 'Export' button",
                    "Select export format",
                    "Save to designated location"
                ]
            ))

        return actions

    def _generate_monitoring_actions(
        self,
        system_status: Dict[str, Any]
    ) -> List[Action]:
        """Generate monitoring and observation actions."""
        actions = []

        # Ongoing analysis
        processed = system_status.get("samples_processed", 0)
        total = system_status.get("total_samples", 0)

        if processed < total:
            actions.append(Action(
                id="monitor_progress",
                priority=ActionPriority.ROUTINE,
                category=ActionCategory.DATA_REVIEW,
                title="Monitor Analysis Progress",
                description=f"Processing in progress: {processed} of {total} samples complete",
                button_text="View Progress",
                button_id="view-progress-btn",
                reason="Regular monitoring helps catch issues early",
                estimated_time="Ongoing",
                steps=[
                    "Check Dashboard status every 10-15 minutes",
                    "Watch for new alerts",
                    "Monitor quality metrics for trends",
                    "Verify expected progress rate"
                ]
            ))

        return actions

    def _generate_configuration_actions(
        self,
        config: Dict[str, Any]
    ) -> List[Action]:
        """Generate configuration validation actions."""
        actions = []

        # Check if species of interest configured
        species_of_interest = config.get("species_of_interest", [])
        if not species_of_interest:
            actions.append(Action(
                id="configure_species_monitoring",
                priority=ActionPriority.ROUTINE,
                category=ActionCategory.CONFIGURATION,
                title="Configure Species Monitoring",
                description="No target species configured for automatic detection",
                button_text="Configure Species",
                button_id="configure-species-btn",
                reason="Configuring target species enables automatic detection alerts",
                estimated_time="5 minutes",
                steps=[
                    "Navigate to Configuration tab",
                    "Click 'Species of Interest' section",
                    "Add target species by name or taxonomy ID",
                    "Save configuration",
                    "Alerts will trigger when these species are detected"
                ]
            ))

        return actions

    def mark_action_completed(self, action_id: str):
        """
        Mark an action as completed.

        Args:
            action_id: ID of the action to mark complete
        """
        for action in self.active_actions:
            if action.id == action_id:
                action.completed = True
                self.completed_actions.append(action)
                self.active_actions.remove(action)
                logger.info(f"Action completed: {action.title}")
                break

    def get_next_action(self) -> Optional[Dict[str, Any]]:
        """
        Get the highest priority incomplete action.

        Returns:
            Next action to take, or None if no actions pending
        """
        incomplete = [a for a in self.active_actions if not a.completed]
        if incomplete:
            return incomplete[0].to_dict()
        return None

    def get_action_summary(self) -> Dict[str, int]:
        """
        Get summary of actions by priority.

        Returns:
            Dictionary with counts by priority level
        """
        summary = {
            "immediate": 0,
            "urgent": 0,
            "important": 0,
            "routine": 0,
            "completed": len(self.completed_actions)
        }

        for action in self.active_actions:
            if not action.completed:
                priority_key = action.priority.name.lower()
                summary[priority_key] = summary.get(priority_key, 0) + 1

        return summary


# Global orchestrator instance
_action_orchestrator = None


def get_action_orchestrator() -> ActionOrchestrator:
    """
    Get or create the global action orchestrator instance.

    Returns:
        ActionOrchestrator instance
    """
    global _action_orchestrator
    if _action_orchestrator is None:
        _action_orchestrator = ActionOrchestrator()
    return _action_orchestrator
