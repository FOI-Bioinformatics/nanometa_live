

"""
organizes the data to plotly sankey plot format


"""

import plotly.graph_objects as go

def format_sankey(top_df,
                  label,
                  pad=25,
                  thickness=10
                  ):
    
    link = dict(source = top_df[top_df.columns[0]].values.tolist(),
                target = top_df[top_df.columns[1]].values.tolist(), 
                value = top_df[top_df.columns[2]].values.tolist())
    
    node = dict(label = label, pad=25, thickness=10)  
    
    sankey_data = go.Sankey(link = link, node=node)
    return sankey_data

# call
#sankey_data = format_sankey(edges=, label=)