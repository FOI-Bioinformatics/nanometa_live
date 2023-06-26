import pandas as pd
#from collections import Counter

def filter_by_top(top,
                  edges_df,
                  result_matrix,
                  tax_letters,
                  rev_tax_letters
                  ):
    """
    Filters the edge df by top entries, determined by nr of reads.
    Organizes the data as nodes and egdes for sankey plotting.
    Adds the correct parents to each node depending on the user specified
    tax levels.
    Adds "ghost nodes" to the end of clades which do not have complete
    lineage ending at the lowest specified tax level.
    """                
    
    ##### this part determines the node IDs of the domains
    
    # transform to df for ease of parsing
    # this df is filtered by tax letters
    result_df = pd.DataFrame(data = result_matrix, 
                             columns =['name','nodeId','rank','readNrs']) 
    
    # finds the rows containing the highest tax level included in tax letters
    highest_clades = result_df.loc[result_df['rank'] == tax_letters[0]]
    #print(highest_clades)
    # extracts the node IDs for the highest clades
    clade_list = highest_clades[highest_clades.columns[1]].values.tolist()
    # transforms them to integers
    clade_list = [ int(x) for x in clade_list ]
    #print(clade_list)
    
    # initialize empty top filtered df
    top_df = pd.DataFrame(columns = ['source', 'target', 'value','rank'])
    #top_df.loc[0] = [-1,-1,-1,'z']
    #print(top_df)
    
    ##### now we find the top x taxa for each level
    
    # parse through chosen letters backwards
    #ghost_nr = 0
    for letter in rev_tax_letters:
        #print('\nCURRENT LETTER: '+letter)
        # creates a temporary df 
        # this df needs to be nullified for every letter
        temp_df = pd.DataFrame(columns = ['source', 'target', 'value','rank'])
        # parses through edges df
        # edges df is already filtered by tax letters
        for i in range(edges_df.shape[0]):
            # if the rank of the entry is current letter
            if edges_df.iloc[i,3] == letter:
                #print(edges_df.iloc[i,3], '-', edges_df.iloc[i,1])
                #print(edges_df.iloc[i,])
                # add it to the temp df
                temp_df.loc[len(temp_df.index)] = [edges_df.iloc[i,0], # source 
                                                   edges_df.iloc[i,1], # target
                                                   edges_df.iloc[i,2], # value
                                                   edges_df.iloc[i,3]] # rank
        # after it has collected the entire group of that letter
        # sort in descending order
        temp_df = temp_df.sort_values('value', ascending=False)
        # keep the top x
        temp_df = temp_df[0:top]
        #target_list = temp_df["target"].values.tolist()
        #print('TARGET LIST = ', target_list)
        #print('temp_df:\n', temp_df)
        
        # concat to the top filtered df
        top_df = pd.concat([top_df, temp_df])
        # drop duplicates: we keep only the ones not already in the df
        #print('top_df:\n', top_df)
        #n_duplicates = top_df.duplicated().sum()
        #print('DUPLICATES:', n_duplicates)
        top_df = top_df.drop_duplicates()
        #print('top_df:\n', top_df) # no highest clade present in edges df
        
        ##### then we add parents immedately
        
        stop_list = [0]
        # keeps parsing until stop list has no entries
        while len(stop_list) != 0:
            # put all targets in a list
            check_list = top_df[top_df.columns[1]].values.tolist()
            #print('stop_list_len:', len(stop_list))
            # empties the stop list
            stop_list = []
            # parses through top_df
            for i in range(top_df.shape[0]):
                # if the entry belongs to the highest clade, it is skipped
                # the highest clade does not need to be in the target list
                if top_df.iloc[i,0] not in clade_list:
                    # if the source ID is not already in targets
                    if top_df.iloc[i,0] not in check_list:
                        # extract the source ID
                        stop_list.append(top_df.iloc[i,0])
                        #print(top_df.iloc[i,0])
                        # find the entry where the current source is the target in edges df
                        row_to_add = edges_df.loc[edges_df['target'] == top_df.iloc[i,0]]
                        # add it to the top df
                        top_df = pd.concat([top_df, row_to_add])
                else: # if entry is a highest clade, it is skipped
                    continue
        #print('ADDING PARENTS')
        #print(top_df)    
        #ghost_nr += 1
        
    ##### now we need to add ghost nodes for all lineages not
    ##### ending on the lowest included tax level
    
    # extract the source nodes
    complete_source_list = top_df["source"].values.tolist() 
    ghost_dict = {}
    ghost_score = 0
    # assigns scores for the number of ghost nodes needed to be
    # created depending on the tax level
    for letter in rev_tax_letters:
        ghost_dict[letter] =ghost_score
        ghost_score += 1
    #print(complete_source_list)
    ghost_nodes = 0
    # where the numbering of new ghost nodes should begin
    ghost_id_nr = result_matrix.shape[0]
    #print(ghost_id_start, type(ghost_id_start), '!!!!!!!!!!!!!')
    # temp df for ghost nodes
    ghost_temp = pd.DataFrame(columns = ['source', 'target', 'value','rank'])
    # parse through top df
    for i in range(top_df.shape[0]):
        if top_df.iloc[i,3] != rev_tax_letters[0]:
            # if a match is found that is not in the source list,
            # meaning it is not a source to any lower node
            #print('not end node met!', top_df.iloc[i,1])
            if top_df.iloc[i,1] not in complete_source_list:
                #print('both criteria met:', top_df.iloc[i,1])
                # create ghost nodes 
                new_row = {'source': top_df.iloc[i,1], 'target': ghost_id_nr, 'value': 1, 'rank': 'x'}
                ghost_temp.loc[len(ghost_temp)] = new_row
                ghost_id_nr += 1
                # keep track of the number of added ghost nodes
                ghost_nodes += 1
                # varying numbers of ghost nodes need to be created
                for j in range(int(ghost_dict[top_df.iloc[i,3]])-1):
                    new_row = {'source': ghost_id_nr-1, 'target': ghost_id_nr, 'value': 1, 'rank': 'x'}
                    ghost_temp.loc[len(ghost_temp)] = new_row
                    ghost_id_nr += 1
                    ghost_nodes += 1
    # add the ghost nodes to the df
    top_df = pd.concat([top_df, ghost_temp])
    #top_df.drop(0)
    #print('FINAL\n', top_df)
    #print('ghost nodes:', ghost_nodes)
    #col_list = top_df["target"].values.tolist()
    #d = Counter(col_list)
    #repeated_list = list([num for num in d if d[num]>1])
    #print("Duplicate integers: ",repeated_list)
    return top_df, ghost_nodes
