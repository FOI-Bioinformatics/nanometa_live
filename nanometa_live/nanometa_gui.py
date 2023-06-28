'''
This is the main script that runs the GUI.

It imports most functions from external scripts in the gui_scripts
directory. There are some functions that are included in this script,
since there has not been time yet to work them into external scipts.

Initial variables, such as paths and placeholders for the layout, are
specified in the beginning of the script.

There are some inconsistencies in how the layout is structured using 
dash, daq and dbc objects where it seemed most convenient.

The callback functions mostly call external funcions, but here as well
some smaller functions remain in the callbacks themselves.
'''

########## DASH PACKAGES ######################################################
from dash import Dash, html, dcc, Output, Input, State, dash_table
import dash_daq as daq
import dash_bootstrap_components as dbc

########## PLOTLY PACKAGES ####################################################
import plotly.graph_objects as go
import plotly.express as px

########## OTHER PACKAGES #####################################################
import numpy as np
import pandas as pd
import os
import yaml
import sys
import argparse

########## CUSTOM SCRIPTS #####################################################

# Makes sure the custom scripts are found after install.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from nanometa_live.gui_scripts.get_time import get_time
from nanometa_live.gui_scripts.sankey_placeholder import sankey_placeholder
from nanometa_live.gui_scripts.kreport2_df import kreport2_df
from nanometa_live.gui_scripts.tax_hierarchy_list import tax_hierarchy_list
from nanometa_live.gui_scripts.get_result_matrix import get_result_matrix
from nanometa_live.gui_scripts.get_rev_matrix import get_rev_matrix
from nanometa_live.gui_scripts.create_edges import create_edges
from nanometa_live.gui_scripts.filter_by_top import filter_by_top
from nanometa_live.gui_scripts.format_sankey import format_sankey
from nanometa_live.gui_scripts.pathogen_df import pathogen_df
from nanometa_live.gui_scripts.create_gauge import create_gauge
from nanometa_live.gui_scripts.domain_filtering import domain_filtering
from nanometa_live.gui_scripts.get_qc_df import get_qc_df
from nanometa_live.gui_scripts.fix_list_order import fix_list_order
from nanometa_live.gui_scripts.create_top_list import create_top_list
from nanometa_live.gui_scripts.icicle_sunburst_data import icicle_sunburst_data
from nanometa_live.gui_scripts.validation_col import validation_col

########## --help argument ####################################################
# Checks if the user has added the --help argument to the command and 
# displays the help info if that is the case. Otherwise, script proceeds
# as normal.

# Parses command-line arguments
parser = argparse.ArgumentParser(description='Runs the Nanometa Live GUI.')
parser.add_argument('-help', action='store_true', help='Displays help message')

args = parser.parse_args()

if args.help:
    parser.print_help()

########## VARIOUS FUNCTIONS ##################################################

# Some functions that are, for different reasons, not suitable to 
# be external scripts.

def sankey_fig_layout():
    '''
    Defines layout for the sankey plot.
    '''
    sankey_fig.update_traces(selector=dict(type='sankey'),
                             orientation='h', # horizontal plot
                             arrangement='freeform', # nodes moveable by user
                             textfont_size=12
                             )
    # The sizes might need to be adjusted depending on platform/screen size.
    sankey_fig.update_layout({'autosize': False}, # autolayout off!
                             width=1700,
                             height=800,
                             margin=dict(t=20, l=20, b=20, r=50)
                             )
    
def gauge_layout():
    '''
    Defines layout for the pathogen danger gauge.
    Some problems still remain with the autolayout here,
    because the graph is displayed in a container where 
    the size is determined by the other objects in the container.
    '''
    gauge_fig.update_layout({'autosize': False}, # autolayout off!
                            width=400,
                            height=300,
                            margin=dict(t=10, l=10, b=10, r=10)
                            )
 
def create_sankey_data(selected_domains, clade_list, top_filter = 5):
    '''
    Main script for sankey data processing and raw data updating.
    (The raw data updating should ideally be made a separate function that
    all the plots and things call, but it can't since it needs to be
    linked to a callback to be interval triggered.)  
    '''
    
    # Updates the global variable for use in other functions.
    # raw_df is the imported cumulative kreport file.
    global raw_df 
    if update_disabled == False: # if True: raw_df is not updated
        while not os.path.isfile(kreport_file): # if there are no data files yet
            return placeholder_data # returns a placeholder (defined below)
            break
        # Imports the latest kreport as a df if update is on.
        # kreport file path specified at the start of script.
        raw_df = kreport2_df(kreport_file) 
    # Jumps directly to filtering if update is not on.
    # Keeps only the domains specified by the user checkboxes.
    d_filt_df = domain_filtering(raw_df, selected_domains)
    
    # Designated tax hierarchy from config file, selection by checkboxes.
    # A list and a reversed list needed for further functions.
    tax_letters, rev_tax_letters = tax_hierarchy_list(clade_list) 
    
    # Next, the entire domain-filtered df is organized and each node is 
    # numbered to facilitate the sankey layout.
    # A dict is created to later map taxon names to node ids.
    result_matrix, id_dict = get_result_matrix(d_filt_df, tax_letters)
    
    # Creates a reversed matrix to assign parent clades. 
    # Not filtered by tax letters.
    rev_matrix = get_rev_matrix(d_filt_df) 
    
    # Create edges for sankey. Filters the domain-filtered df by tax letters.
    edges_df = create_edges(rev_matrix, id_dict, rev_tax_letters)
    
    # Get the top x entries.
    # Also creates empty nodes (ghost nodes) labeled "none"
    # to fill out the columns for each tax level.
    top_df, ghost_nodes = filter_by_top(top_filter, 
                           edges_df,
                           result_matrix,
                           tax_letters,
                           rev_tax_letters)    
   
    top_df = top_df.sort_values('target', ascending=False)
    
    # Label names for sankey.
    label = result_matrix[:,0].tolist()
    # Add "none" labels for each empty node (ghost node).
    for i in range(ghost_nodes):
        label.append('none')
        
    # Format to sankey data.    
    sankey_data = format_sankey(top_df, label, pad=30)
    return sankey_data

