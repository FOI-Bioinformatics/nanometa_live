"""
Gets the timestamps from the nanopore batch files.
Also gets the number of seqs and bp in the files.

This allows creation of qc data: seqs/time and bp/time.

This script processes the files one by one. Another snakemake rule
concatenates the files to a cumulative list containg data on all the
files.

"""

from Bio import SeqIO
import sys
import datetime
import os
import gzip

# Reading in the file names from the terminal argunments.
in_file = sys.argv[1]
out_file = sys.argv[2]

#print(in_file)
#print(out_file)
#print(time_file)

# gets the timestamp from the nanopore batch files
creation_time = os.path.getmtime(in_file) 
# transforms timestamp to human readable time object
creation_time = datetime.datetime.fromtimestamp(creation_time) 

with gzip.open(in_file, 'rt') as inF:
    # count seqs and bp in the fastq file
    bp = 0
    seqs = 0
    for record in SeqIO.parse(inF, "fastq"): 
        bp += len(record.seq)
        seqs += 1
    
    # saves the info in a txt/csv file
    with open(out_file, 'w') as outF: 
        csv_row = str(creation_time) + ',' + str(seqs) + ',' + str(bp) + '\n'
        outF.write(csv_row)
