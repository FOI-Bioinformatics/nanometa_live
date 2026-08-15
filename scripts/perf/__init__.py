"""Sample-count scaling performance harness for the Nanometa Live loaders.

This package lives outside ``tests/`` on purpose. ``pytest.ini`` runs the
suite under ``pytest-xdist`` with ``-n auto``, so timing measurements taken
inside the suite would compete with parallel workers for CPU and page cache.
The counters in :mod:`scripts.perf.instrument` also patch ``os.stat``
process-globally, which is unsafe to do while unrelated tests are running in
the same interpreter.

Entry point::

    python -m scripts.perf.scaling_bench --help
"""