def create_pathogen_table():
    '''
    Creates a colored table of specified pathogens.
    Ranges for coloring specifyable in config file.
    The callback functions send the variables 'data' and 'columns' here.
    '''
    # The lower read limit for when an entry is colored yellow.
    wll = str(config_contents["warning_lower_limit"])
    # The lower read limit for when an entry is colored red.
    dll = str(config_contents["danger_lower_limit"])
    # Creates the table.
    path_tabl = dash_table.DataTable(
        data = df_to_print.to_dict('records'),
        columns = [{"name": i, "id": i} for i in df_to_print.columns],
        id='pathogen_table',
        fill_width=False,
        style_data_conditional=[
            {'if': {
                'filter_query': '{Reads} >' + wll
                },
                'backgroundColor': '#fafa05'}, # yellow
            {'if': {
                'filter_query': '{Reads} >' + dll
                },
                'backgroundColor': '#fc3030'} # red
            ]
        )
    
    return path_tabl
   
def create_top_table():
    '''
    Creates the toplist table in the layout.
    '''
    top_tabl = dash_table.DataTable(
        data = top_df.to_dict('records'),
        columns = [{"name": i, "id": i} for i in top_df.columns],
        id='top_table',
        fill_width=False)
    return top_tabl

def create_icicle(ice_sun_data, height = 800):
    '''
    Creates the icicle plot fig.
    '''
    icicle_fig =px.icicle(ice_sun_data,
                          names='Taxon',
                          parents='Parent',
                          values='Reads',
                          color='Reads', 
                          color_continuous_scale='Jet'
                          )
    icicle_fig.update_traces(selector=dict(type='icicle'),
                             hovertemplate='<b>%{label} </b> <br> Reads: %{value}' # define hover data
                             )
    icicle_fig.update_layout({'autosize': False}, # autolayout off!
                             height = height,
                             width=1700,
                             margin = dict(t=50, l=25, r=25, b=25)
                             )
    return icicle_fig

def create_sunburst(ice_sun_data):
    '''
    Creates the sunburst plot fig.
    '''
    sunburst_fig =px.sunburst(ice_sun_data,
                              names='Taxon',
                              parents='Parent',
                              values='Reads',
                              color='Reads', 
                              color_continuous_scale='Jet'
                              )
    sunburst_fig.update_traces(selector=dict(type='sunburst'),
                               hovertemplate='<b>%{label} </b> <br> Reads: %{value}' # define hover data
                               )
    sunburst_fig.update_layout({'autosize': False},# autolayout off!
                               height = 900,
                               width=900,
                               margin = dict(t=50, l=25, r=25, b=25)                               
                               )
    return sunburst_fig


########## STARTUP VARIABLES ##################################################

# Main definition of the app, needed by Dash.
# Dash bootstrap components also need an external stylesheet to handle layout.
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Current version of the program.
version = '0.1.0'

# Load config file variables.
with open('config.yaml', 'r') as cf:
    config_contents = yaml.safe_load(cf)
# Create interval frequency variable.
interval_freq = config_contents['update_interval_seconds']
    
# Path to cumulative kraken report.
# Used to create the raw kraken dataframe.
kreport_file = os.path.join(config_contents["main_dir"], 'kraken_cumul/kraken_cumul_report.kreport2')

# Path to nanopore output folder.
# Taken from config.
# Used by update_waiting_files callback.
nanopore_dir = config_contents['nanopore_output_directory']

# Path to blast results.
# Used by validation in pathogen_update callback.
blast_dir = os.path.join(config_contents["main_dir"], 'blast_result_files')

# Path to file that stores cumulative QC data.
# Used by update_qc_plots callback and update_waiting_files.
qc_file = os.path.join(config_contents["main_dir"], 'qc_data/cumul_qc.txt')
# Initial qc data, if no data: creates placeholder df.
qc_df = get_qc_df(qc_file)

