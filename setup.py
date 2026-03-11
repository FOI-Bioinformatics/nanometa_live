"""
Setup file for the Nanometa Live application.

This script specifies the Python packages, entry points, and dependencies needed
for installing and running the Nanometa Live application.
"""

from setuptools import setup, find_packages


# Read version from __init__.py without importing the package, which would
# fail during installation before dependencies are available.
def _read_version() -> str:
    import re
    with open("nanometa_live/__init__.py") as f:
        match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', f.read(), re.M)
        if match:
            return match.group(1)
        raise RuntimeError("Unable to find __version__ in nanometa_live/__init__.py")


# Read requirements.txt for dependencies, filtering comments and blank lines
with open('requirements.txt', 'r') as f:
    requirements = [
        line.split('#')[0].strip()
        for line in f
        if line.strip() and not line.strip().startswith('#')
    ]

setup(
    name="Nanometa_Live",
    version=_read_version(),
    description="Real-time metagenomic analysis with a user-friendly interface",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Nanometa Live Team",
    url="https://github.com/FOI-Bioinformatics/nanometa_live",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        'nanometa_live': [
            'config.yaml',
            'kraken2_databases.yaml',
            'app/assets/*',
            'core/config/data/*.yaml',
            'core/config/data/watchlists/*.yaml',
            'core/config/data/watchlists/examples/*.yaml',
        ]
    },
    entry_points={
        'console_scripts': [
            'nanometa-live=nanometa_live.nanometa_live:main',
            # Deprecated: nanometa-sim is superseded by nanorunner.
            # Retained as a stub that prints a deprecation notice.
            # Remove this entry point in a future release.
            'nanometa-sim=nanometa_live.nanopore_simulator:nano_sim',
            'nanometa-prepare=nanometa_live.cli.prepare:main'
        ]
    },
    install_requires=requirements,
    python_requires='>=3.9',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Scientific/Engineering :: Bio-Informatics',
    ],
)