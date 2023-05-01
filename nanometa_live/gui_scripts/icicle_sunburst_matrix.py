"""
Creates a reversed matrix for sunsickle organizing.
A reversed matrix makes parsing easier since the kreport is
structured in a tree-like hierachical fashion.

"""
import numpy as np

def icicle_sunburst_matrix(c_filt_df): 
    rev_df = c_filt_df.iloc[::-1] # reverses the df
    # adds the data needed
    names = rev_df[rev_df.columns[5]].values.tolist()
    ids = rev_df[rev_df.columns[4]].values.tolist()
    tax_rankings = rev_df[rev_df.columns[3]].values.tolist()
    read_nrs = rev_df[rev_df.columns[2]].values.tolist()
    # creates a reversed matrix with names, tax letters and read nrs
    rev_matrix = np.column_stack((names, ids, tax_rankings, read_nrs)) 
    return rev_matrix