# Returns the current time for initial display.
# Used by update_timestamp callback.
time_token = get_time()

# Live updates on by default.
update_disabled = False

# Initial empty raw kraken placeholder dataframe.
zero_data = np.zeros((2,6)) 
raw_df = pd.DataFrame(zero_data, columns=None) 

# Initial empty pathogen list.
df_to_print = pd.DataFrame(columns= ['Name', 'Tax ID', 'Reads'])

# Initial empty top list.
top_df = pd.DataFrame(columns= ['Name', 'Tax ID', 'Reads'])

# Initial pathogen gauge while waiting for data.
gauge_fig = create_gauge()
gauge_layout()

# An empty dataframe for sankey as a placeholder until the first data is produced.
placeholder_data = sankey_placeholder()
# Initial sankey plot with placeholder while waiting for data.
sankey_fig = go.Figure(placeholder_data)
sankey_fig_layout()

# Initial tax level list before first update.
clade_list = config_contents['taxonomic_hierarchy_letters']

# Initial sunburst and icicle figs.
sunburst_fig = create_sunburst(icicle_sunburst_data(raw_df,
                                                    ['Bacteria', 
                                                     'Archaea', 
                                                     'Eukaryota', 
                                                     'Viruses'], 10)
                               )
icicle_fig = create_icicle(icicle_sunburst_data(raw_df,
                                                ['Bacteria', 
                                                 'Archaea', 
                                                 'Eukaryota', 
                                                 'Viruses'], 10)
                               )


########## LAYOUT OBJECTS #####################################################
# The layout is organized into a header section and three tabs with 
# the various information. First, the contents of the tabs is specified
# and sub-organized when needed. Then the main tabs are organized into one 
# division. Finally, the highest level of layout is defined, including the 
# tabs as one object.


###############################################################################
##### main title and info + live toggle, always at the top of GUI #############

# Main headline at the top of the page.
# Specifiable from config.
main_title = html.H1(config_contents["analysis_name"]
                     )

# Program description and version.
subtext = html.Div(['NANOMETA LIVE',
                    html.Br(),
                    'Real-time metagenomic visualization and pathogen detection.',
                    html.Br(),
                    'Version ', version]
                   )

# Toggles live updating on/off by switching the interval object on or off.
# False = live update on (interval component disabled = False).
update_toggle = daq.ToggleSwitch(id='update_toggle',
                                label='Live updating: ',
                                labelPosition='bottom',
                                value=False
                                )

# Tooltip for toggle button.
update_toggle_tooltip = dbc.Tooltip('Pause/unpause the real-time updating of the interface. The data processing pipeline will still be active in the background.', 
                                    target='update_toggle',
                                    placement='top',
                                    delay={'show': 1000})

# Displays the current status of live updating: "on"/"off".
update_status = html.Div(id='update_status',
                           style={'textAlign': 'center'}
                           )

# Displays the time when the last update happened.
timestamp = html.Div(id='timestamp',
                     style={'textAlign': 'center'},
                     children = time_token
                     )


###############################################################################
##### sankey plot with options, in tab 1 ######################################

# Sankey plot object.
sankey_plot = dcc.Graph(id='sankey_plot',
                        figure=sankey_fig,
                        style={'width': '1700px', 'height': '900px', 'margin': '5px'}
                        )

# Sankey plot filtering function headline.
filter_headline = html.Label('Filter by top reads at each taxonomic level:',
                             style={'padding-right': '10px'})

# Sankey top reads filtering value.
filter_input = dcc.Input(id='filter_value',
                         value=config_contents['default_reads_per_level'],
                         type='number'
                         )

# Tooltip for Sankey top filtering.
sankey_top_tooltip = dbc.Tooltip('For example, if set to 5, the top 5 taxa with the highest reads at each level will be included.', 
                                    target='filter_value',
                                    placement='top',
                                    delay={'show': 1000})

# Checkboxes for Sankey domain filtering.
choose_domains = html.Div(children=[
    html.Label('Domains to include in the Sankey plot:',
               style={'padding-right': '10px'}),
    dcc.Checklist(['Bacteria', 
                   'Archaea', 
                   'Eukaryota',
                   'Viruses'],
                  ['Bacteria',
                   'Archaea', 
                   'Eukaryota',
                   'Viruses'],
                  id='domains',
                  style={'display': 'inline-flex', 'flex-wrap': 'wrap'},
                  labelStyle={'padding-right': '10px'}
                  )
    ])

# Checkboxes for Sankey filtering by tax hierarchy.
# Created from the config file values.
choose_hierarchy = html.Div(children=[
    html.Label('Taxonomic levels to include in the Sankey plot:',
               style={'padding-right': '10px'}),
    dcc.Checklist(config_contents['taxonomic_hierarchy_letters'],
                  config_contents['default_hierarchy_letters'], # selected upon start
                  id='clades',
                  style={'display': 'inline-flex', 'flex-wrap': 'wrap'},
                  labelStyle={'padding-right': '10px'}
                  )
    ])

