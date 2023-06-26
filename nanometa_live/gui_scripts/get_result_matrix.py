import numpy as np

def get_result_matrix(d_filt_df, tax_letters):
    """
    Uses the domain filtered kraken df and selected tax letters to 
    create a matrix and a dictionary to be used in further data processing.
    The node IDs need to be created here, before the entries are filtered,
    since the nodes are all ordered by tax hierarchy in this matrix.
    This way the label parameter of the sankey plot will have the correct
    order of node numberings.
    """
    # a counter to number the nodes
    node_nr = 0 
    # list for node names; taxon names. Will become 'label' parameter
    names = [] 
    # list where the node nr will be stored as node id
    node_ids = []
    # using specified tax letters
    tax_rankings = []
    # for later sorting by reads
    read_nrs = []
    # important dictionary to be used later to map taxon names to node ids
    node_id_dict = {}
    # parse through each tax letter, 
    # ordering the df in nodes, domains to the right with the lowest nrs, 
    # going down the clades and assigning higher node nrs to ensure that 
    # each sub-level has a higher nr than its parent
    for letter in tax_letters: 
        # parse through df
        for i in range(d_filt_df.shape[0]): 
            # if it matches current tax letter
            if d_filt_df.iloc[i, 3] == letter: 
                # add name of taxon/node
                name = d_filt_df.iloc[i, 5] 
                # add node id
                node_id = node_nr 
                # add tax letter
                tax_ranking = d_filt_df.iloc[i, 3] 
                # add nr of reads
                nr_reads = d_filt_df.iloc[i, 1]
                # append the stuff to the lists
                names.append(name)
                node_ids.append(node_id)
                tax_rankings.append(tax_ranking)
                read_nrs.append(nr_reads)
                # append the taxon name and node id to dict
                node_id_dict[name] = node_nr
                # add one to the counter to number the next node
                node_nr += 1 
    # create a matrix with the nodes/entries ordered with each higher 
    # clade having a lower node id
    result_matrix = np.array([names, node_ids, tax_rankings, read_nrs]) 
    result_matrix = np.transpose(result_matrix)
    return result_matrix, node_id_dict
