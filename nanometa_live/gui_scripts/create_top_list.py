import sys 
import os

# make sure the custom packages are found
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from nanometa_live.gui_scripts.domain_filtering import domain_filtering
import pandas as pd

def create_top_list(raw_df, domains, keep_letters, top = 15):
    """
    Creates a top list of taxa with the most reads.
    Domains and clades can be filtered.
    Info comes from the callback: user settings.
    """
    # Disables the SettingWithCopyWarning from pandas
    pd.options.mode.chained_assignment = None
    
    # Filter raw df by domains.
    d_filt_df2 = domain_filtering(raw_df, domains)
    # Taxonomy/clade filtering. Simply keep the user specified ones.
    t_filt_df = d_filt_df2[d_filt_df2['rank'].isin(keep_letters)]
    # Sort in descending order of reads.
    o_t_filt_df = t_filt_df.sort_values('reads', ascending=False)
    # Keep the entries with the top x reads.
    top_t_filt_df = o_t_filt_df[0:top]
    # Add an index to the df. (Disabled Pandas warning originates here.)
    top_t_filt_df['Index'] = range(1, len(top_t_filt_df) + 1)
    # Reorganizes the columns of the df and renames them for layout.
    reorg_df = top_t_filt_df[['Index','name','id','rank','reads']]    
    reorg_df.columns = ["Index","Name", "Tax ID", "Tax Rank","Reads"]
    return reorg_df
    
