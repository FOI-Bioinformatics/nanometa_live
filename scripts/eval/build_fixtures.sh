#!/usr/bin/env bash
# Build the four small test fixtures used by the eval test matrix.
#
# Sources:
#   /Users/andreassjodin/Desktop/snabbsekvensering/bioshield/_data/rawdata-barcodes12/
#       12 barcodes -- restricted to barcode01..barcode05 here.
#       Each barcode has one large *.fastq.gz; we head -100 reads via seqkit
#       so nanorunner does not rechunk a multi-million-read source.
#   /Users/andreassjodin/Desktop/snabbsekvensering/bioshield/_data/demo-turexzymo-chunks/
#       Pre-chunked Turex/ and Zymo/ subdirs; already small (~10 chunks, ~16 KB each).
#
# Output (kept outside the repository):
#   /Users/andreassjodin/Desktop/snabbsekvensering/output-live/fixtures/
#     multiplex-bc5/        # 5 barcodes (multiplex layout)
#     singleplex-flat/      # Turex+Zymo flattened, one logical sample
#     per-file-flat/        # same content as singleplex-flat (per_file mode at GUI time)
#     samplesheet/          # CSV pointing at the layouts above
#
# Each fixture is rechunked through nanorunner --reads-per-file 10 so the
# matrix runs in seconds rather than minutes.
#
# Requirements: conda envs "nanorunner" and "seqkit".

set -euo pipefail

SRC_BC=/Users/andreassjodin/Desktop/snabbsekvensering/bioshield/_data/rawdata-barcodes12
SRC_CHUNKS=/Users/andreassjodin/Desktop/snabbsekvensering/bioshield/_data/demo-turexzymo-chunks
DEST=/Users/andreassjodin/Desktop/snabbsekvensering/output-live/fixtures
TMPDIR_BC5=$(mktemp -d -t nm_bc5_XXXX)
TMPDIR_FLAT=$(mktemp -d -t nm_flat_XXXX)

echo "== build_fixtures.sh =="
echo "  destination: ${DEST}"
echo "  staging bc5: ${TMPDIR_BC5}"
echo "  staging flat: ${TMPDIR_FLAT}"

mkdir -p "${DEST}"
rm -rf "${DEST}/multiplex-bc5" "${DEST}/singleplex-flat" "${DEST}/per-file-flat" "${DEST}/samplesheet"
mkdir -p "${DEST}/samplesheet"

# --- stage barcode01..05 (head -100 reads each) ---------------------------
echo "[stage] head 100 reads per barcode (seqkit)"
for bc in barcode01 barcode02 barcode03 barcode04 barcode05; do
    mkdir -p "${TMPDIR_BC5}/${bc}"
    src_fq=$(ls "${SRC_BC}/${bc}/"*.fastq.gz | head -1)
    conda run -n seqkit seqkit head -n 100 "${src_fq}" \
        -o "${TMPDIR_BC5}/${bc}/${bc}.fastq.gz" --quiet
done

# --- stage flat singleplex (Turex + Zymo combined, already small) ----------
mkdir -p "${TMPDIR_FLAT}/flat"
cp "${SRC_CHUNKS}/Turex/"*.fastq.gz "${TMPDIR_FLAT}/flat/"
cp "${SRC_CHUNKS}/Zymo/"*.fastq.gz  "${TMPDIR_FLAT}/flat/"

# --- nanorunner: multiplex-bc5 (static copy, rechunked to 10 reads/file) ---
echo "[1/3] nanorunner replay -> multiplex-bc5"
conda run -n nanorunner nanorunner replay \
    --source "${TMPDIR_BC5}" \
    --target "${DEST}/multiplex-bc5" \
    --reads-per-file 10 --interval 0.05 --batch-size 32 \
    --force-structure multiplex --no-wait --quiet

# --- nanorunner: singleplex-flat -------------------------------------------
echo "[2/3] nanorunner replay -> singleplex-flat"
conda run -n nanorunner nanorunner replay \
    --source "${TMPDIR_FLAT}/flat" \
    --target "${DEST}/singleplex-flat" \
    --reads-per-file 10 --interval 0.05 --batch-size 32 \
    --force-structure singleplex --no-wait --quiet

# --- per-file-flat: identical content to singleplex-flat -------------------
# Layout on disk is identical; sample_handling=per_file at GUI time decides
# whether each fastq is its own sample.
echo "[3/3] cp singleplex-flat -> per-file-flat"
cp -R "${DEST}/singleplex-flat" "${DEST}/per-file-flat"

# --- samplesheet for batch+samplesheet row ---------------------------------
SS="${DEST}/samplesheet/samplesheet.csv"
{
    echo "sample,barcode,fastq_path"
    for bc in barcode01 barcode02 barcode03 barcode04 barcode05; do
        echo "${bc},${bc},${DEST}/multiplex-bc5/${bc}"
    done
} > "${SS}"

# --- cleanup ---------------------------------------------------------------
rm -rf "${TMPDIR_BC5}" "${TMPDIR_FLAT}"

echo "== done =="
echo "  multiplex-bc5:    $(find "${DEST}/multiplex-bc5"   -name '*.fastq.gz' | wc -l) fastq files"
echo "  singleplex-flat:  $(find "${DEST}/singleplex-flat" -name '*.fastq.gz' | wc -l) fastq files"
echo "  per-file-flat:    $(find "${DEST}/per-file-flat"   -name '*.fastq.gz' | wc -l) fastq files"
echo "  samplesheet:      ${SS}"
