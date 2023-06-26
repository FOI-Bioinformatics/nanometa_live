import os
import pandas as pd

def validation_col(validation_list, blast_dir):
    """
    Finds the blast results for each species of interes ID found in the kreport.
    Adds the results from the files to a list that is then made a column
    in the pathogen df.
    """
    validated_col = []
    # validation_list = the subset of species of interest actually found in the data
    for i in validation_list:
        # create path
        file_name = str(i) + '.txt'
        path = os.path.join(blast_dir, file_name)
        #print(path)
        if os.path.isfile(path): # if file exists
            #print('path exists')
            # import data
            val_df = pd.read_csv(path, sep='\t', header=None)
            #print(val_df.iloc[:,0])
            # extract nr of unique sequences. Many sequences will have several matches 
            # on the genome
            unique_seqs = val_df.iloc[:,0].nunique()
            #print(unique_seqs)
            # add nr to column
            validated_col.append(unique_seqs)
        else: # if the correct file is not found
            validated_col.append(0)
    
    return validated_col
