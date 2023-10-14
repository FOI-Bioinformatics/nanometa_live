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
import dash
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
import subprocess
import shutil

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
from nanometa_live.gui_scripts.domain_filtering import domain_filtering
from nanometa_live.gui_scripts.get_qc_df import get_qc_df
from nanometa_live.gui_scripts.fix_list_order import fix_list_order
from nanometa_live.gui_scripts.create_top_list import create_top_list
from nanometa_live.gui_scripts.icicle_sunburst_data import icicle_sunburst_data
from nanometa_live.gui_scripts.validation_col import validation_col
from nanometa_live.gui_scripts.get_fastp_df import get_fastp_df

from nanometa_live import __version__

from nanometa_live.helpers.config_utils import load_config

########## --help argument ####################################################
# Checks if the user has added the --help argument to the command and
# displays the help info if that is the case. Otherwise, script proceeds
# as normal.

# Parses command-line arguments
parser = argparse.ArgumentParser(description='Runs the Nanometa Live GUI.')
parser.add_argument('--config', default='config.yaml', help='Path to the configuration file. Default is config.yaml.')
parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}',
                    help="Show the current version of the script.")
parser.add_argument('-p', '--path', default='', help="The path to the project directory.")

args = parser.parse_args()

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
                             height=900,
                             margin=dict(t=20, l=20, b=20, r=50)
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
version = __version__

config_file_path = os.path.join(args.path, args.config) if args.path else args.config

# Check if the config file exists.
if not os.path.exists(config_file_path):
    print(f"Error: Config file '{config_file_path}' not found.")
    exit(1)

# Load config file variables.
config_contents = load_config(config_file_path)

# Create interval frequency variable.
interval_freq = config_contents['update_interval_seconds']
# Create variable for pathogen coloring cutoff.
# Used in pathogen info section.
dll_2 = str(config_contents["danger_lower_limit"])

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
# Used by update_qc_plots, update_waiting_files and update_qc_text callbacks.
qc_file = os.path.join(config_contents["main_dir"], 'qc_data/cumul_qc.txt')
# Initial qc data, if no data: creates placeholder df.
qc_df = get_qc_df(qc_file)

# Path to file that stores cumulative fastp data.
# Used by update_qc_text callback.
fastp_file = os.path.join(config_contents["main_dir"], 'fastp_reports/compiled_fastp.txt')
# Initial fastp data, if no data: creates placeholder df.
fastp_df = get_fastp_df(fastp_file)

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

# Initial placeholder pathogen barchart.
pathogen_fig = px.bar(qc_df, x='Time', y="Reads")

# Initial empty top list.
top_df = pd.DataFrame(columns= ['Name', 'Tax ID', 'Reads'])

# An empty dataframe for sankey as a placeholder until the first data is produced.
placeholder_data = sankey_placeholder()
# Initial sankey plot with placeholder while waiting for data.
sankey_fig = go.Figure(placeholder_data)
sankey_fig_layout()

# Initial tax level list before first update.
clade_list = config_contents['taxonomic_hierarchy_letters']

# Initial sunburst fig.
sunburst_fig = create_sunburst(icicle_sunburst_data(raw_df,
                                                    ['Bacteria',
                                                     'Archaea',
                                                     'Eukaryota',
                                                     'Viruses'], 10, config_file_path=config_file_path)
                               )

########## LAYOUT OBJECTS #####################################################
# The layout is organized into a header section and 4 tabs with
# the various information. First, the contents of the tabs is specified
# and sub-organized when needed. Then the main tabs are organized into one
# division. Finally, the highest level of layout is defined, including the
# tabs as one object.

###############################################################################
##### main title and info + live toggle, always at the top of GUI #############

# Main headline at the top of the page.
# Specifiable from config.
main_title = html.H2(config_contents["analysis_name"])

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
update_toggle_tooltip = dbc.Tooltip('Toggle real-time interface updates on/off. \
                                    The data processing pipeline will remain active in the background.',
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

# Shutdown button for GUI/entire program.
quit_button = html.Div([
    html.Button('Shut down program', id='shutdown-button'),
    dbc.Modal([
        dbc.ModalHeader('Confirmation'),
        dbc.ModalBody('Are you sure you want to shut down the program?'),
        dbc.ModalFooter([
            dbc.Button('No', id='confirm-no-button', color='secondary'),
            dbc.Button('Yes', id='confirm-yes-button', color='danger'),
        ]),
    ], id='confirmation-modal', centered=True),
    html.Div(id='output-message'),
])

# Export kraken classification button
export_classificaion_button = html.Div([
    html.Button("Export classification report", id="export-button-1"),
    dbc.Modal([
        dbc.ModalHeader('Export classification report'),
        dbc.ModalBody([            
            dcc.Input(id='filename-input-1', type='text', placeholder='Enter a file name or path'),
            html.Div('The file will be saved as a ".kreport2" file.'),
            html.Div('If only a file name is specified, the report will be saved in "PROJECT_DIRECTORY/reports/" by default.'),
        ]),
        dbc.ModalFooter([
            dbc.Button('Save', id='save-button-1', color='success'),
        ]),
    ], id='modal-2', is_open=False),
    html.Div(id='output-message-1'),
])


# Head section in one layout object.
upper_gui_layout = html.Div(
    [
        html.Div(dbc.Container([main_title,
                  subtext]),
                  style={"margin-right": "100px"}
                  ),
        html.Div(dbc.Container([update_toggle,
                  update_toggle_tooltip,
                  update_status,
                  timestamp]),
                  style={"margin-right": "300px"}
                  ),
        html.Div(dbc.Container(quit_button)),
        html.Div(dbc.Container(export_classificaion_button))
    ], className="hstack gap-3",
    style={"display": "flex"}
)

###############################################################################
##### sankey plot with options, in tab 3 ######################################

# Sankey headline
sankey_head = html.H2('Sankey plot', className="bg-light border")

# Sankey plot object.
sankey_plot = dcc.Graph(id='sankey_plot',
                        figure=sankey_fig,
                        style={'width': '1700px', 'height': '900px', 'margin': '5px'}
                        )

sankey_info_line1 = 'This plot shows the most abundand hits in a hierarchical way. \
                              The highest taxonomic level is at the leftmost node, and the lineage \
                              can be traced through the plot to the lowest selected taxonomic level at \
                              the rightmost node.'

sankey_info_line2 = 'The plot can be filtered by how many taxa will show up at \
                              each level: if set to 5, the 5 taxa with the highest number of reads will \
                              be displayed at each level. Since the plot automatically fills in the lineage, \
                              some levels may contain more taxa than this.'

sankey_info_line3 = 'The abundance of the taxa is \
                              shown by the thickness of the edges.'

sankey_info_line4 = 'Hovering over the plot will display some icons in the top right corner of the plot. \
                              Here, the plot can be saved as a png file. The box- and lasso-select icons \
                              can be used to collapse nodes into groups. The nodes can be moved \
                              around manually if the autolayout makes the plot messy. Any modification of the nodes \
                              will be cancelled upon every update so it is best to pause the automatic updates \
                              while exploring the plot.'

sankey_info_line5 = 'Hovering over the nodes or edges will show the cumulative number \
                              of reads belonging to that node, i.e. including the number of reads total in all sub-categories \
                              below that node. The number of incoming and outgoing edges is also shown.'

sankey_info = html.Div([
    html.Div(sankey_info_line1, style={'margin-bottom': '10px'}),
    html.Div(sankey_info_line2, style={'margin-bottom': '10px'}),
    html.Div(sankey_info_line3, style={'margin-bottom': '10px'}),
    html.Div(sankey_info_line4, style={'margin-bottom': '10px'}),
    html.Div(sankey_info_line5, style={'margin-bottom': '10px'}),
])

sankey_modal = html.Div([
    html.Button('INFO/HELP', id='sankey-open-button', n_clicks=0),

    # Modal for displaying text
    dbc.Modal(
        [
            dbc.ModalHeader("Sankey plot"),
            dbc.ModalBody(sankey_info),
            dbc.ModalFooter(
                dbc.Button("Close", id="sankey-close-button", className="ml-auto")
            ),
        ],
        id="sankey-modal",
        size="lg",
        backdrop="static",
    ),
])

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
                  id='domains',
                  style={'display': 'inline-flex', 'flex-wrap': 'wrap'},
                  labelStyle={'padding-right': '10px'}
                  )
    ])

