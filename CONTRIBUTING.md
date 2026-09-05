# Contributing to Nanometa Live

## Set up

```bash
git clone https://github.com/FOI-Bioinformatics/nanometa_live.git
cd nanometa_live
conda env create -f nanometa_live_env.yml   # includes Nextflow >= 26.04.0
conda activate nanometa_live_env
pip install -e ".[dev]"
pytest -q
```

The suite has about 4,100 tests and runs in parallel by default. Tests
marked `slow` need Nextflow and conda and are skipped unless selected with
`-m slow`. The coverage gate (`pytest --cov=nanometa_live`) enforces the
floor in `pytest.ini`; do not lower it.

## Where things are

- `nanometa_live/app/` is the Dash application. Each tab is a `*_tab.py`
  (callback wiring) beside a `*_helpers.py` (pure logic). Put logic in the
  helper and test it without an app.
- `nanometa_live/core/` holds loaders, parsers, taxonomy, the watchlist and
  the pipeline launcher. Import from the leaf module that owns a symbol.
- `docs/decisions/` holds the decisions the code depends on, each with the
  test that pins it. Read these first; they replace reading `CLAUDE.md`
  end to end. `CLAUDE.md` remains the detailed working notes.
- `docs/audit/` records what was tried on real runs and what was found.
  `docs/known-untested-surface.md` says what has not been verified.

## Rules that have a fence

Several properties are enforced by tests that read the code: no background
callback takes a per-tick Input; every module-level cache is wired into
the reset functions; tab gating is display-only; the README compatibility
table names the pipeline floor; every decision record has its sections.
When such a test fails, the property it names has been broken; do not edit
the test to make it pass.

## Companion pipeline

The GUI launches [nanometanf](https://github.com/FOI-Bioinformatics/nanometanf).
The two are released together (see the README compatibility table). A GUI
change that sends a new parameter needs the pipeline change first, and
`NANOMETANF_MIN_VERSION` in `core/workflow/pipeline_compat.py` bumped in the
same commit. nanometanf work stays on its `dev` branch and reaches `master`
through a pull request, because its lint and pre-commit checks run only on
pull requests.

## Releasing

1. On `dev`: bump `nanometa_live/__init__.py`, move the `Unreleased`
   changelog section under the new version with the date, commit
   `chore(release): prepare X.Y.Z`.
2. Open a pull request from `dev` to `main`; CI must be green.
3. Merge, tag `X.Y.Z` (no `v` prefix), publish a GitHub release. The
   publish workflow builds and uploads to PyPI.
4. Update the bioconda recipe (version and sha256) in a pull request to
   bioconda-recipes.

## Style

Modest scientific language in code, documentation and commit messages. No
Unicode in Nextflow files. Commit subjects follow `type(scope): summary`
with a body that says what was wrong and what changed.

## Becoming a maintainer

A second maintainer needs, in this order: the ten decision records, one
full read of `docs/OPERATOR_GUIDE.md`, one end-to-end run of
`docs/quickstart-with-nanorunner.md`, and one release cut with the current
maintainer watching. After that, review rights on both repositories.
