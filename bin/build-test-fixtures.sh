#!/usr/bin/env bash
# build-test-fixtures.sh
#
# Build four reproducible Nanometa Live test fixtures from real ONT data
# using nanorunner replay (rechunking + multiplex/singleplex layout).
#
# ----------------------------------------------------------------------------
# Source data
# ----------------------------------------------------------------------------
# Raw input directory: $HOME/Desktop/snabbsekvensering/rawdata/
# Twelve flat FASTQ.gz files. Five of them are picked for the fixture set:
#
#   1. LVS_1_barcode11          - Francisella tularensis (LVS strain), neat
#                                  bacterial sample. Diverse hits expected.
#   2. D6300_2_barcode14        - ZymoBIOMICS D6300 mock community; well
#                                  characterised multi-organism reference.
#   3. Turex_3_barcode13        - Bacillus thuringiensis (Turex), select-agent
#                                  relative; useful for watchlist matching.
#   4. Ricin_crude_1_barcode12  - Ricinus communis crude prep; eukaryotic /
#                                  toxin-relevant material.
#   5. negative_barcode16       - Negative control; exercises the
#                                  is_negative_control attribution path.
#
# These cover diverse organisms (bacterium, mock community, plant, BSL-3
# relative) plus a negative control, in a small enough size envelope to keep
# each fixture directory under 50 MB after rechunking.
#
# ----------------------------------------------------------------------------
# Conda environment
# ----------------------------------------------------------------------------
# Uses `conda run -n nanorunner nanorunner replay ...` so no `conda activate`
# side effects leak into the caller's shell. Tested with nanorunner 3.0.0.
#
# ----------------------------------------------------------------------------
# Output directories
# ----------------------------------------------------------------------------
# $HOME/Desktop/snabbsekvensering/fixtures/
#   |- samplesheet/             - Five flat rechunked FASTQs + samplesheet.csv
#   |                              for nanometanf batch / samplesheet input.
#   |- realtime_multiplex/      - barcode01..barcode05 subdirs with chunked
#   |                              files; emulates live multiplexed run.
#   |- realtime_single_file/    - One sample, flat layout, multiple chunks;
#   |                              emulates live singleplex (per-file mode).
#   |- realtime_single_folder/  - Same chunks as realtime_single_file but
#                                  nested under one subdirectory; tests the
#                                  single-folder watched layout.
#
# ----------------------------------------------------------------------------
# Idempotency / clean-and-rerun
# ----------------------------------------------------------------------------
# The script is idempotent: it removes the fixtures/ tree at the start of
# each run and rebuilds it from scratch. To clean and rerun manually:
#
#   rm -rf "$HOME/Desktop/snabbsekvensering/fixtures"
#   bash $HOME/Desktop/deving/nanometa_live/bin/build-test-fixtures.sh
#
# ----------------------------------------------------------------------------
# Constraints honoured
# ----------------------------------------------------------------------------
#   - Only $HOME is consumed from the environment.
#   - All FASTQ writing goes through nanorunner; no Python heredocs.
#   - --no-wait is passed so the build does not block on timing replay; the
#     timing-aware replay is left to a later real-time test runner.
#
# ============================================================================

set -euo pipefail

RAW_DIR="${HOME}/Desktop/snabbsekvensering/rawdata"
FIX_ROOT="${HOME}/Desktop/snabbsekvensering/fixtures"
STAGE_ROOT="$(mktemp -d -t nanometa-fixtures.XXXXXX)"
trap 'rm -rf "${STAGE_ROOT}"' EXIT

# Picked source files (5 of 12)
SAMPLES=(
  "LVS_1_barcode11.fastq.gz"
  "D6300_2_barcode14.fastq.gz"
  "Turex_3_barcode13.fastq.gz"
  "Ricin_crude_1_barcode12.fastq.gz"
  "negative_barcode16.fastq.gz"
)

# Sample stems used for samplesheet "sample" column and folder names.
# Drop the trailing _barcodeNN to keep names clean.
sample_stem () {
  local fname="$1"
  fname="${fname%.fastq.gz}"
  fname="${fname%_barcode[0-9][0-9]}"
  printf '%s' "$fname"
}

