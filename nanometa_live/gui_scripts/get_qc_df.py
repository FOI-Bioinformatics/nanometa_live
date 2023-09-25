import os
import pandas as pd

def get_qc_df(qc_file):
    """
    Creates a dataframe from the cumulative qc file (qc_data/cumul_qc.txt).
    If no qc file has been produced, it returns a placeholder.
    """
    # checks if the data has been created
    if os.path.isfile(qc_file): 
        # creates the df
        qc_df = pd.read_csv(qc_file, names=['Time', 'Reads', 'Bp']) 
        # sorts the df by time
        qc_df = qc_df.sort_values(by=['Time'], ascending=True) 
    else: # if no data: creates empty placeholder df
        qc_df = pd.DataFrame(columns=['Time', 'Reads', 'Bp'])
        qc_df.loc[len(qc_df.index)] = ['2023-09-25 00:00:00.0',0,0]
    
    # create cumulative reads
    qc_df['Cumulative reads'] = qc_df['Reads'].cumsum() 
    # create cumulative bp
    qc_df['Cumulative bp'] = qc_df['Bp'].cumsum() 
    
    return qc_df