# Submit button for sankey filters.
filter_submit = html.Button(id='filter_submit', 
                            n_clicks=0, 
                            children='Filter'
                            )

# Tooltip for Sankey submit button.
sankey_button_tooltip = dbc.Tooltip('Apply your filters. Filters will also be applied automatically at each update.', 
                                    target='filter_submit',
                                    placement='top',
                                    delay={'show': 1000})

# Organization of sankey filtering into one layout object.
sankey_filtering = html.Div(
    [   
        html.Div([filter_headline, filter_input, sankey_top_tooltip], className="bg-light border"),        
        html.Div(choose_domains, className="bg-light border"),
        html.Div(choose_hierarchy, className="bg-light border"),
        html.Div([filter_submit, sankey_button_tooltip], className="bg-light border")
    ], className="hstack gap-3"
)


###############################################################################
##### pathogen detection and toplist, tab 1 ###################################

# Tab section divided into pathogen list and top list.

# Pathogen stuff.
pathogen_head = html.H2('Pathogen detection') # main headline

pathogen_gauge = dcc.Graph(id='pathogen_gauge', # danger meter
                            figure=gauge_fig
                            )

# Tooltip for pathogen gauge danger meter.
gauge_tooltip = dbc.Tooltip('The value of this meter is the 10-logarithm of the reads of the most abundant species of interest. The coloring of the meter and the list below is: yellow for warning and red for danger.', 
                                    target='pathogen_gauge',
                                    placement='top',
                                    delay={'show': 1000})

# Colored table. 
pathogen_table = dbc.Container([dbc.Label('Pathogens/species of interest'),  
                                create_pathogen_table()])

# Validation option checkbox. 
validate_option = html.Div(children=[
    html.Label('BLAST validation'),
    dcc.Checklist(['Validate'],
                  id='validate_box'
                  )
    ])

# Tooltip for validation checkbox.
validation_tooltip = dbc.Tooltip('Adds an additional column with the number of reads validated by BLAST, using a minimum percent identity of '+str(config_contents["min_perc_identity"])+' and an e-value cutoff of '+str(config_contents["e_val_cutoff"])+'. Will be added on the next update.', 
                                    target='validate_box',
                                    placement='top',
                                    delay={'show': 1000})

# The toplist.
toplist_head = html.H2('Top reads') # headline
top_list = dbc.Container([dbc.Label('Taxa with the highest number of reads.'),  
                                create_top_table()])

# Filtering functions for the toplist.
toplist_filter_head = html.Label('Number of taxa to include:',
                                 style={'padding-right': '10px'}) # headline

top_filter_val = dcc.Input(id='top_filter_val', # filter value
                         value='15',
                         type='number'
                         )

# Tooltip for top list filtering.
top_list_tooltip = dbc.Tooltip('The number of entries to include in the list.', 
                                    target='top_filter_val',
                                    placement='top',
                                    delay={'show': 1000})

# Chackboxes for Toplist domain filtering.
toplist_domains = html.Div(children=[
    html.Label('Domains to include:',
               style={'padding-right': '10px'}),
    dcc.Checklist(['Bacteria', 
                   'Archaea', 
                   'Eukaryota',
                   'Viruses'],
                  ['Bacteria',
                   'Archaea', 
                   'Eukaryota',
                   'Viruses'],
                  id='toplist_domains',
                  style={'display': 'inline-flex', 'flex-wrap': 'wrap'},
                  labelStyle={'padding-right': '10px'}
                  )
    ])

# checkboxes for Toplist filtering tax hierarchy.
# Created from the config file values.
toplist_hierarchy = html.Div(children=[
    html.Label('Taxonomic levels to include:',
               style={'padding-right': '10px'}),
    dcc.Checklist(config_contents['taxonomic_hierarchy_letters'],
                  config_contents['taxonomic_hierarchy_letters'],
                  id='toplist_clades',
                  style={'display': 'inline-flex', 'flex-wrap': 'wrap'},
                  labelStyle={'padding-right': '10px'}
                  )
    ])

# Toplist filter submit button.
toplist_submit = html.Button(id='toplist_submit', 
                            n_clicks=0, 
                            children='Filter'
                            )

# Tooltip for toplist filter submit button.
toplist_button_tooltip = dbc.Tooltip('Apply your filters. Filters will also be applied automatically at each update.', 
                                    target='toplist_submit',
                                    placement='top',
                                    delay={'show': 1000})

# Organization of toplist filtering into one layout object.
toplist_filtering = html.Div(
    [   
        html.Div([toplist_filter_head, top_filter_val, top_list_tooltip], className="bg-light border"),        
        html.Div(toplist_domains, className="bg-light border"),
        html.Div(toplist_hierarchy, className="bg-light border"),
        html.Div([toplist_submit, toplist_button_tooltip], className="bg-light border")
    ], className="vstack gap-3"
)


