import numpy as np

def get_rev_matrix(d_filt_df): 
    """
    Creates a reversed matrix from the domain filtered df
    in order to parse through the list 
    starting with lowest tax level and assigning it to the corresponding 
    parent clade.
    """
    rev_df = d_filt_df.iloc[::-1] # reverses the df
    # adds the data needed
    names = rev_df[rev_df.columns[5]].values.tolist()
    tax_rankings = rev_df[rev_df.columns[3]].values.tolist()
    read_nrs = rev_df[rev_df.columns[1]].values.tolist()
    # creates a reversed matrix with names, tax letters and read nrs
    rev_matrix = np.column_stack((names, tax_rankings, read_nrs)) 
    return rev_matrix
