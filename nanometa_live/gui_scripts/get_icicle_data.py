import numpy as np

def get_icicle_data(filt_rev_matrix, config_letters):
    """
    Organizes the data in the format needed for sunsickle charts.
    Organizes the taxon lineages by assigning parents to 
    each taxon depending on which tax levels are included by the user.
    """
    Taxon = []
    Tax_ID = []
    Parent = []
    Reads = []
    # reverse the taxonomy letters
    rev_config_letters = config_letters[::-1]
    #print(rev_config_letters)
    
    # create a scoring dictionary for the rev tax letters
    scoring_dict = {}
    score = 0
    for letter in rev_config_letters:
        scoring_dict[letter] = score
        score += 1
    #print(scoring_dict)
    
    # updating of changed variable name instead of changing in script below
    rev_matrix = filt_rev_matrix
    #print(rev_matrix)
    # filter the reversed matrix to only keep the desigated levels
    mask = np.isin(rev_matrix[:, 2], rev_config_letters)
    filt_rev_matrix = rev_matrix[mask]
    #print(filt_rev_matrix)
    
    # go through each tax letter backwards
    for i in range(len(rev_config_letters)):
        #print('\n-----> current letter:', rev_config_letters[i])
        # when the final letter is reached (highest tax level)
        if rev_config_letters[i] == rev_config_letters[-1]:
            # parse through reversed matrix
            for j in range(filt_rev_matrix.shape[0]):
                # when a matching clade is found
                if filt_rev_matrix[j,2] == rev_config_letters[i]:
                    #print(filt_rev_matrix[j,0], 'assigned root - reads:', filt_rev_matrix[j,3])
                    # append the info. This is an inofficial end node
                    Taxon.append(filt_rev_matrix[j,0])
                    Tax_ID.append(filt_rev_matrix[j,1])
                    Parent.append("root")
                    read = int(filt_rev_matrix[j,3])
                    #print(read, type(read))
                    Reads.append(read)                    
        else: # until the highest tax level is reached
            for j in range(filt_rev_matrix.shape[0]):
                # parse through reversed matrix
                if filt_rev_matrix[j,2] == rev_config_letters[i]:
                    # if a match is found for the current tax letter,
                    # append the info
                    #print(filt_rev_matrix[j,2], '-', filt_rev_matrix[j,0])
                    Taxon.append(filt_rev_matrix[j,0])
                    Tax_ID.append(filt_rev_matrix[j,1])
                    read = int(filt_rev_matrix[j,3])
                    #print(read, type(read))
                    Reads.append(read)
                    for entry in filt_rev_matrix[j+1:,:]: 
                        # the first following entry with a tax score higher than
                        # the current one, is assigned parent
                        if scoring_dict[entry[2]] > scoring_dict[rev_config_letters[i]]:
                            #print('PARENT:', entry[2], '-', entry[0])
                            Parent.append(entry[0])
                            break
    # add the functional end node (needed by plotly)
    Taxon.append('root')
    Tax_ID.append('none')
    Parent.append("")
    Reads.append(0)
    return Taxon, Parent, Reads
