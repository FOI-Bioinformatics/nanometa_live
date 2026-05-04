"""
Language simplification utilities for Nanometa Live v2.0.

This module provides translation functions to convert technical bioinformatics
terminology into plain language for non-technical operators (first responders,
laboratory personnel).
"""

from typing import Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


# Technical term to plain language mappings
TERM_TRANSLATIONS = {
    # Basic concepts
    "reads": "DNA sequences",
    "read": "DNA sequence",
    "base pairs": "genetic letters",
    "bp": "genetic letters",
    "quality score": "data quality",
    "phred score": "quality rating",

    # QC terms
    "fastp": "quality filtering",
    "filtered": "quality-checked",
    "unqualified": "low quality",
    "low complexity": "repetitive sequences",

    # Taxonomic terms
    "taxid": "species identifier",
    "taxonomic classification": "organism identification",
    "classified": "identified",
    "unclassified": "unidentified",
    "kraken2": "organism identification system",
    "kreport": "identification report",

    # Analysis terms
    "barcode": "sample tag",
    "demultiplexing": "sample separation",
    "fastq": "sequence data file",

    # Processing terms
    "pipeline": "analysis workflow",
    "workflow": "processing steps",
    "module": "analysis tool",
    "process": "analysis step",
}


# Status translations for different contexts
STATUS_TRANSLATIONS = {
    "running": "In Progress",
    "completed": "Complete",
    "failed": "Issue Detected",
    "pending": "Waiting",
    "idle": "Not Started",
    "processing": "Analyzing",
    "good": "Good",
    "review": "Needs Review",
    "issue": "Problem Detected",
}


# Metric descriptions for help text
METRIC_DESCRIPTIONS = {
    "total_reads": {
        "simple": "Total number of DNA sequences processed",
        "detailed": "The total count of DNA sequences that have been read by the sequencer and processed through quality control."
    },
    "pass_rate": {
        "simple": "Percentage of sequences that meet quality standards",
        "detailed": "The proportion of DNA sequences that passed quality filters based on accuracy, length, and sequence complexity."
    },
    "classified_rate": {
        "simple": "Percentage of sequences matched to known organisms",
        "detailed": "The proportion of quality-checked sequences that were successfully matched to organisms in the reference database."
    },
    "organisms_detected": {
        "simple": "Number of different organisms found in the sample",
        "detailed": "The count of unique species identified in the sample based on DNA sequence matches."
    },
    "quality_score": {
        "simple": "Overall data quality rating (0-100)",
        "detailed": "A composite score indicating the overall quality of sequencing data based on accuracy, yield, and classification success."
    }
}


# Action recommendations
ACTION_RECOMMENDATIONS = {
    "low_quality": "Check sequencing conditions (temperature, flow cell health, sample quality)",
    "low_yield": "Verify sufficient sample loading and sequencing run time",
    "low_classification": "Confirm appropriate reference database is selected for sample type",
    "high_error": "Review error logs and contact bioinformatics support team",
    "no_data": "Ensure sequencer is running and data is being generated",
    "completion": "Analysis complete - review results and generate report"
}


def translate_term(term: str, context: Optional[str] = None) -> str:
    """
    Translate a technical term to plain language.

    Args:
        term: Technical term to translate
        context: Optional context for context-specific translations

    Returns:
        Plain language equivalent or original term if no translation exists

    Examples:
        >>> translate_term("reads")
        'DNA sequences'
        >>> translate_term("kraken2")
        'organism identification system'
    """
    term_lower = term.lower().strip()

    # Try exact match first
    if term_lower in TERM_TRANSLATIONS:
        return TERM_TRANSLATIONS[term_lower]

    # Try partial matches for compound terms
    for tech_term, plain_term in TERM_TRANSLATIONS.items():
        if tech_term in term_lower:
            return term.replace(tech_term, plain_term)

    # Return original if no translation found
    return term


def translate_status(status: str) -> str:
    """
    Translate a status code to plain language.

    Args:
        status: Status code

    Returns:
        Plain language status

    Examples:
        >>> translate_status("running")
        'In Progress'
        >>> translate_status("good")
        'Good'
    """
    status_lower = status.lower().strip()
    return STATUS_TRANSLATIONS.get(status_lower, status.title())


def get_metric_description(metric: str, detailed: bool = False) -> str:
    """
    Get plain language description of a metric.

    Args:
        metric: Metric name
        detailed: If True, return detailed description; otherwise return simple

    Returns:
        Plain language description

    Examples:
        >>> get_metric_description("total_reads")
        'Total number of DNA sequences processed'
        >>> get_metric_description("pass_rate", detailed=True)
        'The proportion of DNA sequences that passed quality filters...'
    """
    metric_lower = metric.lower().strip()

    if metric_lower not in METRIC_DESCRIPTIONS:
        return f"Information about {translate_term(metric)}"

    desc_type = "detailed" if detailed else "simple"
    return METRIC_DESCRIPTIONS[metric_lower][desc_type]


