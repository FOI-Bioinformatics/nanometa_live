import os
import pandas as pd

def get_fastp_df(fastp_file):
    """
    Creates a dataframe from the cumulative fastp file.
    If no fastp file has been produced, it returns a placeholder.
    """
    # checks if the data has been created
    if os.path.isfile(fastp_file): 
        # creates the df
        fastp_df = pd.read_csv(fastp_file, names=['passed_filter_reads', 'low_quality_reads', 'too_many_N_reads', 'too_short_reads'])  
    else: # if no data: creates empty placeholder df
        fastp_df = pd.DataFrame(columns=['passed_filter_reads', 'low_quality_reads', 'too_many_N_reads', 'too_short_reads'])
        fastp_df.loc[len(fastp_df.index)] = [0,0,0,0] 
    
    # create cumulative columns
    fastp_df['cum_passed_filter_reads'] = fastp_df['passed_filter_reads'].cumsum()
    fastp_df['cum_low_quality_reads'] = fastp_df['low_quality_reads'].cumsum()  
    fastp_df['cum_too_many_N_reads'] = fastp_df['too_many_N_reads'].cumsum()  
    fastp_df['cum_too_short_reads'] = fastp_df['too_short_reads'].cumsum()  
        
    return fastp_df
