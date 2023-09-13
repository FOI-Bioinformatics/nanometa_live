import plotly.graph_objects as go
import yaml
import math
import os

def create_gauge(value = 0, config_file_path='config.yaml'): # value = highest log10 reads
    """
    Creates a plotly gauge from a float; a species of interests log10 read value.
    Coloring: yellow = warning, red = danger.
    Ranges adjustable in config file.
    """

    # Check if the config file exists
    if not os.path.exists(config_file_path):
        print(f"Error: Config file '{config_file_path}' not found.")
        return None

    # Load config file variables
    try:
        with open(config_file_path, 'r') as cf:
            config_content = yaml.safe_load(cf)
    except Exception as e:
        print(f"Error: An issue occurred while reading the config file. Details: {e}")
        return None

        
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