echo "[fixtures] nanorunner version: $(conda run -n nanorunner nanorunner --version)"
echo "[fixtures] Raw source        : ${RAW_DIR}"
echo "[fixtures] Fixture root      : ${FIX_ROOT}"
echo "[fixtures] Staging root      : ${STAGE_ROOT}"

# Sanity: every picked file must exist in the raw dir.
for f in "${SAMPLES[@]}"; do
  if [[ ! -f "${RAW_DIR}/${f}" ]]; then
    echo "[fixtures] ERROR: missing source file ${RAW_DIR}/${f}" >&2
    exit 1
  fi
done

# Subsample each picked source file to MAX_READS records. nanorunner's
# --reads-per-file flag rechunks but does not cap total reads, so without
# this step a 140 MB source file produces hundreds of small chunks that
# blow past the per-fixture 50 MB target. Each FASTQ record is 4 lines,
# so we take MAX_READS * 4 lines from the gzipped stream and re-gzip.
MAX_READS=500
SUBSAMPLED_DIR="${STAGE_ROOT}/subsampled_src"
mkdir -p "${SUBSAMPLED_DIR}"
echo "[fixtures] Subsampling sources to ${MAX_READS} reads each"
for f in "${SAMPLES[@]}"; do
  # Use `gunzip -c` rather than `zcat` because macOS `zcat` only handles
  # legacy .Z files; gunzip is consistent across Linux and macOS. We
  # drop pipefail just for this pipeline because `head` closes stdin
  # early and gunzip exits with SIGPIPE, which set -o pipefail would
  # treat as a script-level failure.
  set +o pipefail
  gunzip -c "${RAW_DIR}/${f}" | head -n $((MAX_READS * 4)) | gzip > "${SUBSAMPLED_DIR}/${f}"
  set -o pipefail
  echo "[fixtures]   subsampled ${f}"
done

# Wipe and recreate the fixtures tree for idempotency.
rm -rf "${FIX_ROOT}"
mkdir -p "${FIX_ROOT}"

# ----------------------------------------------------------------------------
# Fixture (a): samplesheet/  -- 5 flat rechunked FASTQs + samplesheet.csv
# ----------------------------------------------------------------------------
echo "[fixtures] Building (a) samplesheet/"
SS_OUT="${FIX_ROOT}/samplesheet"
mkdir -p "${SS_OUT}"

# WORKAROUND for nanorunner replay singleplex bug (filed under audit
# Phase B as a finding for nanorunner): when --source contains more
# than one FASTQ, nanorunner only emits chunks for the alphabetically
# first file and silently skips the rest. Until the upstream bug is
# fixed, we run nanorunner once per sample with a single-file staging
# directory.
for f in "${SAMPLES[@]}"; do
  SAMPLE_STAGE="${STAGE_ROOT}/ss_$(echo "${f}" | tr -c 'A-Za-z0-9' '_')"
  mkdir -p "${SAMPLE_STAGE}"
  cp "${SUBSAMPLED_DIR}/${f}" "${SAMPLE_STAGE}/${f}"
  conda run -n nanorunner nanorunner replay \
    --source "${SAMPLE_STAGE}" \
    --target "${SS_OUT}" \
    --reads-per-file 100 \
    --no-wait \
    --operation copy \
    --force-structure singleplex \
    --quiet
done

