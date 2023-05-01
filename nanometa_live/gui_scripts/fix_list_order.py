"""
Orders the list coming in from the user settings tax letter checkboxes,
using the correct order from the config file.
"""

def fix_list_order(real_list, wrong_list):
    # this will be the proper list
    fixed_list = []
    # parses through each letter in the config list
    for i in real_list:
        # if the letter is in the checkbox list
        if i in wrong_list:
            # include it in the list to use
            fixed_list.append(i)
    return fixed_list