# Main layout for pathogen and top lists section.
pathogens_top = html.Div(
    [   
        html.Div([toplist_head,
                  top_list,
                  html.Br(),
                  toplist_filtering
                  ],
                 className="bg-light border"),
        html.Div([pathogen_head,
                  pathogen_gauge,
                  gauge_tooltip,
                  pathogen_table,
                  html.Br(),
                  validate_option, 
                  validation_tooltip
                  ],
                 className="bg-light border")
    ], className="hstack gap-3"
)


###############################################################################
##### QC, tab 3 ###############################################################

# QC headline:
qc_head = html.H2('Technical QC')

# Initial placeholder values for the qc text info.
qc_total_reads = html.Div('Total reads (after filtering):', id='qc_total_reads')
qc_classified_reads = html.Div('Classified reads:', id='qc_classified_reads')
qc_unclassified_reads = html.Div('Unclassified reads:', id='qc_unclassified_reads')
waiting_files = html.Div('Files awaiting processing:', id='waiting_files')
processed_files = html.Div('Files processed:', id='processed_files')

# Tooltip for the total reads.
total_reads_tooltip = dbc.Tooltip('The total reads are displayed here after quality filtering, hence the numbers will differ from the ones in the plots, which are the total reads produced (pre-filtering).', 
                                    target='qc_total_reads',
                                    placement='top',
                                    delay={'show': 1000})

# Initial empty placeholder plots (plotly express).
cumul_reads_fig = px.line(qc_df, x='Time', y="Cumulative reads")
cumul_bp_fig = px.line(qc_df, x='Time', y="Cumulative bp")
reads_fig = px.line(qc_df, x='Time', y="Reads")
bp_fig = px.line(qc_df, x='Time', y="Bp")

# QC plot layout: division into cols and rows, one plot each place.
qc_col_1 = html.Div(
    [   
        html.Div(dcc.Graph(id='cumul_reads_graph',
                           figure=cumul_reads_fig), 
                 className="bg-light border"),
        html.Div(dcc.Graph(id='cumul_bp_graph',
                           figure=cumul_bp_fig), 
                 className="bg-light border")
    ], className="hstack gap-3"
)

qc_col_2 = html.Div(
    [   
        html.Div(dcc.Graph(id='reads_graph',
                           figure=reads_fig), 
                 className="bg-light border"),
        html.Div(dcc.Graph(id='bp_graph',
                           figure=bp_fig), 
                 className="bg-light border")
    ], className="hstack gap-3"
)

qc_rows = html.Div(
    [   
        html.Div(qc_col_1, className="bg-light border"),
        html.Div(qc_col_2)
    ], className="vstack gap-3"    
)

# Tooltips for QC charts.
cumul_reads_graph_tooltip = dbc.Tooltip('This graph displays the reads produced by the sequencer cumulatively over time.', 
                                    target='cumul_reads_graph',
                                    placement='top',
                                    delay={'show': 1000})

cumul_bp_graph_tooltip = dbc.Tooltip('This graph displays the base pairs produced by the sequencer cumulatively over time.', 
                                    target='cumul_bp_graph',
                                    placement='top',
                                    delay={'show': 1000})

reads_graph_tooltip = dbc.Tooltip('This graph displays the reads produced in each batch by the sequencer.', 
                                    target='reads_graph',
                                    placement='top',
                                    delay={'show': 1000})

bp_graph_tooltip = dbc.Tooltip('This graph displays the base pairs produced in each batch by the sequencer.', 
                                    target='bp_graph',
                                    placement='top',
                                    delay={'show': 1000})

# Main layout for QC tab.
qc_layout = html.Div([qc_head,
                      qc_total_reads,
                      qc_classified_reads,
                      qc_unclassified_reads,
                      html.Br(),
                      waiting_files,
                      processed_files,
                      html.Hr(),
                      dbc.Container(qc_rows), # adding a container here centers the plots in the layout
                      cumul_reads_graph_tooltip,
                      cumul_bp_graph_tooltip,
                      reads_graph_tooltip,
                      bp_graph_tooltip,
                      total_reads_tooltip],
                     className="bg-light border"
                     )


###############################################################################
##### sunburst and icicle charts, tab 2 #######################################

# Sunburst plot figure.
sunburst_chart = dcc.Graph(id='sunburst_chart',
                        figure=sunburst_fig
                        )

# Tooltip for sunburst fig.
sunburst_tooltip = dbc.Tooltip('The side bar displays the coloring used to represent abundance by number of reads for each taxon', 
                                    target='sunburst_chart',
                                    placement='top',
                                    delay={'show': 1000})

# Icicle chart plot figure.
icicle_chart = dcc.Graph(id='icicle_chart',
                        figure=icicle_fig
                        )

# Tooltip for icicle fig.
icicle_tooltip = dbc.Tooltip('The side bar displays the coloring used to represent abundance by number of reads for each taxon', 
                                    target='icicle_chart',
                                    placement='top',
                                    delay={'show': 1000})

# Sunburst filtering.
sun_filter_head = html.Label('Filter by min reads:',
                             style={'padding-right': '10px'})

