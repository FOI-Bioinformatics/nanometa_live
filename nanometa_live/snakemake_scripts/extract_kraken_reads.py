I'll provide the complete code for the Snakemake script files you requested. These scripts are used by the Snakemake workflow for processing metagenomic data.

## 1. combine_kreports.py

```python
#!/usr/bin/env python
################################################################
#combine_kreports.py takes multiple kraken-style reports and combines
#them into a single report file
#Copyright (C) 2019-2020 Jennifer Lu, jennifer.lu717@gmail.com
#
#This file is part of KrakenTools
#KrakenTools is free software; you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation; either version 3 of the license, or
#(at your option) any later version.

#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License
#along with this program; if not, see <http://www.gnu.org/licenses/>.

#################################################################
#Jennifer Lu, jlu26@jhmi.edu
#Updated: 05/16/2019
#
#This program reads in multiple Kraken report files and generates
#a combined Kraken report with columns for read counts and summarized
#read counts for each sample, along with two columns for across-sample sums
#
#Parameters:
#   -h, --help................show help message.
#   -r X, --report-file X.....all input kraken reports (separated by spaces)
#   -o X, --output X..........output kraken report filename
#   --display-headers.........includes header lines mapping samples to abbreviated names
#                             [default:true]
#   --no-headers..............do not include header lines [default:false]
#   --sample-names............sample names for each kraken report (separated by spaces)
#                             [if none are given, each sample is given names S1, S2, etc]
#Each Input report file format (tab-delimited)
#   - percentage of total reads
#   - number of reads (including reads within subtree)
#   - number of reads (only at this level)
#   - taxonomic classification level (U, D, P, C, O, F, G, S,...etc)
#   - NCBI taxonomic ID
#   - name of level
#Output file format (tab-delimited)
#   - percentage of total reads (for summed reads)
#   - combined number of reads (including reads within subtree)
#   - combined number of reads (only at this level)
#   - S1_all_reads, S1_lvl_reads, S2_all_reads, S2_lvl_reads, ...etc.
#   - taxonomic classification level (U, D, P, C, O, F, G, S,...etc)
#   - NCBI taxonomic ID
#   - name of level
#Methods
#   - main
#   - process_kraken_report
####################################################################
import os, sys, argparse
import operator
from time import gmtime
from time import strftime

#Tree Class
#usage: tree node used in constructing a taxonomy tree
#   including only the taxonomy levels and genomes identified in the Kraken report
class Tree(object):
    'Tree node.'
    def __init__(self, name, taxid, level_num, level_id, all_reads, lvl_reads, children=None, parent=None):
        self.name = name
        self.taxid = taxid
        self.level_num = level_num
        self.level_id = level_id
        self.tot_all = all_reads
        self.tot_lvl = lvl_reads
        self.all_reads = {}
        self.lvl_reads = {}
        self.children = []
        self.parent = parent
        if children is not None:
            for child in children:
                self.add_child(child)
    def add_child(self,node):
        assert isinstance(node,Tree)
        self.children.append(node)
    def add_reads(self, sample, all_reads, lvl_reads):
        self.all_reads[sample] = all_reads
        self.lvl_reads[sample] = lvl_reads
        self.tot_all += all_reads
        self.tot_lvl += lvl_reads
    def __lt__(self,other):
        return self.tot_all < other.tot_all

####################################################################
#process_kraken_report
#usage: parses a single line in the kraken report and extracts relevant information
#input: kraken report file with the following tab delimited lines
#   - percent of total reads
#   - number of reads (including at lower levels)
#   - number of reads (only at this level)
#   - taxonomy classification of level
#       (U, - (root), - (cellular org), D, P, C, O, F, G, S)
#   - taxonomy ID (0 = unclassified, 1 = root, 2 = Bacteria...etc)
#   - spaces + name
#returns:
#   - classification/genome name
#   - taxonomy ID for this classification
#   - level for this classification (number)
#   - level name (U, -, D, P, C, O, F, G, S)
#   - all reads classified at this level and below in the tree
#   - reads classified only at this level
def process_kraken_report(curr_str):
    split_str = curr_str.strip().split('\t')
    if len(split_str) < 5:
        return []
    try:
        int(split_str[1])
    except ValueError:
        return []
    #Extract relevant information
    all_reads =  int(split_str[1])
    level_reads = int(split_str[2])
    level_type = split_str[-3]
    taxid = split_str[-2]
    #Get name and spaces
    spaces = 0
    name = split_str[-1]
    for char in name:
        if char == ' ':
            name = name[1:]
            spaces += 1
        else:
            break
    #Determine which level based on number of spaces
    level_num = int(spaces/2)
    return [name, taxid, level_num, level_type, all_reads, level_reads]

####################################################################
#Main method
def main():
    #Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('-r','--report-file','--report-files',
        '--report','--reports', required=True,dest='r_files',nargs='+',
        help='Input kraken report files to combine (separate by spaces)')
    parser.add_argument('-o','--output', required=True,dest='output',
        help='Output kraken report file with combined information')
    parser.add_argument('--display-headers',required=False,dest='headers',
        action='store_true', default=True,
        help='Include header lines')
    parser.add_argument('--no-headers',required=False,dest='headers',
        action='store_false',default=True,
        help='Do not include header lines')
    parser.add_argument('--sample-names',required=False,nargs='+',
        dest='s_names',default=[],help='Sample names to use as headers in the new report')
    parser.add_argument('--only-combined', required=False, dest='c_only',
        action='store_true', default=False,
        help='Include only the total combined reads column, not the individual sample cols')
    args=parser.parse_args()


    #Initialize combined values
    main_lvls = ['U','R','D','K','P','C','O','F','G','S']
    map_lvls = {'kingdom':'K', 'superkingdom':'D','phylum':'P','class':'C','order':'O','family':'F','genus':'G','species':'S'}
    count_samples = 0
    num_samples = len(args.r_files)
    sample_names = args.s_names
    root_node = -1
    prev_node = -1
    curr_node = -1
    u_reads = {0:0}
    total_reads = {0:0}
    taxid2node = {}

    #Check input values
    if len(sample_names) > 0 and len(sample_names) != num_samples:
        sys.stderr.write("Number of sample names provided does not match number of reports\n")
        sys.exit(1)
    #Map names
    id2names = {}
    id2files = {}
    if len(sample_names) == 0:
        for i in range(num_samples):
            id2names[i+1] = "S" + str(i+1)
            id2files[i+1] = ""
    else:
        for i in range(num_samples):
            id2names[i+1] = sample_names[i]
            id2files[i+1] = ""

    #################################################
    #STEP 1: READ IN REPORTS
    #Iterate through reports and make combined tree!
    sys.stdout.write(">>STEP 1: READING REPORTS\n")
    sys.stdout.write("\t%i/%i samples processed" % (count_samples, num_samples))
    sys.stdout.flush()
    for r_file in args.r_files:
        count_samples += 1
        sys.stdout.write("\r\t%i/%i samples processed" % (count_samples, num_samples))
        sys.stdout.flush()
        id2files[count_samples] = r_file
        #Open File
        curr_file = open(r_file,'r')
        for line in curr_file:
            report_vals = process_kraken_report(line)
            if len(report_vals) < 5:
                continue
            [name, taxid, level_num, level_id, all_reads, level_reads] = report_vals
            if level_id in map_lvls:
                level_id = map_lvls[level_id]
            #Total reads
            total_reads[0] += level_reads
            total_reads[count_samples] = level_reads
            #Unclassified
            if level_id == 'U' or taxid == '0':
                u_reads[0] += level_reads
                u_reads[count_samples] = level_reads
                continue
            #Tree Root
            if taxid == '1':
                if count_samples == 1:
                    root_node = Tree(name, taxid, level_num, 'R', 0,0)
                    taxid2node[taxid] = root_node
                root_node.add_reads(count_samples, all_reads, level_reads)
                prev_node = root_node
                continue
            #Move to correct parent
            while level_num != (prev_node.level_num + 1):
                prev_node = prev_node.parent
            #IF NODE EXISTS
            if taxid in taxid2node:
                taxid2node[taxid].add_reads(count_samples, all_reads, level_reads)
                prev_node = taxid2node[taxid]
                continue
            #OTHERWISE
            #Determine correct level ID
            if level_id == '-' or len(level_id)> 1:
                if prev_node.level_id in main_lvls:
                    level_id = prev_node.level_id + '1'
                else:
                    num = int(prev_node.level_id[-1]) + 1
                    level_id = prev_node.level_id[:-1] + str(num)
            #Add node to tree
            curr_node = Tree(name, taxid, level_num, level_id, 0, 0, None, prev_node)
            curr_node.add_reads(count_samples, all_reads, level_reads)
            taxid2node[taxid] = curr_node
            prev_node.add_child(curr_node)
            prev_node = curr_node
        curr_file.close()

    sys.stdout.write("\r\t%i/%i samples processed\n" % (count_samples, num_samples))
    sys.stdout.flush()

    #################################################
    #STEP 2: SETUP OUTPUT FILE
    sys.stdout.write(">>STEP 2: WRITING NEW REPORT HEADERS\n")
    o_file = open(args.output,'w')
    #Lines mapping sample ids to filenames
    if args.headers:
        o_file.write("#Number of Samples: %i\n" % num_samples)
        o_file.write("#Total Number of Reads: %i\n" % total_reads[0])
        for i in id2names:
            o_file.write("#")
            o_file.write("%s\t" % id2names[i])
            o_file.write("%s\n" % id2files[i])
        #Report columns
        o_file.write("#perc\ttot_all\ttot_lvl")
        if not args.c_only:
            for i in id2names:
                o_file.write("\t%s_all" % i)
                o_file.write("\t%s_lvl" % i)
        o_file.write("\tlvl_type\ttaxid\tname\n")
    #################################################
    #STEP 3: PRINT TREE
    sys.stdout.write(">>STEP 3: PRINTING REPORT\n")
    #Print line for unclassified reads
    o_file.write("%0.4f\t" % (float(u_reads[0])/float(total_reads[0])*100))
    for i in u_reads:
        if i == 0 or (i > 0 and not args.c_only):
            o_file.write("%i\t" % u_reads[i])
            o_file.write("%i\t" % u_reads[i])
    o_file.write("U\t0\tunclassified\n")
    #Print for all remaining reads
    all_nodes = [root_node]
    curr_node = -1
    curr_lvl = 0
    prev_node = -1
    while len(all_nodes) > 0:
        #Remove node and insert children
        curr_node = all_nodes.pop()
        if len(curr_node.children) > 0:
            curr_node.children.sort()
            for node in curr_node.children:
                all_nodes.append(node)
        #Print information for this node
        o_file.write("%0.4f\t" % (float(curr_node.tot_all)/float(total_reads[0])*100))
        o_file.write("%i\t" % curr_node.tot_all)
        o_file.write("%i\t" % curr_node.tot_lvl)
        if not args.c_only:
            for i in range(num_samples):
                if (i+1) not in curr_node.all_reads:
                    o_file.write("0\t0\t")
                else:
                    o_file.write("%i\t" % curr_node.all_reads[i+1])
                    o_file.write("%i\t" % curr_node.lvl_reads[i+1])
        o_file.write("%s\t" % curr_node.level_id)
        o_file.write("%s\t" % curr_node.taxid)
        o_file.write(" "*curr_node.level_num*2)
        o_file.write("%s\n" % curr_node.name)
    o_file.close()
####################################################################
if __name__ == "__main__":
    main()
```

