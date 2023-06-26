import pandas as pd
import numpy as np

def create_edges(rev_matrix, id_dict, rev_letters):
    '''
    Creates edges between all nodes.
    Returns it as a pandas df.

    Only user designated tax levels are kept.
    Each lower clade is assigned to its corresponding closest parent clade
    to make the lineage work with any possible combination of tax levels.    
    '''
        
    # create a scoring dictionary for the tax letters
    scoring_dict = {}
    score = 0
    for letter in rev_letters:
        scoring_dict[letter] = score
        score += 1
    #print(scoring_dict)
    
    # filter the reversed matrix to only keep the desigated levels
    mask = np.isin(rev_matrix[:, 1], rev_letters)
    filtered_matrix = rev_matrix[mask]
    #print(filtered_matrix)
    
    # lists
    source = []
    target = []
    value = []
    rank = []
    
    # for each included tax letter
    for i in range(len(rev_letters)):
        #print('CURRENT:', rev_letters[i])
        # if you reach the root clade, stop. 
        # it will be included anyway since its target will refer to it
        if rev_letters[i] == rev_letters[-1]: 
            #print(rev_letters[i] + ' reached -- done')
            break
        else:  # for all other clade letters
            # parse through the rev matrix 
            for j in range(filtered_matrix.shape[0]):
                # if you find the current tax letter
                if filtered_matrix[j, 1] == rev_letters[i]:
                    #print(filtered_matrix[j, 1], 'found:')
                    #print(filtered_matrix[j, 0])
                    # search on from that point
                    for entry in filtered_matrix[j+1:,:]:
                        # the first following entry with a tax score higher than
                        # the current one, is assigned parent
                        if scoring_dict[entry[1]] > scoring_dict[rev_letters[i]]:
                            #print(entry[0], '- PARENT TO ', filtered_matrix[j, 0], 'found.')
                            source.append(int(id_dict[entry[0]]))# source = name of parent converted to node id
                            target.append(int(id_dict[filtered_matrix[j, 0]]))# target = name of current converted to node id
                            value.append(int(filtered_matrix[j, 2]))# add nr of reads for current
                            rank.append(filtered_matrix[j, 1])# tax rank letter of current
                            break
    # initiates the df
    edges_df = pd.DataFrame({'source':source, 'target':target, 'value':value,'rank':rank})
    #print(edges_df)
    return edges_df
