
'''
A list that defines which taxonomic hierarchies are to be included.
The letters and hierarchies can be specified in the config file.
Returns the hierarchy list and the reversed hierarcy list needed for processing.

'''

def tax_hierarchy_list(hierarchy_letters):
    reversed_hierarchy_letters = hierarchy_letters[::-1]
    return hierarchy_letters, reversed_hierarchy_letters