sun_filter_val = dcc.Input(id='sun_filter_val',
                         value='10',
                         type='number'
                         )

# Tooltip for sunburst filtering.
sunburst_filter_tooltip = dbc.Tooltip('Include only taxa with this minimum number of reads in the sunburst chart.', 
                                    target='sun_filter_val',
                                    placement='top',
                                    delay={'show': 1000})

# Sunburst domains checkboxes.
sun_domains = html.Div(children=[
    html.Label('Domains to include in the sunburst chart:',
               style={'padding-right': '10px'}),
    dcc.Checklist(['Bacteria', 
                   'Archaea', 
                   'Eukaryota',
                   'Viruses'],
                  ['Bacteria',
                   'Archaea', 
                   'Eukaryota',
                   'Viruses'],
                  id='sun_domains',
                  style={'display': 'inline-flex', 'flex-wrap': 'wrap'},
                  labelStyle={'padding-right': '10px'}
                  )
    ])

# Submit button for sunburst filters.
sun_submit = html.Button(id='sun_submit', 
                            n_clicks=0, 
                            children='Filter'
                            )

# Tooltip for sunburst submit button.
sunburst_button_tooltip = dbc.Tooltip('Apply your filters. Filters will also be applied automatically at each update.', 
                                    target='sun_submit',
                                    placement='top',
                                    delay={'show': 1000})

# Layout for sunburst filtering.
sun_filtering = html.Div(
    [   
        html.Div([sun_filter_head, sun_filter_val, sunburst_filter_tooltip], className="bg-light border"),        
        html.Div(sun_domains, className="bg-light border"),
        html.Div([sun_submit, sunburst_button_tooltip], className="bg-light border")
    ], 
    className="hstack gap-3"    
)

# Icicle filtering.
ice_filter_head = html.Label('Filter by min reads:',
                             style={'padding-right': '10px'})

ice_filter_val = dcc.Input(id='ice_filter_val',
                         value='10',
                         type='number'
                         )

# Tooltip for icicle filtering.
icicle_filter_tooltip = dbc.Tooltip('Include only taxa with this minimum number of reads in the icicle chart.', 
                                    target='ice_filter_val',
                                    placement='top',
                                    delay={'show': 1000})

# Icicle height adjustment.
ice_height_head = html.Label('Height of graph:',
                             style={'padding-right': '10px'})

ice_height = dcc.Input(id='ice_height',
                         value='800',
                         type='number'
                         )

# Tooltip for icicle height.
icicle_height_tooltip = dbc.Tooltip('Change the height of the icicle graph.', 
                                    target='ice_height',
                                    placement='top',
                                    delay={'show': 1000})

# Icicle chart domains checkboxes.
ice_domains = html.Div(children=[
    html.Label('Domains to include in the icicle chart:',
               style={'padding-right': '10px'}),
    dcc.Checklist(['Bacteria', 
                   'Archaea', 
                   'Eukaryota',
                   'Viruses'],
                  ['Bacteria',
                   'Archaea', 
                   'Eukaryota',
                   'Viruses'],
                  id='ice_domains',
                  style={'display': 'inline-flex', 'flex-wrap': 'wrap'},
                  labelStyle={'padding-right': '10px'}
                  )
    ])

# Submit button for icicle parameters.
ice_submit = html.Button(id='ice_submit', 
                            n_clicks=0, 
                            children='Filter'
                            )

# Tooltip for icicle submit button.
icicle_button_tooltip = dbc.Tooltip('Apply your filters. Filters will also be applied automatically at each update.', 
                                    target='ice_submit',
                                    placement='top',
                                    delay={'show': 1000})

# Icicle filtering layout.
ice_filtering = html.Div(
    [   
        html.Div([ice_filter_head, ice_filter_val, icicle_filter_tooltip], className="bg-light border"),        
        html.Div(ice_domains, className="bg-light border"),
        html.Div([ice_height_head, ice_height, icicle_height_tooltip], className="bg-light border"),
        html.Div([ice_submit, icicle_button_tooltip], className="bg-light border")
    ], className="hstack gap-3"
)


########## INTERVAL COMPONENT #################################################

# Interval component which controls the live update.
# When disabled = True, the updating is off.
# Interval specifiable in config. Variable defined above.
# Always keep this last in the layout list. Invisible object.
interval_component = dcc.Interval(id='interval_component',
                                  interval= interval_freq*1000, # milliseconds
                                  n_intervals=0,
                                  disabled = False
                                  )


########## LAYOUT ORGANIZATION ################################################

# Organization of layout into three tabs. 
# Wrapping things in dbc.Containers centers them and makes the layout better.
main_tabs = html.Div([
    dcc.Tabs([
        dcc.Tab(label='Main', children=[
            sankey_plot,
            dbc.Container(sankey_filtering),
            html.Br(),
            html.Hr(),
            html.Br(),
            dbc.Container(pathogens_top),
            html.Br()
        ]),
        dcc.Tab(label='Explore', children=[
            dbc.Container(sunburst_chart),
            sunburst_tooltip,
            dbc.Container(sun_filtering),
            html.Br(),
            html.Hr(),
            html.Br(),
            icicle_chart,
            icicle_tooltip,
            dbc.Container(ice_filtering),
            html.Br()
        ]),
        dcc.Tab(label='QC', children=[
            qc_layout,
            html.Br()
        ]),
    ])
])


