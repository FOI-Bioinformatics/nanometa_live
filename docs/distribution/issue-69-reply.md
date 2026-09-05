Thank you for the report, and apologies for the long silence on it.

Multiplexed (barcoded) runs are supported in the 2.x rewrite. Set
`sample_handling: by_barcode` in the configuration, or choose "By barcode"
in the Configuration tab, and point the input directory at the folder that
holds `barcode01/`, `barcode02/`, and so on (a MinKNOW `fastq_pass/` folder
is a valid input; `fastq_fail/` and `fastq_skip/` are excluded on intake).
The dashboard then lists every barcode in the sample selector, screens the
run as a whole for watchlist organisms, and names the barcodes carrying a
detection. Negative-control barcodes can be declared and are reported
alongside a detection rather than suppressing it.

Documentation: `docs/user-guide.md`, section "Barcoded data structure", and
`docs/quickstart-with-nanorunner.md` for an end-to-end demo with simulated
barcoded input.

Current release: Nanometa Live 0.18.0 with nanometanf v1.10.0. I am closing
this as addressed; please reopen if the current release does not cover your
layout, ideally with the directory listing and the configuration used.