def get_recommendation(situation: str) -> str:
    """
    Get plain language action recommendation for a situation.

    Args:
        situation: Situation code (e.g., "low_quality", "high_error")

    Returns:
        Plain language recommendation

    Examples:
        >>> get_recommendation("low_quality")
        'Check sequencing conditions (temperature, flow cell health, sample quality)'
    """
    situation_lower = situation.lower().strip()
    return ACTION_RECOMMENDATIONS.get(
        situation_lower,
        "Continue monitoring and contact support if issues persist"
    )


def format_number(value: int, use_plain_language: bool = True) -> str:
    """
    Format a number with thousands separators and optional plain language unit.

    Args:
        value: Number to format
        use_plain_language: If True, add plain language hints for large numbers

    Returns:
        Formatted number string

    Examples:
        >>> format_number(1500)
        '1,500'
        >>> format_number(1500000, use_plain_language=True)
        '1,500,000 (1.5 million)'
    """
    formatted = f"{value:,}"

    if not use_plain_language:
        return formatted

    # Add plain language hint for large numbers
    if value >= 1_000_000:
        millions = value / 1_000_000
        return f"{formatted} ({millions:.1f} million)"
    elif value >= 1_000_000_000:
        billions = value / 1_000_000_000
        return f"{formatted} ({billions:.1f} billion)"

    return formatted


def format_percentage(value: float, decimal_places: int = 1) -> str:
    """
    Format a percentage value with consistent decimal places.

    Args:
        value: Percentage value (0-100)
        decimal_places: Number of decimal places to show

    Returns:
        Formatted percentage string

    Examples:
        >>> format_percentage(75.5)
        '75.5%'
        >>> format_percentage(99.99, decimal_places=2)
        '99.99%'
    """
    return f"{value:.{decimal_places}f}%"


def format_time_duration(seconds: int) -> str:
    """
    Format a time duration in plain language.

    Args:
        seconds: Duration in seconds

    Returns:
        Plain language time string

    Examples:
        >>> format_time_duration(90)
        '1 minute 30 seconds'
        >>> format_time_duration(3661)
        '1 hour 1 minute'
    """
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"

    minutes = seconds // 60
    remaining_seconds = seconds % 60

    if minutes < 60:
        if remaining_seconds == 0:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        return f"{minutes} minute{'s' if minutes != 1 else ''} {remaining_seconds} second{'s' if remaining_seconds != 1 else ''}"

    hours = minutes // 60
    remaining_minutes = minutes % 60

    if hours < 24:
        if remaining_minutes == 0:
            return f"{hours} hour{'s' if hours != 1 else ''}"
        return f"{hours} hour{'s' if hours != 1 else ''} {remaining_minutes} minute{'s' if remaining_minutes != 1 else ''}"

    days = hours // 24
    remaining_hours = hours % 24

    if remaining_hours == 0:
        return f"{days} day{'s' if days != 1 else ''}"
    return f"{days} day{'s' if days != 1 else ''} {remaining_hours} hour{'s' if remaining_hours != 1 else ''}"


def create_plain_summary(
    total_reads: int,
    pass_rate: float,
    organisms_detected: int,
    sample_count: int
) -> str:
    """
    Create a plain language summary of analysis results.

    Args:
        total_reads: Total number of reads processed
        pass_rate: Percentage of reads that passed QC
        organisms_detected: Number of organisms identified
        sample_count: Number of samples analyzed

    Returns:
        Plain language summary paragraph

    Examples:
        >>> create_plain_summary(10000, 85.5, 12, 3)
        'Analyzed 10,000 DNA sequences from 3 samples. 85.5% met quality standards.
        Successfully identified 12 different organisms.'
    """
    reads_text = format_number(total_reads)
    sample_text = f"{sample_count} sample{'s' if sample_count != 1 else ''}"
    pass_text = format_percentage(pass_rate)
    org_text = f"{organisms_detected} different organism{'s' if organisms_detected != 1 else ''}"

    summary = (
        f"Analyzed {reads_text} DNA sequences from {sample_text}. "
        f"{pass_text} met quality standards. "
    )

    if organisms_detected > 0:
        summary += f"Successfully identified {org_text}."
    else:
        summary += "No organisms identified yet - analysis may still be in progress."

    return summary


def get_quality_interpretation(score: int) -> Tuple[str, str, str]:
    """
    Interpret a quality score (0-100) with plain language rating and color.

    Args:
        score: Quality score from 0-100

    Returns:
        Tuple of (rating, interpretation, color_code)

    Examples:
        >>> get_quality_interpretation(90)
        ('Excellent', 'Data quality is very good', 'success')
        >>> get_quality_interpretation(65)
        ('Fair', 'Data quality is acceptable but could be improved', 'warning')
    """
    if score >= 85:
        return (
            "Excellent",
            "Data quality is very good - proceed with confidence",
            "success"
        )
    elif score >= 75:
        return (
            "Good",
            "Data quality meets standards for reliable analysis",
            "success"
        )
    elif score >= 60:
        return (
            "Fair",
            "Data quality is acceptable but could be improved",
            "warning"
        )
    elif score >= 40:
        return (
            "Poor",
            "Data quality is below optimal - review sequencing conditions",
            "danger"
        )
    else:
        return (
            "Very Poor",
            "Data quality is concerning - immediate attention recommended",
            "danger"
        )


