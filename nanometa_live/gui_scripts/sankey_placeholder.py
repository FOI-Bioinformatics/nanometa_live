"""
Creates placeholder sankey data to display before kraken data starts coming in.

"""

import plotly.graph_objects as go

def sankey_placeholder():
    # the values 
    placeholder_link = dict(source = [0], 
                            target = [1],
                            value = [1])
    # placeholder node
    placeholder_node = dict(label = ["Waiting for data"], 
                            pad=25, 
                            thickness=10) 
    # sankey data object
    placeholder_data = go.Sankey(link=placeholder_link, node=placeholder_node)
    
    return placeholder_data