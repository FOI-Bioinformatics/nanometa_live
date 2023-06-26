import pandas as pd

def kreport2_df(kreport_file):
    """
    Imports kreport2 file and creates a pd dataframe.
    """
    raw_kraken_df = pd.read_csv(kreport_file,
                                sep = '\t',
                                # removes spaces in col 5
                                skipinitialspace = True, 
                                header=None
                                )
    return raw_kraken_df