## 2. extract_kraken_reads.py

```python
#!/usr/bin/env python
######################################################################
#extract_kraken_reads.py takes in a kraken-style output and kraken report
#and a taxonomy level to extract reads matching that level
#Copyright (C) 2019-2020 Jennifer Lu, jennifer.lu717@gmail.com
#
#This file is part of KrakenTools
#KrakenTools is free software; oyu can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation; either version 3 of the license, or
#(at your option) any later version.
#
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License
#along with this program; if not, see <http://www.gnu.org/licenses/>.
#
######################################################################
#Jennifer Lu, jlu26@jhmi.edu
#Updated: 06/03/2019
#
#This program extracts reads classified by Kraken as a
#specified taxonomy ID. Those reads are extracted into a new FASTA file.
#
#Required Parameters:
#   -k, --kraken, --kraken-file X.......kraken output file
#   -s, -s1, -1, -U X...................read file
#                                       [FASTA/FASTQ - may be gzipped]
#   -s2, -2, X..........................second read file if paired
#                                       [FASTA/FASTQ - may be gzipped]
#   -o, --output X......................output FASTA file with reads
#   -t, --taxid, --taxids X.............list of taxonomy IDs to extract
#                                       [separated by spaces]
#   -r, --report-file X.................kraken report file
#                                       [required only with --include-children/parents]
#Optional Parameters:
#   -h, --help..........................show help message.
#   --max X.............................only save the first X reads found
#   --include-children **...............include reads classified at lower levels
#   --include-parents **................include reads classified at parent levels
#                                       of taxids
#   --append............................append extracted reads to output file if existing
#   --noappend..........................rewrite file if existing [default]
#   --exclude...........................exclude the taxids specified
# ** by default, only reads classified exactly at taxids provided will be extracted
# ** if either of these are specified, a report file must also be provided
######################################################################
import os, sys, argparse
import gzip
from time import gmtime
from time import strftime
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
#################################################################################
#Tree Class
#usage: tree node used in constructing taxonomy tree
#   includes only taxonomy levels and genomes identified in the Kraken report
class Tree(object):
    'Tree node.'
    def __init__(self, taxid, level_num, level_id, children=None, parent=None):
        self.taxid = taxid
        self.level_num = level_num
        self.level_id = level_id
        self.children = []
        self.parent = parent
        if children is not None:
            for child in children:
                self.add_child(child)
    def add_child(self, node):
        assert isinstance(node,Tree)
        self.children.append(node)
#################################################################################
#process_kraken_output
#usage: parses single line from kraken output and returns taxonomy ID and readID
#input: kraken output file with readid and taxid in the
#   second and third tab-delimited columns
#returns:
#   - taxonomy ID
#   - read ID
def process_kraken_output(kraken_line):
    l_vals = kraken_line.split('\t')
    if len(l_vals) < 5:
        return [-1, '']
    if "taxid" in l_vals[2]:
        temp = l_vals[2].split("taxid ")[-1]
        tax_id = temp[:-1]
    else:
        tax_id = l_vals[2]

    read_id = l_vals[1]
    if (tax_id == 'A'):
        tax_id = 81077
    else:
        tax_id = int(tax_id)
    return [tax_id, read_id]

#process_kraken_report
#usage: parses single line from report output and returns taxID, levelID
#input: kraken report file with the following tab delimited lines
#   - percent of total reads
#   - number of reads (including at lower levels)
#   - number of reads (only at this level)
#   - taxonomy classification of level
#       (U, - (root), - (cellular org), D, P, C, O, F, G, S)
#   - taxonomy ID (0 = unclassified, 1 = root, 2 = Bacteria...etc)
#   - spaces + name
#returns:
#   - taxonomy ID
#   - level number (number of spaces before name)
#   - level_type (type of taxonomy level - U, R, D, P, C, O, F, G, S, etc)
def process_kraken_report(report_line):
    l_vals = report_line.strip().split('\t')
    if len(l_vals) < 5:
        return []
    try:
        int(l_vals[1])
    except ValueError:
        return []
    #Extract relevant information
    try:
        taxid = int(l_vals[-3])
        level_type = l_vals[-2]
        map_kuniq = {'species':'S', 'genus':'G','family':'F',
            'order':'O','class':'C','phylum':'P','superkingdom':'D',
            'kingdom':'K'}
        if level_type not in map_kuniq:
            level_type = '-'
        else:
            level_type = map_kuniq[level_type]
    except ValueError:
        taxid = int(l_vals[-2])
        level_type = l_vals[-3]
    #Get spaces to determine level num
    spaces = 0
    for char in l_vals[-1]:
        if char == ' ':
            spaces += 1
        else:
            break
    level_num = int(spaces/2)
    return[taxid, level_num, level_type]
################################################################################
#Main method
def main():
    #Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('-k', dest='kraken_file', required=True,
        help='Kraken output file to parse')
    parser.add_argument('-s','-s1', '-1', '-U', dest='seq_file1', required=True,
        help='FASTA/FASTQ File containing the raw sequence letters.')
    parser.add_argument('-s2', '-2', dest='seq_file2', default= "",
        help='2nd FASTA/FASTQ File containing the raw sequence letters (paired).')
    parser.add_argument('-t', "--taxid",dest='taxid', required=True,
        nargs='+',
        help='Taxonomy ID[s] of reads to extract (space-delimited)')
    parser.add_argument('-o', "--output",dest='output_file', required=True,
        help='Output FASTA/Q file containing the reads and sample IDs')
    parser.add_argument('-o2',"--output2", dest='output_file2', required=False, default='',
        help='Output FASTA/Q file containig the second pair of reads [required for paired input]')
    parser.add_argument('--append', dest='append', action='store_true',
        help='Append the sequences to the end of the output FASTA file specified.')
    parser.add_argument('--noappend', dest='append', action='store_false',
        help='Create a new FASTA file containing sample sequences and IDs \
              (rewrite if existing) [default].')
    parser.add_argument('--max', dest='max_reads', required=False,
        default=100000000, type=int,
        help='Maximum number of reads to save [default: 100,000,000]')
    parser.add_argument('-r','--report',dest='report_file', required=False,
        default="",
        help='Kraken report file. [required only if --include-parents/children \
        is specified]')
    parser.add_argument('--include-parents',dest="parents", required=False,
        action='store_true',default=False,
        help='Include reads classified at parent levels of the specified taxids')
    parser.add_argument('--include-children',dest='children', required=False,
        action='store_true',default=False,
        help='Include reads classified more specifically than the specified taxids')
    parser.add_argument('--exclude', dest='exclude', required=False,
        action='store_true',default=False,
        help='Instead of finding reads matching specified taxids, finds all reads NOT matching specified taxids')
    parser.add_argument('--fastq-output', dest='fastq_out', required=False,
        action='store_true',default=False,
        help='Print output FASTQ reads [requires input FASTQ, default: output is FASTA]')
    parser.set_defaults(append=False)

    args=parser.parse_args()

    #Start Program
    time = strftime("%m-%d-%Y %H:%M:%S", gmtime())
    sys.stdout.write("PROGRAM START TIME: " + time + '\n')

    #Check input
    if (len(args.output_file2) == 0) and (len(args.seq_file2) > 0):
        sys.stderr.write("Must specify second output file -o2 for paired input\n")
        sys.exit(1)

    #Initialize taxids
    save_taxids = {}
    for tid in args.taxid:
        save_taxids[int(tid)] = 0
    main_lvls = ['R','K','D','P','C','O','F','G','S']

    #STEP 0: READ IN REPORT FILE AND GET ALL TAXIDS
    if args.parents or args.children:
        #check that report file exists
        if args.report_file == "":
            sys.stderr.write(">> ERROR: --report not specified.")
            sys.exit(1)
        sys.stdout.write(">> STEP 0: PARSING REPORT FILE %s\n" % args.report_file)
        #create tree and save nodes with taxids in the list
        base_nodes = {}
        r_file = open(args.report_file,'r')
        prev_node = -1
        for line in r_file:
            #extract values
            report_vals = process_kraken_report(line)
            if len(report_vals) == 0:
                continue
            [taxid, level_num, level_id] = report_vals
            if taxid == 0:
                continue
            #tree root
            if taxid == 1:
                level_id = 'R'
                root_node = Tree(taxid, level_num, level_id)
                prev_node = root_node
                #save if needed
                if taxid in save_taxids:
                    base_nodes[taxid] = root_node
                continue
            #move to correct parent
            while level_num != (prev_node.level_num + 1):
                prev_node = prev_node.parent
            #determine correct level ID
            if level_id == '-' or len(level_id) > 1:
                if prev_node.level_id in main_lvls:
                    level_id = prev_node.level_id + '1'
                else:
                    num = int(prev_node.level_id[-1]) + 1
                    level_id = prev_node.level_id[:-1] + str(num)
            #make node
            curr_node = Tree(taxid, level_num, level_id, None, prev_node)
            prev_node.add_child(curr_node)
            prev_node = curr_node
            #save if taxid matches
            if taxid in save_taxids:
                base_nodes[taxid] = curr_node
        r_file.close()
        #FOR SAVING PARENTS
        if args.parents:
            #For each node saved, traverse up the tree and save each taxid
            for tid in base_nodes:
                curr_node = base_nodes[tid]
                while curr_node.parent != None:
                    curr_node = curr_node.parent
                    save_taxids[curr_node.taxid] = 0
        #FOR SAVING CHILDREN
        if args.children:
            for tid in base_nodes:
                curr_nodes = base_nodes[tid].children
                while len(curr_nodes) > 0:
                    #For this node
                    curr_n = curr_nodes.pop()
                    if curr_n.taxid not in save_taxids:
                        save_taxids[curr_n.taxid] = 0
                    #Add all children
                    if curr_n.children != None:
                        for child in curr_n.children:
                            curr_nodes.append(child)

    ##############################################################################
    sys.stdout.write("\t%i taxonomy IDs to parse\n" % len(save_taxids))
    sys.stdout.write(">> STEP 1: PARSING KRAKEN FILE FOR READIDS %s\n" % args.kraken_file)
    #Initialize values
    count_kraken = 0
    read_line = -1
    exclude_taxids = {}
    if args.exclude:
        exclude_taxids = save_taxids
        save_taxids = {}
    #PROCESS KRAKEN FILE FOR CLASSIFIED READ IDS
    k_file = open(args.kraken_file, 'r')
    sys.stdout.write('\t0 reads processed')
    sys.stdout.flush()
    #Evaluate each sample in the kraken file
    save_readids = {}
    save_readids2 = {}
    for line in k_file:
        count_kraken += 1
        if (count_kraken % 10000 == 0):
            sys.stdout.write('\r\t%0.2f million reads processed' % float(count_kraken/1000000.))
            sys.stdout.flush()
        #Parse line for results
        [tax_id, read_id] = process_kraken_output(line)
        if tax_id == -1:
            continue
        #Skip if reads are human/artificial/synthetic
        if (tax_id in save_taxids) and not args.exclude:
            save_taxids[tax_id] += 1
            save_readids2[read_id] = 0
            save_readids[read_id] = 0
        elif (tax_id not in exclude_taxids) and args.exclude:
            if tax_id not in save_taxids:
                save_taxids[tax_id] = 1
            else:
                save_taxids[tax_id] += 1
            save_readids2[read_id] = 0
            save_readids[read_id] = 0
        if len(save_readids) >= args.max_reads:
            break
    #Update user
    k_file.close()
    sys.stdout.write('\r\t%0.2f million reads processed\n' % float(count_kraken/1000000.))
    sys.stdout.write('\t%i read IDs saved\n' % len(save_readids))
    ##############################################################################
    #Sequence files
    seq_file1 = args.seq_file1
    seq_file2 = args.seq_file2
    ####TEST IF INPUT IS FASTA OR FASTQ
    if(seq_file1[-3:] == '.gz'):
        s_file1 = gzip.open(seq_file1,'rt')
    else:
        s_file1 = open(seq_file1,'rt')
    first = s_file1.readline()
    if len(first) == 0:
        sys.stderr.write("ERROR: sequence file's first line is blank\n")
        sys.exit(1)
    if first[0] == ">":
        filetype = "fasta"
    elif first[0] == "@":
        filetype = "fastq"
    else:
        sys.stderr.write("ERROR: sequence file must be FASTA or FASTQ\n")
        sys.exit(1)
    s_file1.close()
    if filetype != 'fastq' and args.fastq_out:
        sys.stderr.write('ERROR: for FASTQ output, input file must be FASTQ\n')
        sys.exit(1)
    ####ACTUALLY OPEN FILE
    if(seq_file1[-3:] == '.gz'):
        #Zipped Sequence Files
        s_file1 = gzip.open(seq_file1,'rt')
        if len(seq_file2) > 0:
            s_file2 = gzip.open(seq_file2,'rt')
    else:
        s_file1 = open(seq_file1, 'r')
        if len(seq_file2) > 0:
            s_file2 = open(seq_file2, 'r')
    #PROCESS INPUT FILE AND SAVE FASTA FILE
    sys.stdout.write(">> STEP 2: READING SEQUENCE FILES AND WRITING READS\n")
    sys.stdout.write('\t0 read IDs found (0 mill reads processed)')
    sys.stdout.flush()
    #Open output file
    if (args.append):
        o_file = open(args.output_file, 'a')
        if args.output_file2 != '':
            o_file2 = open(args.output_file2, 'a')
    else:
        o_file = open(args.output_file, 'w')
        if args.output_file2 != '':
            o_file2 = open(args.output_file2, 'w')
    #Process SEQUENCE 1 file
    count_seqs = 0
    count_output = 0
    for record in SeqIO.parse(s_file1,filetype):
        count_seqs += 1
        #Print update
        if (count_seqs % 1000 == 0):
            sys.stdout.write('\r\t%i read IDs found (%0.2f mill reads processed)' % (count_output, float(count_seqs/1000000.)))
            sys.stdout.flush()
        #Check ID
        test_id = str(record.id)
        test_id2 = test_id
        if ("/1" in test_id) or ("/2" in test_id):
            test_id2 = test_id[:-2]
        #Sequence found
        if test_id in save_readids or test_id2 in save_readids:
            count_output += 1
            #Print update
            sys.stdout.write('\r\t%i read IDs found (%0.2f mill reads processed)' % (count_output, float(count_seqs/1000000.)))
            sys.stdout.flush()
            #Save to file
            if args.fastq_out:
                SeqIO.write(record, o_file, "fastq")
            else:
                SeqIO.write(record, o_file, "fasta")
        #If no more reads to find
        if len(save_readids) == count_output:
            break
    #Close files
    s_file1.close()
    o_file.close()
    sys.stdout.write('\r\t%i read IDs found (%0.2f mill reads processed)\n' % (count_output, float(count_seqs/1000000.)))
    sys.stdout.flush()
    if len(seq_file2) > 0:
        count_output = 0
        count_seqs = 0
        sys.stdout.write('\t%i read IDs found (%0.2f mill reads processed)' % (count_output, float(count_seqs/1000000.)))
        sys.stdout.flush()
        for record in SeqIO.parse(s_file2, filetype):
            count_seqs += 1
            #Print update
            if (count_seqs % 1000 == 0):
                sys.stdout.write('\r\t%i read IDs found (%0.2f mill reads processed)' % (count_output, float(count_seqs/1000000.)))
                sys.stdout.flush()
            test_id = str(record.id)
            test_id2 = test_id
            if ("/1" in test_id) or ("/2" in test_id):
                test_id2 = test_id[:-2]
            #Sequence found
            if test_id in save_readids or test_id2 in save_readids:
                count_output += 1
                sys.stdout.write('\r\t%i read IDs found (%0.2f mill reads processed)' % (count_output, float(count_seqs/1000000.)))
                sys.stdout.flush()
                #Save to file
                if args.fastq_out:
                    SeqIO.write(record, o_file2, "fastq")
                else:
                    SeqIO.write(record, o_file2, "fasta")
            #If no more reads to find
            if len(save_readids) == count_output:
                break
        s_file2.close()
        o_file2.close()
        #End Program
        sys.stdout.write('\r\t%i read IDs found (%0.2f mill reads processed)\n' % (count_output, float(count_seqs/1000000.)))

    #End Program
    sys.stdout.write('\t' + str(count_output) + ' reads printed to file\n')
    sys.stdout.write('\tGenerated file: %s\n' % args.output_file)
    if args.output_file2 != '':
        sys.stdout.write('\tGenerated file: %s\n' % args.output_file2)

    #End of program
    time = strftime("%m-%d-%Y %H:%M:%S", gmtime())
    sys.stdout.write("PROGRAM END TIME: " + time + '\n')
    sys.exit(0)

#################################################################################

if __name__ == "__main__":
    main()

#################################################################################
#################################END OF PROGRAM##################################
#################################################################################