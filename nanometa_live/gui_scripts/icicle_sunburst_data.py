from nanometa_live.gui_scripts.domain_filtering import domain_filtering
from nanometa_live.gui_scripts.icicle_sunburst_matrix import icicle_sunburst_matrix
from nanometa_live.gui_scripts.get_icicle_data import get_icicle_data
import yaml
import os

def icicle_sunburst_data(raw_df, domains, count = 10, config_file_path='config.yaml'):
    """
    Creates the data in the format needed for plotly sunsickle charts.
    Data format for sunburst and icicle is identical.
    """
    
    # Check if the config file exists
    if not os.path.exists(config_file_path):
        print(f"Error: Config file '{config_file_path}' not found.")
        return None

    # Load config file variables
    try:
        with open(config_file_path, 'r') as cf:
            config_contents = yaml.safe_load(cf)
    except Exception as e:
        print(f"Error: An issue occurred while reading the config file. Details: {e}")
        return None

    # Gets the tax letters from the config file.
    config_letters = config_contents['taxonomic_hierarchy_letters']
    
    # Filters by domain.
    d_filt_df = domain_filtering(raw_df, domains)
    # Filters by lowest count to be kept.
    c_filt_df = d_filt_df[d_filt_df.iloc[:,1] > count]
    # Creates a reversed matrix for ease of parsing the kreport structure.
    filt_rev_matrix = icicle_sunburst_matrix(c_filt_df)
    # The lists needed for plotly.
    #print(filt_rev_matrix)
    # This sorts the kreport data in taxon lineages, assigning
    # parents to each taxon depending on designated tax letters.
    Taxon, Parent, Reads = get_icicle_data(filt_rev_matrix, config_letters)
    # The plotly data format.
    ice_sun_data = dict(Taxon=Taxon, Parent=Parent, Reads=Reads)
    return ice_sun_data