# Highest level of layout organization. This defines the order of the
# headline, info, update toggle and tabs.
app.layout= html.Div([main_title,
                      subtext,
                      update_toggle,
                      update_toggle_tooltip,
                      update_status,
                      timestamp,
                      html.Br(),
                      main_tabs,
                      interval_component
                      ])


########## CALLBACKS FOR LIVE UPDATE ##########################################
# Callback functions define what happens in the layout objects.

# Updates the time displayed for when the latest update happened.
@app.callback(Output('timestamp', 'children'), # plain text
              Input('interval_component', 'n_intervals')) # interval
def update_timestamp(interval_trigger):
    time_token = get_time()        
    return 'Latest update: ', time_token

# Controls the live update toggle on/off and displays the current status.
@app.callback(Output('update_status', 'children'), # text info on state
              Output('interval_component', 'disabled'), # actual on/off
              Input('update_toggle', 'value')) # toggle is clicked: bool
def live_update(toggle_value):
    # update globally to not cause problems
    global update_disabled 
    update_disabled = toggle_value
    # display on/off status
    if update_disabled == False: 
        status_var = 'on'
    else:
        status_var = 'off'
    return status_var, update_disabled


########## CALLBACKS FOR SANKEY PLOT ##########################################

# Creates the sankey plot and updates it live. 
@app.callback(Output(component_id='sankey_plot', component_property='figure'),
              Input('interval_component', 'n_intervals'), # updates with interval
              Input('filter_submit', 'n_clicks'), # or with button click
              State('filter_value', 'value'),
              State('domains', 'value'),
              State('clades', 'value')) # all the filters are states until click
def update_sankey(interval_trigger, filter_click, filter_value, domains, clades):
    global sankey_fig
    real_list = config_contents['taxonomic_hierarchy_letters']
    # The clade list will reorder itself when manipulated by user.
    # This function makes sure everything is set back to the right order.
    fixed_clades = fix_list_order(real_list, clades)
    #  creates the figure
    sankey_fig = go.Figure(create_sankey_data(domains, fixed_clades, int(filter_value)))
    sankey_fig_layout()
    return sankey_fig


########## CALLBACKS FOR SUNSICKLE ############################################

# Creates the sunburst plot and updates it live 
@app.callback(Output(component_id='sunburst_chart', component_property='figure'),
              Input('interval_component', 'n_intervals'), # updates with interval
              Input('sun_submit', 'n_clicks'), # or with button click
              State('sun_filter_val', 'value'),
              State('sun_domains', 'value')) # all the filters are states until click
def update_sunburst(interval_trigger, filter_click, filter_value, domains):
    data = icicle_sunburst_data(raw_df, domains, int(filter_value))
    sunburst_fig = create_sunburst(data)
    return sunburst_fig

# creates the icicle plot and updates it live 
@app.callback(Output(component_id='icicle_chart', component_property='figure'),
              Input('interval_component', 'n_intervals'), # updates with interval
              Input('ice_submit', 'n_clicks'), # or with button click
              State('ice_height', 'value'),
              State('ice_filter_val', 'value'),
              State('ice_domains', 'value')) # all the filters are states until click
def update_icicle(interval_trigger, filter_click, height_value, filter_value, domains):
    data = icicle_sunburst_data(raw_df, domains, int(filter_value))
    icicle_fig = create_icicle(data, int(height_value))
    return icicle_fig


########## CALLBACKS FOR PATHOGEN INFO ########################################

# Pathogen detection callback: produces a colored list of 
# pre-defined species and nr of reads for them.
# Also displays a general danger meter based on the highest
# log10 value of the specified pathogens.
# If interval is disabled, it should keep the latest values.
@app.callback(Output('pathogen_gauge', 'figure'), # danger meter
              Output('pathogen_table', 'data'), # row data for table
              Output('pathogen_table', 'columns'), # specify table cols
              Input('interval_component', 'n_intervals'), # interval update
              State('validate_box', 'value') # valiaditon option 
              )
def pathogen_update(interval_trigger, val_state):
    # get the data, using the species list from config and the raw df
    pathogen_info = pathogen_df(config_contents['species_of_interest'], raw_df) 
    # log10 data column for danger meter
    graph_col = pathogen_info['log10(Reads)'] 
    # extract the pathogen with the highest nr of reads(log10)
    # display log10 reads in danger meter
    gauge_fig = create_gauge(graph_col.max()) 
    # create a df with the pathogen cols to be displayed
    df_to_print = pathogen_info[['Name', 'Tax ID', 'Reads']].copy()
    # needed since the val_state object in "none" before first click
    if val_state:
        # if validation is on
        if len(val_state) == 1: 
            # get the IDs to be validated; the ones found in the data
            validation_list = list(df_to_print.iloc[:,1])
            # get the validation data on the IDs
            validated_col = validation_col(validation_list, blast_dir)
            # add to table
            df_to_print['Validated reads'] = validated_col
    # dash handling
    data = df_to_print.to_dict('records') 
    columns = [{"name": i, "id": i} for i in df_to_print.columns]
    gauge_layout() # layout for the danger meter
    return gauge_fig, data, columns


