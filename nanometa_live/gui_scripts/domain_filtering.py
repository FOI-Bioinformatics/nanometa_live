
"""
Filters the raw kreport df by user chosen domains.

"""

import pandas as pd

def domain_filtering(raw_df, # full data
                     selected_domains # by domain name: Bacteria etc
                     ): 
    # adding col names for ease of parsing
    raw_df.columns = ['%',
                      'cuml_reads',
                      'reads',
                      'rank',
                      'id',
                      'name'] 
    
    all_domains = ['Bacteria', # these will never change
                   'Archaea', 
                   'Eukaryota', 
                   'Viruses'] 
     
    domain_start = []
    
    # parses through all domains
    for i in all_domains: 
        #print('domain in all domains:', i)
        # finds the row with the domain entry
        start_row = raw_df.loc[raw_df['name'] == i] 
        #print('domain start row:\n', start_row) 
        # gets the index of that row
        start_index = start_row.index.values.tolist() 
        #print('domain start index:\n', start_index)
        # if domain exists in kreport
        if len(start_index) != 0: 
            # add domain start index
            domain_start.append(start_index[0]) 
        else: # if domain does not exist in kreport: ex no viruses 
            domain_start.append(-1) # append -1


    #print(all_domains)
    #print(domain_start)
    
    # create a df of the domain start indexes and names
    domain_df = pd.DataFrame(list(zip(all_domains, domain_start))) 
    domain_df.columns = ['name', 'start']
    # sort by index in order of which comes first in list
    domain_df = domain_df.sort_values('start') 
    # remove domains not in kreport
    domain_df.drop(domain_df[domain_df['start'] == -1].index, inplace = True) 
    
    #print(domain_df)
    
    domain_ranges = []
    
    # parse through all domains existing in the kreport
    for i in range(domain_df.shape[0]): 
        # in every entry but the last
        if i+1 < domain_df.shape[0]:  
            # add the start index and the stop index (start index of next domain)
            domain_ranges.append([domain_df.iloc[i,1], domain_df.iloc[i+1,1]]) 
            #print(domain_df.iloc[i,1], domain_df.iloc[i+1,1])
        else: # for the last entry
            # add the domain start index and make the end index the last row of the kreport. 
            # This will include "other sequences" etc but it is irrelevant since they are not 
            # included in the clade list
            domain_ranges.append([domain_df.iloc[i,1], len(raw_df)]) 
            #print(domain_df.iloc[i,1])
    
    # add the domain ranges to the df
    domain_df['index_ranges'] = domain_ranges        
    #print(domain_df)   

    temp_lists = []
    
    # parse through all domains
    for i in range(domain_df.shape[0]): 
        #print(i)
        #print(domain_df.iloc[i,0])
        # if the domain is in selected list
        if domain_df.iloc[i,0] in selected_domains:
             # adds all rows between domain start and domain end indexes
            temp_lists.append([i for i in range(domain_df.iloc[i,2][0], domain_df.iloc[i,2][1])])
            #print(domain_df.iloc[i,2][0], domain_df.iloc[i,2][1])
    
    # make it all into one list
    flat_list = [item for sublist in temp_lists for item in sublist] 
    #print(flat_list)
    
    # filter the raw df by the index list
    filt_df = raw_df[raw_df.index.isin(flat_list)] 
        
    return filt_df