# Checkboxes for Sankey filtering by tax hierarchy.
# Created from the config file values.
choose_hierarchy = html.Div(children=[
    html.Label('Taxonomic levels to include:',
               style={'padding-right': '10px'}),
    dcc.Checklist(config_contents['taxonomic_hierarchy_letters'],
                  config_contents['default_hierarchy_letters'], # ticked upon start
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

# Organization of sankey *filtering* into one layout object.
sankey_filtering = html.Div(
    [
        html.Div(sankey_modal),
        html.Div([filter_headline, filter_input, sankey_top_tooltip], className="bg-light border"),
        html.Div(choose_domains, className="bg-light border"),
        html.Div(choose_hierarchy, className="bg-light border"),
        html.Div([filter_submit, sankey_button_tooltip], className="bg-light border")
    ], className="hstack gap-3"
)

###############################################################################
##### pathogen detection and toplist, tab 1 ###################################

# Tab section divided into pathogen list and top list.

########## Pathogen stuff ##########
pathogen_head = html.H2('Species of Interest') # main headline

# Colored table.
pathogen_table = dbc.Container([dbc.Label('Species of interest:'),
                                create_pathogen_table()])

# Validation option checkbox.
validate_option = html.Div(children=[
    html.Label('BLAST validation'),
    dcc.Checklist(['Validate'],
                  id='validate_box'
                  )
    ])

# Tooltip for validation checkbox.
validation_tooltip = dbc.Tooltip('Adds an additional column with the number of reads validated by BLAST, \
                                 using a minimum percent identity of '+str(config_contents["min_perc_identity"])+' and\
                                 an e-value cutoff of '+str(config_contents["e_val_cutoff"])+'. Will be added on the next update.',
                                    target='validate_box',
                                    placement='top',
                                    delay={'show': 1000})

# Pahogen barchart.
pathogen_fig_obj = dcc.Graph(id='pathogen_fig',
                           figure=pathogen_fig)

pathogen_info_line1 = 'This section shows the abundance of all specified pathogens/species \
of interest.'

pathogen_info_line2 = 'The barchart and list are colored, so that species with more than ' + str(dll_2) + ' reads \
show up as red.'

pathogen_info_line3 = 'The "Tax ID" column contains the taxonomic IDs from the databased used.'

pathogen_info_line4 = '"Reads" is the \
number of reads assigned to the species.'

pathogen_info_line5 = 'If "BLAST validation" is turned on, an additional column will be \
added on the next update, containing the number of reads validated by BLAST, using the following parameters:'

pathogen_info_line6 = 'Minimum percent identity: ' + str(config_contents["min_perc_identity"])

pathogen_info_line7 = 'E-value cutoff : ' + str(config_contents["e_val_cutoff"])

pathogen_info_line7b = 'Minimum percent identity: a read must match the reference sequence to at least this percentage to \
    be considered validated.'

pathogen_info_line7c = 'E-value cutoff: only reads with an e-vaule below this will be considered validated. \
    The e-value is the number of expected hits of similar quality that could be be found just by chance \
        in a given database.'

pathogen_info_line8 = 'When hovering over the plot, zooming options appear at the top right of the chart \
 using the small icons, as well as the possibility to save the chart as a png file.'

pathogen_info = html.Div([
    html.Div(pathogen_info_line1, style={'margin-bottom': '10px'}),
    html.Div(pathogen_info_line2, style={'margin-bottom': '10px'}),
    html.Div(pathogen_info_line3, style={'margin-bottom': '10px'}),
    html.Div(pathogen_info_line4, style={'margin-bottom': '10px'}),
    html.Div(pathogen_info_line5, style={'margin-bottom': '10px'}),
    html.Div(pathogen_info_line6, style={'margin-bottom': '10px'}),
    html.Div(pathogen_info_line7, style={'margin-bottom': '10px'}),
    html.Div(pathogen_info_line7b, style={'margin-bottom': '10px'}),
    html.Div(pathogen_info_line7c, style={'margin-bottom': '10px'}),
    html.Div(pathogen_info_line8, style={'margin-bottom': '10px'}),
])

pathogen_modal = html.Div([
    html.Button('INFO/HELP', id='pathogen-open-button', n_clicks=0),

    # Modal for displaying text
    dbc.Modal(
        [
            dbc.ModalHeader("Pathogen detection"),
            dbc.ModalBody(pathogen_info),
            dbc.ModalFooter(
                dbc.Button("Close", id="pathogen-close-button", className="ml-auto")
            ),
        ],
        id="pathogen-modal",
        size="lg",
        backdrop="static",
    ),
])

# Export pathogens button
export_pathogens_button = html.Div([
    html.Button("Export list", id="export-button-3"),
    dbc.Modal([
        dbc.ModalHeader('Export species of interest list'),
        dbc.ModalBody([            
            dcc.Input(id='filename-input-3', type='text', placeholder='Enter a file name or path'),
            html.Div('The file will be saved as a ".csv" file.'),
            html.Div('If only a file name is specified, the list will be saved in "PROJECT_DIRECTORY/reports/" by default.'),
        ]),
        dbc.ModalFooter([
            dbc.Button('Save', id='save-button-3', color='success'),
        ]),
    ], id='modal-4', is_open=False),
    html.Div(id='output-message-3'),
])

# Placing the INFO button and Export list button horizontally
pathogen_buttons = html.Div([pathogen_modal,
                  export_pathogens_button
                  ], className="hstack gap-3"
                  )


# Entire pathogen section in one object.
pathogen_section = html.Div(
    [
        html.Div([pathogen_head,
                  pathogen_fig_obj,
                  pathogen_table,
                  html.Br(),
                  validate_option,
                  validation_tooltip,
                  html.Br(),
                  pathogen_buttons
                  ],
                 className="bg-light border"),
    ], className="hstack gap-3"
)

########## Toplist stuff ##########
toplist_head = html.H2('Most Abundant Hits') # headline
top_list = dbc.Container([dbc.Label('This section provides a quick overview of the most abundant hits, offering you an immediate glimpse into the microbial diversity and prevalence.'),
                                create_top_table()])

# Filtering functions for the toplist.
toplist_filter_head = html.Label('Number of taxa to include:',
                                 style={'padding-right': '10px'}) # headline

top_filter_val = dcc.Input(id='top_filter_val', # filter value
                         value='60',
                         type='number'
                         )

# Tooltip for top list filtering.
top_list_tooltip = dbc.Tooltip('The number of entries to include in the list, i.e. the lenght of the list.',
                                    target='top_filter_val',
                                    placement='top',
                                    delay={'show': 1000})

# Checkboxes for Toplist domain filtering.
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

# Checkboxes for Toplist filtering tax hierarchy.
# Created from the config file values.
toplist_hierarchy = html.Div(children=[
    html.Label('Taxonomic levels to include:',
               style={'padding-right': '10px'}),
    dcc.Checklist(config_contents['taxonomic_hierarchy_letters'],
                  ['S'], # provided there is an S!
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

toplist_info_line1 = 'This section displays the taxa with the highest number of reads assigned by the classifier.'

toplist_info_line2 = 'The column "Tax ID" contains the taxonomic IDs from the database used.'

toplist_info_line3 = '"Tax Rank" shows the category the taxa belong to: S - species, G - genus, etc.'

toplist_info_line4 = 'The "Reads" column contains the reads assigned specifically \
                                  to the taxon, i.e. not cumulatively counting all reads in sub-categories.'

toplist_info_line5 = 'Using the filters, domains and taxonomic levels can be modified. The lenght of\
                                  the list can also be set.'

toplist_info = html.Div([
    html.Div(toplist_info_line1, style={'margin-bottom': '10px'}),
    html.Div(toplist_info_line2, style={'margin-bottom': '10px'}),
    html.Div(toplist_info_line3, style={'margin-bottom': '10px'}),
    html.Div(toplist_info_line4, style={'margin-bottom': '10px'}),
    html.Div(toplist_info_line5, style={'margin-bottom': '10px'}),
])

toplist_modal = html.Div([
    html.Button('INFO/HELP', id='toplist-open-button', n_clicks=0),

    # Modal for displaying text
    dbc.Modal(
        [
            dbc.ModalHeader("Most Abundant Hits"),
            dbc.ModalBody(toplist_info),
            dbc.ModalFooter(
                dbc.Button("Close", id="toplist-close-button", className="ml-auto")
            ),
        ],
        id="toplist-modal",
        size="lg",
        backdrop="static",
    ),
])

# Export toplist button
export_toplist_button = html.Div([
    html.Button("Export list", id="export-button-2"),
    dbc.Modal([
        dbc.ModalHeader('Export current list'),
        dbc.ModalBody([            
            dcc.Input(id='filename-input-2', type='text', placeholder='Enter a file name or path'),
            html.Div('The file will be saved as a ".csv" file.'),
            html.Div('If only a file name is specified, the list will be saved in "PROJECT_DIRECTORY/reports/" by default.'),
        ]),
        dbc.ModalFooter([
            dbc.Button('Save', id='save-button-2', color='success'),
        ]),
    ], id='modal-3', is_open=False),
    html.Div(id='output-message-2'),
])


# Organization of toplist filtering into one layout object.
toplist_filtering = html.Div(
    [   
        html.Br(),
        html.Div([toplist_filter_head, top_filter_val, top_list_tooltip], className="bg-light border"),
        html.Div(toplist_domains, className="bg-light border"),
        html.Div(toplist_hierarchy, className="bg-light border"),
        html.Div([toplist_submit, toplist_button_tooltip]),
        html.Hr(),
        html.Div(toplist_modal),
        html.Br(),
        html.Div(export_toplist_button)
    ], className="vstack gap-3"
)

# Organizing toplist section into rows and columns.
toplist_col_1 = html.Div([toplist_head,
                          top_list
                          ],
                          className="bg-light border")

toplist_col_2 = html.Div([toplist_filtering
                          ])

# This object contains all of the toplist section.
toplist_together = html.Div([
    html.Div(toplist_col_1, style={"align-self": "flex-start"}),
    html.Div(toplist_col_2, style={"align-self": "flex-start"})
], className="hstack gap-3")

# Main layout for pathogen AND top lists section.
pathogens_top = html.Div(
    [
        html.Div([toplist_together
                  ],
                 className="bg-light border",
                 style={"align-self": "flex-start"}),
        html.Div([pathogen_section
                  ],
                 className="bg-light border",
                 style={"align-self": "flex-start"})
    ], className="hstack gap-3",
    style={"align-self": "flex-start"}
)

# Adding margins to improve layout.
main_page_margins = {'margin': '20px'}
pathogens_top_with_margin = html.Div(pathogens_top, style=main_page_margins)

###############################################################################
##### QC, tab 2 ###############################################################

# QC headline:
qc_head = html.H2('Technical QC',className="bg-light border")

# Initial placeholder values for the qc text info.
qc_filtering_headline = html.Div('FILTERING', style={'padding-right': '10px'}, id='qc_filtering_headline')
qc_reads_pre_filtering = html.Div('Total reads pre filtering:', style={'padding-right': '10px'}, id='qc_reads_pre_filtering')

qc_reads_passed = html.Div('Reads that passed filtering:', style={'padding-right': '10px'}, id='qc_reads_passed')
qc_reads_removed = html.Div('Total reads removed:', style={'padding-right': '10px'}, id='qc_reads_removed')

qc_remove_reason = html.Div('REASONS FOR REMOVAL', style={'padding-right': '10px'}, id='qc_remove_reason')
qc_proportions_info = html.Div('(percentages of total removed reads)', style={'padding-right': '10px'}, id='qc_proportions_info')
qc_low_quality = html.Div('Too low quality:', style={'padding-right': '10px'}, id='qc_low_quality')
qc_too_short = html.Div('Too short:', style={'padding-right': '10px'}, id='qc_too_short')
qc_low_complexity = html.Div('Too low complexity:', style={'padding-right': '10px'}, id='qc_low_complexity')

qc_classification_headline = html.Div('CLASSIFICATION', style={'padding-right': '10px'}, id='qc_classification_headline')
qc_classified_reads = html.Div('Classified reads:', style={'padding-right': '10px'}, id='qc_classified_reads')
qc_unclassified_reads = html.Div('Unclassified reads:', style={'padding-right': '10px'}, id='qc_unclassified_reads')

qc_processing_headline = html.Div('FILE PROCESSING', style={'padding-right': '10px'}, id='qc_processing_headline')
waiting_files = html.Div('Files awaiting processing:', style={'padding-right': '10px'}, id='waiting_files')
processed_files = html.Div('Files processed:', style={'padding-right': '10px'}, id='processed_files')

qc_info_line1 = 'The two upper graphs show the cumulative reads and base pairs produced by the sequencer \
                           over time, using the pre-filtered data, i.e. the raw data from the sequencer.'

qc_info_line2 = 'The lower two plots show the number of reads and base pairs produced in each batch, also\
                           using the unfiltered sequencer data.'

qc_info_line3 = 'The plots can be saved as png files using the icon \
                           in the top right corner of each plot that appears when hovering over the plot.'

qc_info_line4 = 'The FILTERING info displays the total number of sequences\
                           produced, the number of passed and removed sequences, and the reasons for removal.'

qc_info_line5 = 'The filter parameters are the following:'

qc_info_line6 = '"Too low quality": removes sequences with\
                           too many unqualified bases. Bases with phred quality <15 are unqualified. Sequences \
                           with more than 40% unqualified bases are discarded.'

qc_info_line7 = '"Too short": removes sequences \
                           that are shorter than 15 bp. '

qc_info_line8 = '"Too low complexity": filters by the percentage of bases\
                           that are different from its next base. This way, sequences with long stretches of the\
                           same nucleotide are filtered out. At least 30% complexity is required.'

qc_info_line9 = 'The filtering \
                           also automatically removes adapters. '

qc_info_line10 = 'CLASSIFICATION shows the number of reads that\
                           were successfully classified.'

qc_info_line11 = 'FILE PROCESSING shows the number of batch files that have been \
                           processed and the number that still remain.'

qc_info = html.Div([
    html.Div(qc_info_line1, style={'margin-bottom': '10px'}),
    html.Div(qc_info_line2, style={'margin-bottom': '10px'}),
    html.Div(qc_info_line3, style={'margin-bottom': '10px'}),
    html.Div(qc_info_line4, style={'margin-bottom': '10px'}),
    html.Div(qc_info_line5, style={'margin-bottom': '10px'}),
    html.Div(qc_info_line6, style={'margin-bottom': '10px'}),
    html.Div(qc_info_line7, style={'margin-bottom': '10px'}),
    html.Div(qc_info_line8, style={'margin-bottom': '10px'}),
    html.Div(qc_info_line9, style={'margin-bottom': '10px'}),
    html.Div(qc_info_line10, style={'margin-bottom': '10px'}),
    html.Div(qc_info_line11, style={'margin-bottom': '10px'}),
])

qc_modal = html.Div([
    html.Button('INFO/HELP', id='qc-open-button', n_clicks=0),

    # Modal for displaying text
    dbc.Modal(
        [
            dbc.ModalHeader("Technical quality control"),
            dbc.ModalBody(qc_info),
            dbc.ModalFooter(
                dbc.Button("Close", id="qc-close-button", className="ml-auto")
            ),
        ],
        id="qc-modal",
        size="lg",
        backdrop="static",
    ),
])

# Initial empty placeholder plots (plotly express).
cumul_reads_fig = px.line(qc_df, x='Time', y="Cumulative reads")
cumul_bp_fig = px.line(qc_df, x='Time', y="Cumulative bp")
reads_fig = px.bar(qc_df, x='Time', y="Reads")
bp_fig = px.bar(qc_df, x='Time', y="Bp")

# QC plot layout: division into cols and rows, one plot each place.
qc_row_1 = html.Div(
    [
        html.Div(dcc.Graph(id='cumul_reads_graph',
                           figure=cumul_reads_fig),
                 className="bg-light border"),
        html.Div(dcc.Graph(id='cumul_bp_graph',
                           figure=cumul_bp_fig),
                 className="bg-light border")
    ], className="hstack gap-3"
)

qc_row_2 = html.Div(
    [
        html.Div(dcc.Graph(id='reads_graph',
                           figure=reads_fig),
                 className="bg-light border"),
        html.Div(dcc.Graph(id='bp_graph',
                           figure=bp_fig),
                 className="bg-light border")
    ], className="hstack gap-3"
)

# All QC figs ordered in one object.
qc_column = html.Div(
    [qc_row_1,
     qc_row_2
    ],
    className="vstack gap-3"
)

# Everything exept headline in one object.
qc_row_all = html.Div(
    [
        html.Div(html.Div([qc_filtering_headline,
                           qc_reads_pre_filtering,
                           qc_reads_passed,
                           qc_reads_removed,
                           html.Br(),
                           qc_remove_reason,
                           qc_low_quality,
                           qc_too_short,
                           qc_low_complexity,
                           html.Br(),
                           qc_proportions_info,
                           html.Hr(),
                           qc_classification_headline,
                  qc_classified_reads,
                  qc_unclassified_reads,
                  html.Hr(),
                  qc_processing_headline,
                  processed_files,
                  waiting_files,
                  html.Br(),
                  html.Hr(),
                  qc_modal
                  ]), className="bg-light border"),
        html.Div(qc_column, className="bg-light border")
    ], className="hstack gap-3"
)

# Complete QC layout in one object.
qc_layout = html.Div([html.Br(),
                      qc_head,
                      html.Br(),
                      qc_row_all])

# Adding margins for better layout.
qc_page_margins = {'margin': '20px'}
qc_with_margin = html.Div(qc_layout, style=qc_page_margins)

###############################################################################
##### sunburst chart, tab 4 #######################################

# Sunburst header
sunburst_head = html.H2('Sunburst chart', className="bg-light border")

# Sunburst plot figure.
sunburst_chart = dcc.Graph(id='sunburst_chart',
                        figure=sunburst_fig
                        )

# Sunburst filtering.
sun_filter_head = html.Label('Filter by minimum reads:',
                             style={'padding-right': '10px'})

sun_filter_val = dcc.Input(id='sun_filter_val',
                         value='10',
                         type='number'
                         )

# Tooltip for sunburst filtering.
sunburst_filter_tooltip = dbc.Tooltip('Include only taxa with at least this many reads.',
                                    target='sun_filter_val',
                                    placement='top',
                                    delay={'show': 1000})

# Sunburst domains checkboxes.
sun_domains = html.Div(children=[
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

sunburst_info_line1 = '''The sunburst chart shows a hierarchical view of the taxa. The highest
                         taxonomic level is in the center, with sub-categories extending outward.
                         '''

sunburst_info_line2 = '''The sections in the chart can be clicked to zoom in on that category.
                         At every update, the chart is returned to the standard view, so it is best to
                         pause the live updates when exploring this chart.
                         '''

sunburst_info_line3 = '''The bar on the right side
                         shows abundance by number of reads through a coloring scheme.
                         '''

sunburst_info_line4 = '''The chart can be filtered
                         by minimum reads, i.e. the number of reads required for a taxon to appear in the
                         chart.
                         '''

sunburst_info_line5 = '''Hovering over the chart will display an icon in the right upper corner
                         that enables saving the chart as a png file.
                         '''

sunburst_info = html.Div([
    html.Div(sunburst_info_line1, style={'margin-bottom': '10px'}),
    html.Div(sunburst_info_line2, style={'margin-bottom': '10px'}),
    html.Div(sunburst_info_line3, style={'margin-bottom': '10px'}),
    html.Div(sunburst_info_line4, style={'margin-bottom': '10px'}),
    html.Div(sunburst_info_line5, style={'margin-bottom': '10px'}),
])

sunburst_modal = html.Div([
    html.Button('INFO/HELP', id='sunburst-open-button', n_clicks=0),

    # Modal for displaying text
    dbc.Modal(
        [
            dbc.ModalHeader("Sunburst chart"),
            dbc.ModalBody(sunburst_info),
            dbc.ModalFooter(
                dbc.Button("Close", id="sunburst-close-button", className="ml-auto")
            ),
        ],
        id="sunburst-modal",
        size="lg",
        backdrop="static",
    ),
])

# Layout sunburst filtering plus info, one object.
sun_filtering = html.Div(
    [
        html.Div([sun_filter_head, sun_filter_val, sunburst_filter_tooltip], className="bg-light border"),
        html.Div(sun_domains, className="bg-light border"),
        html.Div([sun_submit, sunburst_button_tooltip]),
        html.Br(),
        html.Hr(),
        html.Br(),
        html.Div([sunburst_modal])
    ],
    className="vstack gap-3"
)

# All sunburst stuff in one object.
sunburst_complete = html.Div(
    [
        html.Div(sunburst_chart,
                 className="bg-light border"),
        html.Div(sun_filtering)
    ],
    className="hstack gap-3"
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

# Organization of layout into four tabs.
# Wrapping things in dbc.Containers centers them and makes the layout better(?)
main_tabs = html.Div([
    dcc.Tabs([
        dcc.Tab(label='Main', children=[
            pathogens_top_with_margin,
            html.Br()
        ]),
        dcc.Tab(label='QC', children=[
            qc_with_margin,
            html.Br(),
            html.Br(),
            html.Br()
        ]),
        dcc.Tab(label='Sankey plot', children=[
            html.Br(),
            sankey_head,
            sankey_plot,
            dbc.Container(sankey_filtering),
            html.Br(),
            html.Br(),
            html.Br()
        ]),
        dcc.Tab(label='Sunburst chart', children=[
            html.Br(),
            sunburst_head,
            sunburst_complete,
            html.Br()
        ]),

    ])
])

# Base level of layout organization. This defines the order of the
# headline, info, update toggle and tabs.
app.layout= html.Div([upper_gui_layout,
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

########## CALLBACKS FOR SUNBURST ############################################

# Creates the sunburst plot and updates it live
@app.callback(Output(component_id='sunburst_chart', component_property='figure'),
              Input('interval_component', 'n_intervals'), # updates with interval
              Input('sun_submit', 'n_clicks'), # or with button click
              State('sun_filter_val', 'value'),
              State('sun_domains', 'value')) # all the filters are states until click
def update_sunburst(interval_trigger, filter_click, filter_value, domains):
    data = icicle_sunburst_data(raw_df, domains, int(filter_value), config_file_path=config_file_path)
    sunburst_fig = create_sunburst(data)
    return sunburst_fig

########## CALLBACKS FOR PATHOGEN INFO ########################################

# Pathogen detection callback: produces a colored list of
# pre-defined species and nr of reads for them.
# Also displays a colored barchart.
# If interval is disabled, it should keep the latest values.
@app.callback(Output('pathogen_fig', 'figure'), # barchart
              Output('pathogen_table', 'data'), # row data for table
              Output('pathogen_table', 'columns'), # specify table cols
              Input('interval_component', 'n_intervals'), # interval update
              State('validate_box', 'value') # valiaditon option
              )
def pathogen_update(interval_trigger, val_state):
    global df_to_print
    # Create a dictionary to keep track of name and taxid pairs
    species_dict = {entry["taxid"]: entry["name"] for entry in config_contents['species_of_interest']}

    # Extract taxids to create the pathogen list
    pathogen_list = list(species_dict.keys())

    pathogen_info = pathogen_df(pathogen_list, raw_df)
    # Cutoff for coloring.
    dll = int(config_contents["danger_lower_limit"])
    # Deals with species of interest not present in kreport.
    for taxid in pathogen_list:
        if taxid not in pathogen_info['Tax ID'].values:
            # Use the species name from species_dict instead of 'not found in DB'
            species_name = species_dict[taxid]
            pathogen_info.loc[len(pathogen_info.index)] = [species_name,  # add pathogen name
                                                           taxid, # add pathogen taxID
                                                           0,# add pathogen nr of reads
                                                           0.0, # add percent reads for pathogens
                                                           0] # not needed anymore, remove later

    # Adding a column for the coloring sceme.
    pathogen_info['Color'] = pathogen_info['Reads'].apply(lambda x: 'Green' if x < dll else 'Red')

    # Create the barchart from the pathogen_info table.
    pathogen_barchart_fig = px.bar(pathogen_info,
                                         x='Name',
                                         y='Reads',
                                         color='Color',
                                         labels={'Reads': 'Number of Reads',
                                                 'Name': 'Species'},
                                         title='Number of reads per species of interest',
                                         color_discrete_map={'Red': 'red', 'Green': 'green'})

    # Change size of graph.
    pathogen_barchart_fig.update_layout(width=700, height=400)
    # Change width of columns.
    pathogen_barchart_fig.update_traces(width=0.4)
    # Change hover info.
    pathogen_barchart_fig.update_traces(hovertemplate='<b>%{x}</b><br>Number of Reads: %{y}',
                            hoverinfo='x+y')
    # Remove unnecessary legend.
    pathogen_barchart_fig.update_traces(showlegend=False)

    # create a df with the pathogen cols to be displayed
    df_to_print = pathogen_info[['Name', 'Tax ID', 'Reads']].copy()
    # needed since the val_state object in "none" before first click
    if val_state:
        # if validation is on
        if len(val_state) == 1:
            # get the IDs to be validated; the ones found in the data
            validation_list = list(df_to_print.iloc[:,1])
            read_nr_list = list(df_to_print.iloc[:,2])
            # get the validation data on the IDs
            validated_col = validation_col(validation_list, blast_dir, read_nr_list)
            # add to table
            df_to_print['Validated reads'] = validated_col
    # Sort according to read number.
    df_to_print = df_to_print.sort_values(by='Reads', ascending=False)
    df_to_print = df_to_print.reset_index(drop=True)
    # dash handling
    data = df_to_print.to_dict('records')
    columns = [{"name": i, "id": i} for i in df_to_print.columns]
    return pathogen_barchart_fig, data, columns

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
    global top_df
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
    # Modify time points for batches, use in barplots.
    time_for_barplots = pd.to_datetime(qc_df["Time"]).dt.strftime("%H:%M:%S")
    reads_fig = px.bar(qc_df, x=time_for_barplots, y="Reads")
    bp_fig = px.bar(qc_df, x=time_for_barplots, y="Bp")
    # Update x axis label for barcharts.
    reads_fig.update_xaxes(title_text="Batch timestamp")
    bp_fig.update_xaxes(title_text="Batch timestamp")
    # Make barcharts discrete instead of continous.
    reads_fig.update_xaxes(type='category')
    bp_fig.update_xaxes(type='category')
    # Define some size parameters.
    standard_width = 650
    standard_height = 350
    b_marg = 10
    l_marg = 10
    t_marg = 35
    r_marg = 10
    # Update the layout of all charts. Should be a separate script.
    cumul_reads_fig.update_layout(width=standard_width,
                                  height=standard_height,
                                  margin=dict(l=l_marg, r=r_marg, t=t_marg, b=b_marg),
                                  title='Cumulative reads over time'
                                  )
    cumul_bp_fig.update_layout(width=standard_width,
                               height=standard_height,
                               margin=dict(l=l_marg, r=r_marg, t=t_marg, b=b_marg),
                               title='Cumulative base pairs (bp) over time'
                               )
    reads_fig.update_layout(width=standard_width,
                            height=standard_height,
                            margin=dict(l=l_marg, r=r_marg, t=t_marg, b=b_marg),
                            title='Reads per batch'
                            )
    bp_fig.update_layout(width=standard_width,
                         height=standard_height,
                         margin=dict(l=l_marg, r=r_marg, t=t_marg, b=b_marg),
                         title='Base pairs (bp) per batch'
                         )
    return cumul_reads_fig, cumul_bp_fig, reads_fig, bp_fig

# Displays classified, unclassified and total reads from Kraken.
# Also displays filter info.
# If interval is disabled, it should keep the latest values.
@app.callback(Output('qc_classified_reads', 'children'), # text outputs
              Output('qc_unclassified_reads', 'children'),
              Output('qc_reads_pre_filtering', 'children'),
              Output('qc_reads_passed', 'children'),
              Output('qc_low_quality', 'children'),
              Output('qc_too_short', 'children'),
              Output('qc_low_complexity', 'children'),
              Output('qc_reads_removed', 'children'),
              Input('interval_component', 'n_intervals') # interval input
              )
def update_qc_text(interval_trigger):
    # uses the latest raw kraken df to extract the info
    c = int(raw_df.iloc[1,1]) # nr of classified reads
    u = int(raw_df.iloc[0,1]) # nr of unclassified reads
    t = c+u # total nr of processed reads
    pc = float(round(raw_df.iloc[1,0],1)) # percent classified
    pu = float(round(raw_df.iloc[0,0],1)) # percent unclassified
    # Define the classified info objects.
    classified_reads = 'Classified reads: ' + str(c) + ' (' + str(pc) + '%)'
    unclassified_reads = 'Unclassified reads: ' + str(u) + ' (' + str(pu) + '%)'
    # Needed to extract the number of pre-filter reads etc.
    qc_df_b = get_qc_df(qc_file)
    # Define the filter info objects.
    tot_reads_pre_filt = int(qc_df_b['Cumulative reads'].iloc[-1])
    unfiltered_reads = 'Total reads pre filtering: ' + str(tot_reads_pre_filt)
    #total_reads = 'Total reads post filtering: ' + str(t)
    #filtered_proportion = 'Reads that passed filtering: ' + str(float(round((t*100)/tot_reads_pre_filt, 1))) + ' %'
    # Define the filter setting objects.
    # Load the latest cumulative fastP info file.
    fastp_df = get_fastp_df(fastp_file)
    # Create info variables.
    tot_passed_reads = int(fastp_df['cum_passed_filter_reads'].iloc[-1])
    tot_low_quality_reads = int(fastp_df['cum_low_quality_reads'].iloc[-1])
    tot_too_many_N_reads = int(fastp_df['cum_too_many_N_reads'].iloc[-1])
    tot_too_short_reads = int(fastp_df['cum_too_short_reads'].iloc[-1])

    tot_removed_reads = tot_low_quality_reads + tot_too_many_N_reads + tot_too_short_reads

    # avoid div by zero error
    if tot_reads_pre_filt == 0:
        percentage_passed_reads = 0.0
        percentage_reads_removed = 0.0
    else:
        percentage_passed_reads = float(round((tot_passed_reads*100)/tot_reads_pre_filt, 1))
        percentage_reads_removed = float(round((tot_removed_reads*100)/tot_reads_pre_filt, 1))

    if tot_removed_reads == 0:
        percentage_low_quality = 0.0
        percentage_low_complexity = 0.0
        percentage_too_short = 0.0
    else:
        percentage_low_quality = float(round((tot_low_quality_reads*100)/tot_removed_reads, 1))
        percentage_low_complexity = float(round((tot_too_many_N_reads*100)/tot_removed_reads, 1))
        percentage_too_short = float(round((tot_too_short_reads*100)/tot_removed_reads, 1))

    # Create layout objects.
    trp = 'Total reads passed: ' + str(tot_passed_reads) + ' (' + str(percentage_passed_reads) + '%)'
    tlq = 'Too low quality: ', str(tot_low_quality_reads) + ' (' + str(percentage_low_quality) + '%)'
    ts = 'Too short: ', str(tot_too_short_reads) + ' (' + str(percentage_too_short) + '%)'
    tlc = 'Too low complexity: ', str(tot_too_many_N_reads) + ' (' + str(percentage_low_complexity) + '%)'

    trr = 'Total reads removed: ' + str(tot_removed_reads) + ' (' + str(percentage_reads_removed) + '%)'

    return classified_reads, unclassified_reads, unfiltered_reads, trp, tlq, ts, tlc, trr

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
        waiting_message = "Batch files awaiting processing: " + str(delta)
        processed_message = "Batch files processed: " + str(files_processed)
    else: # if directory does not exist
        waiting_message = "Files awaiting processing: "
        processed_message = "Files processed: "
    return waiting_message, processed_message

########## SHUTDOWN CALLBACK #################################################

# At click of shutdown button.
@app.callback(
    Output('confirmation-modal', 'is_open'),
    Output('output-message', 'children'),
    Input('shutdown-button', 'n_clicks'),
    Input('confirm-no-button', 'n_clicks'),
    Input('confirm-yes-button', 'n_clicks'),
    State('confirmation-modal', 'is_open'),
    prevent_initial_call=True
)
def show_confirmation_modal(shutdown_clicks, no_clicks, yes_clicks, is_open):
    ctx = dash.callback_context

    if ctx.triggered:
        button_id = ctx.triggered[0]['prop_id'].split('.')[0]

        if button_id == 'shutdown-button':
            return not is_open, ''

        if button_id == 'confirm-no-button':
            return False, 'Action canceled.'

        if button_id == 'confirm-yes-button':
            if is_open:
                try:
                    # subprocess.Popen(["echo", "User shutdown sucessful."])
                    # get process ID of main process
                    with open('.runtime','r') as f:
                        import signal
                        pid = int(f.readline())

                        # send custom signal to trigger KeyboardInterrupt in wrapper main script
                        try:
                            os.kill(pid,signal.SIGUSR1)
                        except Exception as e:
                            print(f'Kill error: {e}')
                        #/
                    #/
                except Exception as e:
                    return is_open, f'Error: {str(e)}'
                return False, 'Shutting down program...'
            else:
                return is_open, ''

########## INFO BUTTON MODALS #################################################

# Sunburst chart info modal.
@app.callback(
    Output("sunburst-modal", "is_open"),
    Input("sunburst-open-button", "n_clicks"),
    Input("sunburst-close-button", "n_clicks"),
    State("sunburst-modal", "is_open"),
)
def toggle_modal(open_clicks, close_clicks, is_open):
    if open_clicks or close_clicks:
        return not is_open
    return is_open

# Sankey plot info modal.
@app.callback(
    Output("sankey-modal", "is_open"),
    Input("sankey-open-button", "n_clicks"),
    Input("sankey-close-button", "n_clicks"),
    State("sankey-modal", "is_open"),
)
def toggle_modal(open_clicks, close_clicks, is_open):
    if open_clicks or close_clicks:
        return not is_open
    return is_open

# QC info modal.
@app.callback(
    Output("qc-modal", "is_open"),
    Input("qc-open-button", "n_clicks"),
    Input("qc-close-button", "n_clicks"),
    State("qc-modal", "is_open"),
)
def toggle_modal(open_clicks, close_clicks, is_open):
    if open_clicks or close_clicks:
        return not is_open
    return is_open

# Pathogen info modal.
@app.callback(
    Output("pathogen-modal", "is_open"),
    Input("pathogen-open-button", "n_clicks"),
    Input("pathogen-close-button", "n_clicks"),
    State("pathogen-modal", "is_open"),
)
def toggle_modal(open_clicks, close_clicks, is_open):
    if open_clicks or close_clicks:
        return not is_open
    return is_open

# Toplist info modal.
@app.callback(
    Output("toplist-modal", "is_open"),
    Input("toplist-open-button", "n_clicks"),
    Input("toplist-close-button", "n_clicks"),
    State("toplist-modal", "is_open"),
)
def toggle_modal(open_clicks, close_clicks, is_open):
    if open_clicks or close_clicks:
        return not is_open
    return is_open

########## EXPORT CLASSIFICATION ##############################################

@app.callback(
    Output('modal-2', 'is_open'),
    Output('output-message-1', 'children'),
    Input('export-button-1', 'n_clicks'),
    Input('save-button-1', 'n_clicks'),
    State('modal-2', 'is_open'),
    State('filename-input-1', 'value'),
    prevent_initial_call=True
)
def toggle_modal(export_clicks, save_clicks, is_open, filename):
    ctx = dash.callback_context

    if not ctx.triggered:
        return False, None

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]

    if button_id == 'export-button-1':
        return True, None

    if button_id == 'save-button-1':
        if not filename:
            return True, 'Enter a file name of path'

        try:
            project_directory = config_contents["main_dir"]
            reports_directory = os.path.join(project_directory, 'reports')
            os.makedirs(reports_directory, exist_ok=True)

            if os.path.isabs(filename):
                file_path = f'{filename}.kreport2'  # User specified an absolute path
            else:
                file_path = os.path.join(reports_directory, f'{filename}.kreport2') # User specified only a file name

            # Copy the content of kreport_file to the specified file
            shutil.copyfile(kreport_file, file_path)

            return False, f'Report saved as {file_path}'
        except Exception as e:
            return True, f'Error: {str(e)}'
        

########## EXPORT TOPLIST #####################################################

@app.callback(
    Output('modal-3', 'is_open'),
    Output('output-message-2', 'children'),
    Input('export-button-2', 'n_clicks'),
    Input('save-button-2', 'n_clicks'),
    State('modal-3', 'is_open'),
    State('filename-input-2', 'value'),
    prevent_initial_call=True
)
def toggle_modal(export_clicks, save_clicks, is_open, filename):
    ctx = dash.callback_context

    if not ctx.triggered:
        return False, None

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]

    if button_id == 'export-button-2':
        return True, None

    if button_id == 'save-button-2':
        if not filename:
            return True, 'Enter a file name of path'

        try:
            project_directory = config_contents["main_dir"]
            reports_directory = os.path.join(project_directory, 'reports')
            os.makedirs(reports_directory, exist_ok=True)

            if os.path.isabs(filename):
                file_path = f'{filename}.csv'  # User specified an absolute path
            else:
                file_path = os.path.join(reports_directory, f'{filename}.csv') # User specified only a file name

            # Export the current toplist to a csv file 
            top_df.to_csv(file_path, index=False)

            return False, f'List saved as {file_path}'
        except Exception as e:
            return True, f'Error: {str(e)}'
        
########## EXPORT PATHOGENS #####################################################

@app.callback(
    Output('modal-4', 'is_open'),
    Output('output-message-3', 'children'),
    Input('export-button-3', 'n_clicks'),
    Input('save-button-3', 'n_clicks'),
    State('modal-4', 'is_open'),
    State('filename-input-3', 'value'),
    prevent_initial_call=True
)
def toggle_modal(export_clicks, save_clicks, is_open, filename):
    ctx = dash.callback_context

    if not ctx.triggered:
        return False, None

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]

    if button_id == 'export-button-3':
        return True, None

    if button_id == 'save-button-3':
        if not filename:
            return True, 'Enter a file name of path'

        try:
            project_directory = config_contents["main_dir"]
            reports_directory = os.path.join(project_directory, 'reports')
            os.makedirs(reports_directory, exist_ok=True)

            if os.path.isabs(filename):
                file_path = f'{filename}.csv'  # User specified an absolute path
            else:
                file_path = os.path.join(reports_directory, f'{filename}.csv') # User specified only a file name

            # Export the current toplist to a csv file 
            df_to_print.to_csv(file_path, index=True)

            return False, f'List saved as {file_path}'
        except Exception as e:
            return True, f'Error: {str(e)}'

###############################################################################
###############################################################################

def run_app():
    '''
    This is how the app runs.
    '''
    # A unique port specifiable in config.
    # Debug=True means it updates as you make changes in this script.
    app.run(debug=True, port=int(config_contents['gui_port']))
if __name__ == "__main__":
    # The run_app makes it run as an entry point (bash command).
    run_app()
