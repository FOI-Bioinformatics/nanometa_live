
import json
import sys

# Reading in the file names from the terminal argunments.
in_file = sys.argv[1]
out_file = sys.argv[2]

#print(in_file)
#print(out_file)

# parse out the info
with open(in_file, 'r') as inF:
    filter_data = json.load(inF)
    passed_filter_reads = filter_data.get("filtering_result", {}).get("passed_filter_reads", 0)
    low_quality_reads = filter_data.get("filtering_result", {}).get("low_quality_reads", 0)
    too_many_N_reads = filter_data.get("filtering_result", {}).get("too_many_N_reads", 0)
    too_short_reads = filter_data.get("filtering_result", {}).get("too_short_reads", 0)

# saves the info in a txt/csv file
with open(out_file, 'w') as outF: 
    csv_row = str(passed_filter_reads) + ',' + str(low_quality_reads) + ',' + str(too_many_N_reads) + ',' + str(too_short_reads) + '\n'
    outF.write(csv_row)
