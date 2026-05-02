#!/usr/bin/env bash
# run-mode-test.sh -- Phase C end-to-end mode driver.
#
# Runs the nanometanf pipeline against one of the four fixture
# directories produced by `bin/build-test-fixtures.sh` and writes the
# pipeline output under
# $HOME/Desktop/snabbsekvensering/output-live/<mode>/.
#
# Usage:
#   bin/run-mode-test.sh samplesheet
#   bin/run-mode-test.sh realtime_multiplex
#   bin/run-mode-test.sh realtime_single_file
#   bin/run-mode-test.sh realtime_single_folder
#
# The script pins NXF_VER=25.04.7 (matches nanometanf's
# bin/run-nf-tests.sh) to avoid the watchPath JVM cleanup hang on
# 25.10.4, and reuses the pre-warmed conda env cache at
# ~/.nanometa/work/conda so the first run does not have to rebuild
# every env from scratch.
#
# All four modes write under the same output-live tree; the
# 2026-05-02 collision UX in the GUI handles the "this output dir
# already has results" case for follow-up runs.

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <samplesheet|realtime_multiplex|realtime_single_file|realtime_single_folder>" >&2
  exit 2
fi

MODE="$1"
FIX_ROOT="${HOME}/Desktop/snabbsekvensering/fixtures"
OUT_ROOT="${HOME}/Desktop/snabbsekvensering/output-live"
PIPELINE_DIR="${HOME}/Code/nanometanf"
KRAKEN_DB="${HOME}/Desktop/kraken_db/k2_pluspfp_08_GB_20251015"

if [[ ! -d "${FIX_ROOT}/${MODE}" ]]; then
  echo "ERROR: fixture not found: ${FIX_ROOT}/${MODE}" >&2
  echo "       Run bin/build-test-fixtures.sh first." >&2
  exit 1
fi

if [[ ! -d "${KRAKEN_DB}" ]]; then
  echo "ERROR: Kraken2 DB not found at ${KRAKEN_DB}" >&2
  exit 1
fi

OUTDIR="${OUT_ROOT}/${MODE}"
mkdir -p "${OUTDIR}"

# Reuse pre-warmed conda envs to keep the wall-clock manageable.
export NXF_VER=25.04.7
export NXF_OFFLINE=true
export NXF_CONDA_CACHEDIR="${HOME}/.nanometa/work/conda"

echo "[mode-test] mode      : ${MODE}"
echo "[mode-test] fixture   : ${FIX_ROOT}/${MODE}"
echo "[mode-test] outdir    : ${OUTDIR}"
echo "[mode-test] pipeline  : ${PIPELINE_DIR}"
echo "[mode-test] kraken DB : ${KRAKEN_DB}"
echo "[mode-test] NXF_VER   : ${NXF_VER}"
echo

case "${MODE}" in
  samplesheet)
    EXTRA_ARGS=(
      --input "${FIX_ROOT}/${MODE}/samplesheet.csv"
    )
    ;;
  realtime_multiplex)
    EXTRA_ARGS=(
      --realtime_mode
      --nanopore_output_dir "${FIX_ROOT}/${MODE}"
      --file_pattern '**.fastq{,.gz}'
      --max_files 10
      --realtime_timeout_minutes 1
      --realtime_processing_grace_period 1
      --batch_size 2
      --batch_timeout 2
    )
    ;;
  realtime_single_file)
    EXTRA_ARGS=(
      --realtime_mode
      --nanopore_output_dir "${FIX_ROOT}/${MODE}"
      --file_pattern '*.fastq{,.gz}'
      --max_files 5
      --realtime_timeout_minutes 1
      --realtime_processing_grace_period 1
      --batch_size 2
      --batch_timeout 2
    )
    ;;
  realtime_single_folder)
    EXTRA_ARGS=(
      --realtime_mode
      --nanopore_output_dir "${FIX_ROOT}/${MODE}"
      --file_pattern '**.fastq{,.gz}'
      --max_files 5
      --realtime_timeout_minutes 1
      --realtime_processing_grace_period 1
      --batch_size 2
      --batch_timeout 2
    )
    ;;
  *)
    echo "ERROR: unknown mode ${MODE}" >&2
    exit 2
    ;;
esac

cd "${PIPELINE_DIR}"
conda run -n nf-core nextflow run main.nf \
  -profile conda \
  --outdir "${OUTDIR}" \
  --kraken2_db "${KRAKEN_DB}" \
  -work-dir "${OUTDIR}/work" \
  "${EXTRA_ARGS[@]}" \
  2>&1 | tee "${OUTDIR}/run.log"

echo
echo "[mode-test] exit status: ${PIPESTATUS[0]}"
echo "[mode-test] outputs under ${OUTDIR}:"
ls -1 "${OUTDIR}"