# Generate samplesheet.csv. nanorunner rechunks each input into one or more
# files named <stem>_<part>.fastq.gz. We stitch all chunk parts back into a
# single per-sample chunk (the fixture is small, ~100 reads); the samplesheet
# points at the first chunk for that sample. nanometanf's schema_input.json
# accepts one fastq per row, so we collapse using the first chunk and rely
# on rechunk size = 100 (one chunk file per sample is the common case at
# this size).
SAMPLESHEET="${SS_OUT}/samplesheet.csv"
{
  printf 'sample,fastq,barcode\n'
  for f in "${SAMPLES[@]}"; do
    stem="$(sample_stem "$f")"
    # First chunk file matching this stem.
    first_chunk="$(find "${SS_OUT}" -maxdepth 1 -type f -name "${stem}_*.fastq.gz" | sort | head -n1)"
    if [[ -z "${first_chunk}" ]]; then
      # Fallback: nanorunner may keep the original basename if reads <= chunk size.
      first_chunk="$(find "${SS_OUT}" -maxdepth 1 -type f -name "${f}" | head -n1)"
    fi
    if [[ -z "${first_chunk}" ]]; then
      echo "[fixtures] ERROR: no chunk produced for ${stem}" >&2
      exit 1
    fi
    printf '%s,%s,\n' "${stem}" "${first_chunk}"
  done
} > "${SAMPLESHEET}"

# ----------------------------------------------------------------------------
# Fixture (b): realtime_multiplex/  -- barcode01..barcode05 subdirs
# ----------------------------------------------------------------------------
echo "[fixtures] Building (b) realtime_multiplex/"
MP_STAGE="${STAGE_ROOT}/multiplex_src"
mkdir -p "${MP_STAGE}"
i=1
for f in "${SAMPLES[@]}"; do
  bdir="$(printf 'barcode%02d' "${i}")"
  mkdir -p "${MP_STAGE}/${bdir}"
  cp "${SUBSAMPLED_DIR}/${f}" "${MP_STAGE}/${bdir}/${f}"
  i=$((i + 1))
done

MP_OUT="${FIX_ROOT}/realtime_multiplex"
mkdir -p "${MP_OUT}"

# Same per-source-file workaround as fixture (a). Multiplex mode runs
# one barcode dir at a time so nanorunner sees a single file each
# invocation but writes into the matching barcodeXX subdir under MP_OUT.
i=1
for f in "${SAMPLES[@]}"; do
  bdir="$(printf 'barcode%02d' "${i}")"
  PER_BARCODE_STAGE="${STAGE_ROOT}/mp_${bdir}"
  mkdir -p "${PER_BARCODE_STAGE}/${bdir}"
  cp "${SUBSAMPLED_DIR}/${f}" "${PER_BARCODE_STAGE}/${bdir}/${f}"
  conda run -n nanorunner nanorunner replay \
    --source "${PER_BARCODE_STAGE}" \
    --target "${MP_OUT}" \
    --reads-per-file 50 \
    --no-wait \
    --operation copy \
    --force-structure multiplex \
    --quiet
  i=$((i + 1))
done

# ----------------------------------------------------------------------------
# Fixture (c): realtime_single_file/  -- one sample, flat, many chunks
# ----------------------------------------------------------------------------
echo "[fixtures] Building (c) realtime_single_file/"
SF_STAGE="${STAGE_ROOT}/single_file_src"
mkdir -p "${SF_STAGE}"
cp "${SUBSAMPLED_DIR}/LVS_1_barcode11.fastq.gz" "${SF_STAGE}/LVS_1_barcode11.fastq.gz"

SF_OUT="${FIX_ROOT}/realtime_single_file"
mkdir -p "${SF_OUT}"
conda run -n nanorunner nanorunner replay \
  --source "${SF_STAGE}" \
  --target "${SF_OUT}" \
  --reads-per-file 25 \
  --no-wait \
  --operation copy \
  --force-structure singleplex \
  --quiet

# ----------------------------------------------------------------------------
# Fixture (d): realtime_single_folder/  -- same chunks, nested under <sample>/
# ----------------------------------------------------------------------------
echo "[fixtures] Building (d) realtime_single_folder/"
FF_OUT="${FIX_ROOT}/realtime_single_folder"
mkdir -p "${FF_OUT}/LVS_1"
# Copy every file produced under (c) into the nested LVS_1 subdir.
find "${SF_OUT}" -maxdepth 1 -type f -name '*.fastq.gz' -print0 \
  | xargs -0 -I{} cp {} "${FF_OUT}/LVS_1/"

echo "[fixtures] Done."
echo "[fixtures] Sizes:"
du -sh "${FIX_ROOT}"/*
