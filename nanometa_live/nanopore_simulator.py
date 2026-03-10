#!/usr/bin/env python3
"""
Nanopore simulator for Nanometa Live (DEPRECATED).

This module has been superseded by the nanorunner package, which provides
more comprehensive nanopore run simulation capabilities including multiplexed
barcode support, mock community generation, and POD5 format handling.

For installation and usage of nanorunner, see:
    https://github.com/FOI-Bioinformatics/nanorunner
"""

import sys
import warnings


def nano_sim() -> int:
    """
    Deprecated entry point for the nanometa-sim command.

    Prints a deprecation notice directing users to nanorunner and exits
    with a non-zero status code.

    Returns:
        Exit code 1 to indicate the command is no longer functional.
    """
    warnings.warn(
        "nanometa-sim is deprecated and will be removed in a future release. "
        "Use nanorunner instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    message = (
        "\n"
        "=========================================================\n"
        "  DEPRECATION NOTICE: nanometa-sim has been deprecated.\n"
        "=========================================================\n"
        "\n"
        "The nanometa-sim command has been fully superseded by the\n"
        "nanorunner package, which offers improved functionality\n"
        "including:\n"
        "\n"
        "  - Multiplexed barcode simulation\n"
        "  - Mock community generation from NCBI genomes\n"
        "  - POD5/FAST5 format support\n"
        "  - Configurable read count and timing profiles\n"
        "\n"
        "To install nanorunner:\n"
        "\n"
        "    pip install nanorunner\n"
        "\n"
        "For usage information:\n"
        "\n"
        "    nanorunner --help\n"
        "    nanorunner generate --help\n"
        "\n"
        "For documentation, see:\n"
        "\n"
        "    https://github.com/FOI-Bioinformatics/nanorunner\n"
        "\n"
        "=========================================================\n"
    )
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(nano_sim())