########## CALLBACKS FOR TOP TABLE ############################################

# Creates a list of the taxa with the highest number of reads.
@app.callback(Output('top_table', 'data'), # row data for table
              Output('top_table', 'columns'), # specify table cols
              Input('interval_component', 'n_intervals'), # interval update
              Input('toplist_submit', 'n_clicks'), # or with button click
              State('toplist_domains', 'value'),
              State('toplist_clades', 'value'),
              State('top_filter_val', 'value')) 
def toplist_update(interval_trigger, click, domains, clades, top):
    top_df =  create_top_list(raw_df, domains, clades, int(top))
    data = top_df.to_dict('records') 
    columns = [{"name": i, "id": i} for i in top_df.columns]
    return data, columns


########## QC CALLBACKS #######################################################

# Displays 4 qc plots on read data over time.
# If interval is disabled, it should keep the latest values.
@app.callback(Output('cumul_reads_graph', 'figure'), # plotly express plots
              Output('cumul_bp_graph', 'figure'),
              Output('reads_graph', 'figure'),
              Output('bp_graph', 'figure'), 
              Input('interval_component', 'n_intervals')) # interval input
def update_qc_plots(interval_trigger):
    # creates df from qc file
    # qc file path specified at the start of this script
    qc_df = get_qc_df(qc_file) 
    # defines data for the 4 plots
    cumul_reads_fig = px.line(qc_df, x='Time', y="Cumulative reads")
    cumul_bp_fig = px.line(qc_df, x='Time', y="Cumulative bp")
    reads_fig = px.line(qc_df, x='Time', y="Reads")
    bp_fig = px.line(qc_df, x='Time', y="Bp")       
    return cumul_reads_fig, cumul_bp_fig, reads_fig, bp_fig

# Displays classified, unclassified and total reads from Kraken.
# If interval is disabled, it should keep the latest values.
@app.callback(Output('qc_total_reads', 'children'), # text outputs
              Output('qc_classified_reads', 'children'),
              Output('qc_unclassified_reads', 'children'), 
              Input('interval_component', 'n_intervals') # interval input
              )
def update_qc_text(interval_trigger):  
    # uses the latest raw kraken df to extract the info
    c = int(raw_df.iloc[1,1]) # nr of classified reads
    u = int(raw_df.iloc[0,1]) # nr of unclassified reads
    t = c+u # total nr of processed reads
    pc = float(round(raw_df.iloc[1,0],1)) # percent classified
    pu = float(round(raw_df.iloc[0,0],1)) # percent unclassified    
    total_reads = 'Total reads (post filtering): ' + str(t)
    classified_reads = 'Classified reads: ' + str(c) + ' (' + str(pc) + ' %)'
    unclassified_reads = 'Unclassified reads: ' + str(u) + ' (' + str(pu) + ' %)'
    return total_reads, classified_reads, unclassified_reads

# Displays the current nr of nanopore files waiting to be processed,
# and the number of processed files.
@app.callback(Output('waiting_files', 'children'), # simple text output
              Output('processed_files', 'children'),
              Input('interval_component', 'n_intervals') # triggered by interval
              )
def update_waiting_files(interval_trigger):
    # Nanopore dir specified above.
    if os.path.isdir(nanopore_dir): # check if directory exists
        # number of files nanopore has produced:
        nanop_files = os.listdir(nanopore_dir) 
        # get the number of processed files from qc data 
        qc_df_2 = get_qc_df(qc_file)
        # check if its the qc placeholder, i.e. no data yet
        if qc_df_2.iloc[0,0] == '0.0':
            files_processed = 0 # if it is, assign 0
        else: # otherwize, assign nr
            files_processed = qc_df_2.shape[0]
        
        # subtract the numbers from each other
        delta = len(nanop_files) - files_processed    
        # if delta is negative it is set to 0
        # this happens if/when there are old unremoved files hanging around
        if delta < 0:
            delta = 0
        waiting_message = "Files awaiting processing: " + str(delta)
        processed_message = "Files processed: " + str(files_processed)
    else: # if directory does not exist
        waiting_message = "Files awaiting processing: "
        processed_message = "Files processed: "
    return waiting_message, processed_message

###############################################################################
###############################################################################

def run_app():
    '''
    This is how the app runs.
    '''
    # A unique port specifiable in config.
    # Debug=True means it updates as you make changes in this script.
    app.run(debug=False, port=int(config_contents['gui_port']))
if __name__ == "__main__":
    # The run_app makes it run as an entry point (bash command).
    run_app() 
