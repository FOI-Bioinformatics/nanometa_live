#!/bin/bash
# Build the subspecies ground-truth dataset: 7 barcodes, one generate
# process each so barcode assignment is explicit rather than inherited
# from flag order.
set -u
export PATH=/Users/andreassjodin/miniforge3/envs/nanorunner/bin:$PATH

G=/tmp/nanometa_subsp/genomes
D=/tmp/nanometa_subsp/dataset
L=/tmp/nanometa_subsp/logs
COMMON="--generator-backend badread --read-count 10000 --reads-per-file 1000 \
        --mean-read-length 4000 --no-wait --no-parallel \
        --force-structure singleplex --output-format fastq.gz"

pure () {  # $1=barcode  $2=genome stem  $3=seed
  nanorunner generate --target $D/$1 --genomes $G/$2.fna.gz \
      $COMMON --seed $3 > $L/$1.log 2>&1
  echo "$1 done"
}

mixed () {  # $1=barcode $2=stemA $3=stemB $4=abundA $5=abundB $6=seed
  nanorunner generate --target $D/$1 \
      --genomes $G/$2.fna.gz --genomes $G/$3.fna.gz \
      --abundances $4 --abundances $5 --mix-reads \
      $COMMON --seed $6 > $L/$1.log 2>&1
  echo "$1 done"
}

pure  barcode01 holarctica_LVS       101 &
pure  barcode02 tularensis_SCHUS4    102 &
pure  barcode03 mediasiatica_FSC147  103 &
pure  barcode04 novicida_U112        104 &
mixed barcode05 holarctica_LVS tularensis_SCHUS4 0.7 0.3 105 &
pure  barcode06 philomiragia         106 &
mixed barcode07 ecoli_K12 holarctica_LVS 0.998 0.002 107 &
wait
echo "ALL BARCODES COMPLETE"
