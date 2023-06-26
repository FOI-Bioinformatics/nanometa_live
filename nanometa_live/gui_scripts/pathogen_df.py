import pandas as pd
import math

def pathogen_df(pathogen_list, raw_df): 
    """
    Creates a df of data on specified pathogens from config list.
    """
    
    # df makes layout much easier
    pathogen_info = pd.DataFrame(columns= ['Name', 
                                           'Tax ID',
                                           'Reads', 
                                           'Percent reads', 
                                           'log10(Reads)'])
    # iterates through the list of tax IDs
    for entry in pathogen_list: 
        # compares each pathogen against IDs in kreport
        for i in range(raw_df.shape[0]): 
            # if there is a match
            if entry == raw_df.iloc[i,4]: 
                # handle zero values for log function
                if raw_df.iloc[i,2] == 0: 
                    log10reads = 0 # set it to 0
                else: # get the log of the reads for danger meter
                    log10reads = math.log(raw_df.iloc[i,2],10)
                # add the species to the results df.
                pathogen_info.loc[len(pathogen_info.index)] = [raw_df.iloc[i,5], # add pathogen name 
                                                               raw_df.iloc[i,4], # add pathogen taxID
                                                               raw_df.iloc[i,2], # add pathogen nr of reads
                                                               raw_df.iloc[i,0], # add percent reads for pathogens
                                                               log10reads] # log value for the danger meter
    return pathogen_info
