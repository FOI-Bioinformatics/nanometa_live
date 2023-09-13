import os
import pandas as pd

def validation_col(validation_list, blast_dir, read_nr_list):
    """
    Finds the blast results for each species of interes ID found in the kreport.
    Adds the results from the files to a list that is then made a column
    in the pathogen df.
    """
    validated_col = []
    # validation_list = the subset of species of interest actually found in the data
    counter = 0
    for i in validation_list:
        #print('now we are working on', i)
        #print('counter is ', counter)
        # create path
        if read_nr_list[counter] == 0:
            #print('reads for ', i,'is',read_nr_list[counter])
            validated_col.append(0)
            #print('the value 0 has been added to entry',  i)
            counter += 1
            break
        #print('entry', i, 'has', read_nr_list[counter], 'nr of reads')
        file_name = str(i) + '.txt'
        path = os.path.join(blast_dir, file_name)
        #print(path)
        if os.path.isfile(path): # if file exists
            #print('path exists')
            # import data
            val_df = pd.read_csv(path, sep='\t', header=None)
            #print(val_df)
            #print(val_df.iloc[:,0])
            # extract nr of unique sequences. Many sequences will have several matches 
            # on the genome
            unique_seqs = val_df.iloc[:,0].nunique()
            #print(unique_seqs)
            #print(unique_seqs)
            # add nr to column
            validated_col.append(unique_seqs)
            #print(validated_col)
        else: # if the correct file is not found
            validated_col.append(0)
        counter += 1
    
    return validated_col