def create_help_text(topic: str) -> Dict[str, str]:
    """
    Generate help text for common topics in plain language.

    Args:
        topic: Help topic identifier

    Returns:
        Dictionary with 'title', 'summary', and 'details' keys

    Examples:
        >>> help_text = create_help_text("quality_score")
        >>> print(help_text['title'])
        'Understanding Data Quality'
    """
    help_topics = {
        "quality_score": {
            "title": "Understanding Data Quality",
            "summary": "Quality scores indicate how reliable your sequencing data is.",
            "details": (
                "The quality score (0-100) combines multiple factors:\n"
                "• Sequence accuracy (how many errors in the genetic code)\n"
                "• Data yield (how much usable data was generated)\n"
                "• Classification success (how many sequences matched known organisms)\n\n"
                "Higher scores mean more reliable results. Scores above 75 are good."
            )
        },
        "organism_identification": {
            "title": "How Organism Identification Works",
            "summary": "DNA sequences are matched against a database of known organisms.",
            "details": (
                "The system compares each DNA sequence to a reference database:\n"
                "1. Sequences are quality-checked\n"
                "2. They're compared to millions of known organisms\n"
                "3. Best matches are identified\n"
                "4. Results show which organisms are present\n\n"
                "Not all sequences can be identified - this is normal."
            )
        },
        "quality_filtering": {
            "title": "Quality Filtering Explained",
            "summary": "Poor quality sequences are removed to ensure accurate results.",
            "details": (
                "Sequences are filtered based on:\n"
                "• Too low quality: Many uncertain genetic letters\n"
                "• Too short: Sequence too brief for reliable matching\n"
                "• Low complexity: Repetitive patterns that can cause false matches\n\n"
                "Typical pass rates are 70-90%. Lower rates may indicate issues."
            )
        }
    }

    return help_topics.get(
        topic,
        {
            "title": "Help Information",
            "summary": "Additional help is available from your bioinformatics support team.",
            "details": "Contact your bioinformatics support team for detailed assistance with this topic."
        }
    )


def get_pathogen_action_guidance(threat_level: str) -> Dict[str, str]:
    """
    Get plain language action guidance for pathogen detections.

    This provides structured, actionable instructions for non-expert
    operators when dangerous pathogens are detected.

    Args:
        threat_level: Threat level (critical, high, moderate, low)

    Returns:
        Dict with 'immediate', 'next_steps', and 'contact' keys

    Examples:
        >>> guidance = get_pathogen_action_guidance("critical")
        >>> print(guidance['immediate'])
        'STOP work immediately. Do not touch the sample.'
    """
    guidance = {
        "critical": {
            "immediate": "STOP work immediately. Do not touch the sample.",
            "next_steps": "Secure the area. Notify your supervisor right away.",
            "contact": "Call your facility biosafety officer immediately.",
            "color": "danger"
        },
        "high": {
            "immediate": "Use appropriate personal protective equipment.",
            "next_steps": "Document the finding. Follow established protocols.",
            "contact": "Notify your supervisor within 1 hour.",
            "color": "danger"
        },
        "high_risk": {
            "immediate": "Use appropriate personal protective equipment.",
            "next_steps": "Document the finding. Follow established protocols.",
            "contact": "Notify your supervisor within 1 hour.",
            "color": "warning"
        },
        "moderate": {
            "immediate": "Continue standard safety procedures.",
            "next_steps": "Document and monitor. Verify with confirmatory testing.",
            "contact": "Report to supervisor at end of shift.",
            "color": "warning"
        },
        "low": {
            "immediate": "No immediate action required.",
            "next_steps": "Document for records.",
            "contact": "Include in routine reporting.",
            "color": "info"
        },
    }
    return guidance.get(threat_level.lower(), guidance["low"])


def get_classification_interpretation(rate: float) -> Tuple[str, str, str]:
    """
    Get plain language interpretation of classification rate.

    Args:
        rate: Classification rate percentage (0-100)

    Returns:
        Tuple of (rating_word, explanation, status_color)

    Examples:
        >>> get_classification_interpretation(75)
        ('High', 'Most sequences identified', 'success')
    """
    if rate >= 70:
        return ("High", "Most sequences identified", "success")
    elif rate >= 50:
        return ("Moderate", "Many sequences identified", "info")
    elif rate >= 30:
        return ("Low", "Limited identification", "warning")
    else:
        return ("Very Low", "Check database selection", "danger")


def get_read_count_interpretation(count: int) -> Tuple[str, str]:
    """
    Get plain language interpretation of read count.

    Args:
        count: Number of sequencing reads

    Returns:
        Tuple of (interpretation, explanation)

    Examples:
        >>> get_read_count_interpretation(500000)
        ('High', 'Good amount of data')
    """
    if count >= 1_000_000:
        return ("Very High", "Substantial data for analysis")
    elif count >= 100_000:
        return ("High", "Good amount of data")
    elif count >= 10_000:
        return ("Moderate", "Sufficient for basic analysis")
    elif count >= 1_000:
        return ("Low", "Limited data available")
    else:
        return ("Very Low", "May need more sequencing")
