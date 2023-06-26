import plotly.graph_objects as go
import yaml
import math

def create_gauge(value = 0): # value = highest log10 reads
    """
    Creates a plotly gauge from a float; a species of interests log10 read value.
    Coloring: yellow = warning, red = danger.
    Ranges adjustable in config file.
    """
    # load config file contents
    with open('config.yaml', 'r')as cf:
        config_content = yaml.safe_load(cf)
        
    # defining color ranges of the graph:
    # if any species have reads above Warning Lower Limit: yellow
    # (numbers transformed into log10 values for visualization) 
    wll = math.log(config_content['warning_lower_limit'], 10)
    # if any species have reads above Danger Lower Limit: red
    dll = math.log(config_content['danger_lower_limit'], 10)
    # create the gauge
    fig = go.Figure(go.Indicator(
        domain = {'x': [0, 1], 'y': [0, 1]},
        value = value, # this is your input
        mode = "gauge",
        title = {'text': "Pathogenicity level"},
        gauge = {'bar': {'color': "black"},
                 'axis': {'range': [None, 3]},
                 # defines coloring by value
                 'steps' : [{'range': [0, wll], 'color': "green"}, 
                            {'range': [wll, dll], 'color': "yellow"},
                            {'range': [dll, 3], 'color': "red"}] 
                }
        ))
        
    return fig
