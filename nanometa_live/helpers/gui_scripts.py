# Standard Library Imports
import math
import os
import sys
import time
from datetime import datetime

# Third-Party Imports
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yaml

# make sure the custom packages are found
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def create_edges(rev_matrix, id_dict, rev_letters):
    """
    Creates edges between all nodes.
    Returns it as a pandas df.

    Only user designated tax levels are kept.
    Each lower clade is assigned to its corresponding closest parent clade
    to make the lineage work with any possible combination of tax levels.
    """

    # create a scoring dictionary for the tax letters
    scoring_dict = {}
    score = 0
    for letter in rev_letters:
        scoring_dict[letter] = score
        score += 1

    # filter the reversed matrix to only keep the desigated levels
    mask = np.isin(rev_matrix[:, 1], rev_letters)
    filtered_matrix = rev_matrix[mask]

    # lists
    source = []
    target = []
    value = []
    rank = []

    # for each included tax letter
    for i in range(len(rev_letters)):
        # print('CURRENT:', rev_letters[i])
        # if you reach the root clade, stop.
        # it will be included anyway since its target will refer to it
        if rev_letters[i] == rev_letters[-1]:
            # print(rev_letters[i] + ' reached -- done')
            break
        else:  # for all other clade letters
            # parse through the rev matrix
            for j in range(filtered_matrix.shape[0]):
                # if you find the current tax letter
                if filtered_matrix[j, 1] == rev_letters[i]:
                    # print(filtered_matrix[j, 1], 'found:')
                    # print(filtered_matrix[j, 0])
                    # search on from that point
                    for entry in filtered_matrix[j + 1 :, :]:
                        # the first following entry with a tax score higher
                        # than the current one, is assigned parent
                        if (
                            scoring_dict[entry[1]]
                            > scoring_dict[rev_letters[i]]
                        ):
                            # print(entry[0], '- PARENT TO ', filtered_matrix[j, 0], 'found.')
                            source.append(
                                int(id_dict[entry[0]])
                            )  # source = name of parent converted to node id
                            target.append(
                                int(id_dict[filtered_matrix[j, 0]])
                            )  # target = name of current converted to node id
                            value.append(
                                int(filtered_matrix[j, 2])
                            )  # add nr of reads for current
                            rank.append(
                                filtered_matrix[j, 1]
                            )  # tax rank letter of current
                            break
    # initiates the df
    edges_df = pd.DataFrame(
        {"source": source, "target": target, "value": value, "rank": rank}
    )
    # print(edges_df)
    return edges_df


def create_top_list(raw_df, domains, keep_letters, top=15):
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
    t_filt_df = d_filt_df2[d_filt_df2["rank"].isin(keep_letters)]
    # Sort in descending order of reads.
    o_t_filt_df = t_filt_df.sort_values("reads", ascending=False)
    # Keep the entries with the top x reads.
    top_t_filt_df = o_t_filt_df[0:top]
    # Add an index to the df. (Disabled Pandas warning originates here.)
    top_t_filt_df["Index"] = range(1, len(top_t_filt_df) + 1)
    # Reorganizes the columns of the df and renames them for layout.
    reorg_df = top_t_filt_df[["Index", "name", "id", "rank", "reads"]]
    reorg_df.columns = ["Index", "Name", "Tax ID", "Tax Rank", "Reads"]
    return reorg_df


def domain_filtering(
    raw_df, selected_domains  # full data  # by domain name: Bacteria etc
):
    """
    Filters the raw kreport df by user chosen domains.
    """

    # adding col names for ease of parsing
    raw_df.columns = ["%", "cuml_reads", "reads", "rank", "id", "name"]

    all_domains = [
        "Bacteria",  # these will never change
        "Archaea",
        "Eukaryota",
        "Viruses",
    ]

    domain_start = []

    # parses through all domains
    for i in all_domains:
        # print('domain in all domains:', i)
        # finds the row with the domain entry
        start_row = raw_df.loc[raw_df["name"] == i]
        # print('domain start row:\n', start_row)
        # gets the index of that row
        start_index = start_row.index.values.tolist()
        # print('domain start index:\n', start_index)
        # if domain exists in kreport
        if len(start_index) != 0:
            # add domain start index
            domain_start.append(start_index[0])
        else:  # if domain does not exist in kreport: ex no viruses
            domain_start.append(-1)  # append -1

    # print(all_domains)
    # print(domain_start)

    # create a df of the domain start indexes and names
    domain_df = pd.DataFrame(list(zip(all_domains, domain_start)))
    domain_df.columns = ["name", "start"]
    # sort by index in order of which comes first in list
    domain_df = domain_df.sort_values("start")
    # remove domains not in kreport
    domain_df.drop(domain_df[domain_df["start"] == -1].index, inplace=True)

    # print(domain_df)

    domain_ranges = []

    # parse through all domains existing in the kreport
    for i in range(domain_df.shape[0]):
        # in every entry but the last
        if i + 1 < domain_df.shape[0]:
            # add the start index and the stop index (start index of next domain)
            domain_ranges.append(
                [domain_df.iloc[i, 1], domain_df.iloc[i + 1, 1]]
            )
            # print(domain_df.iloc[i,1], domain_df.iloc[i+1,1])
        else:  # for the last entry
            # add the domain start index and make the end index the last row of the kreport.
            # This will include "other sequences" etc but it is irrelevant since they are not
            # included in the clade list
            domain_ranges.append([domain_df.iloc[i, 1], len(raw_df)])
            # print(domain_df.iloc[i,1])

    # add the domain ranges to the df
    domain_df["index_ranges"] = domain_ranges
    # print(domain_df)

    temp_lists = []

    # parse through all domains
    for i in range(domain_df.shape[0]):
        # print(i)
        # print(domain_df.iloc[i,0])
        # if the domain is in selected list
        if domain_df.iloc[i, 0] in selected_domains:
            # adds all rows between domain start and domain end indexes
            temp_lists.append(
                [
                    i
                    for i in range(
                        domain_df.iloc[i, 2][0], domain_df.iloc[i, 2][1]
                    )
                ]
            )
            # print(domain_df.iloc[i,2][0], domain_df.iloc[i,2][1])

    # make it all into one list
    flat_list = [item for sublist in temp_lists for item in sublist]
    # print(flat_list)

    # filter the raw df by the index list
    filt_df = raw_df[raw_df.index.isin(flat_list)]

    return filt_df


def filter_by_top(top, edges_df, result_matrix, tax_letters, rev_tax_letters):
    """
    Filters the edge df by top entries, determined by nr of reads.
    Organizes the data as nodes and egdes for sankey plotting.
    Adds the correct parents to each node depending on the user specified
    tax levels.
    Adds "ghost nodes" to the end of clades which do not have complete
    lineage ending at the lowest specified tax level.
    """

    # this part determines the node IDs of the domains

    # transform to df for ease of parsing
    # this df is filtered by tax letters
    result_df = pd.DataFrame(
        data=result_matrix, columns=["name", "nodeId", "rank", "readNrs"]
    )

    # finds the rows containing the highest tax level included in tax letters
    highest_clades = result_df.loc[result_df["rank"] == tax_letters[0]]
    # print(highest_clades)
    # extracts the node IDs for the highest clades
    clade_list = highest_clades[highest_clades.columns[1]].values.tolist()
    # transforms them to integers
    clade_list = [int(x) for x in clade_list]
    # print(clade_list)

    # initialize empty top filtered df
    top_df = pd.DataFrame(columns=["source", "target", "value", "rank"])
    # top_df.loc[0] = [-1,-1,-1,'z']
    # print(top_df)

    # now we find the top x taxa for each level

    # parse through chosen letters backwards
    # ghost_nr = 0
    for letter in rev_tax_letters:
        # print('\nCURRENT LETTER: '+letter)
        # creates a temporary df
        # this df needs to be nullified for every letter
        temp_df = pd.DataFrame(columns=["source", "target", "value", "rank"])
        # parses through edges df
        # edges df is already filtered by tax letters
        for i in range(edges_df.shape[0]):
            # if the rank of the entry is current letter
            if edges_df.iloc[i, 3] == letter:
                # print(edges_df.iloc[i,3], '-', edges_df.iloc[i,1])
                # print(edges_df.iloc[i,])
                # add it to the temp df
                temp_df.loc[len(temp_df.index)] = [
                    edges_df.iloc[i, 0],  # source
                    edges_df.iloc[i, 1],  # target
                    edges_df.iloc[i, 2],  # value
                    edges_df.iloc[i, 3],
                ]  # rank
        # after it has collected the entire group of that letter
        # sort in descending order
        temp_df = temp_df.sort_values("value", ascending=False)
        # keep the top x
        temp_df = temp_df[0:top]
        # target_list = temp_df["target"].values.tolist()
        # print('TARGET LIST = ', target_list)
        # print('temp_df:\n', temp_df)

        # concat to the top filtered df
        top_df = pd.concat([top_df, temp_df])
        # drop duplicates: we keep only the ones not already in the df
        # print('top_df:\n', top_df)
        # n_duplicates = top_df.duplicated().sum()
        # print('DUPLICATES:', n_duplicates)
        top_df = top_df.drop_duplicates()
        # print('top_df:\n', top_df) # no highest clade present in edges df

        # then we add parents immedately

        stop_list = [0]
        # keeps parsing until stop list has no entries
        while len(stop_list) != 0:
            # put all targets in a list
            check_list = top_df[top_df.columns[1]].values.tolist()
            # print('stop_list_len:', len(stop_list))
            # empties the stop list
            stop_list = []
            # parses through top_df
            for i in range(top_df.shape[0]):
                # if the entry belongs to the highest clade, it is skipped
                # the highest clade does not need to be in the target list
                if top_df.iloc[i, 0] not in clade_list:
                    # if the source ID is not already in targets
                    if top_df.iloc[i, 0] not in check_list:
                        # extract the source ID
                        stop_list.append(top_df.iloc[i, 0])
                        # print(top_df.iloc[i,0])
                        # find the entry where the current source is the target in edges df
                        row_to_add = edges_df.loc[
                            edges_df["target"] == top_df.iloc[i, 0]
                        ]
                        # add it to the top df
                        top_df = pd.concat([top_df, row_to_add])
                else:  # if entry is a highest clade, it is skipped
                    continue
        # print('ADDING PARENTS')
        # print(top_df)
        # ghost_nr += 1

    # now we need to add ghost nodes for all lineages not
    # ending on the lowest included tax level

    # extract the source nodes
    complete_source_list = top_df["source"].values.tolist()
    ghost_dict = {}
    ghost_score = 0
    # assigns scores for the number of ghost nodes needed to be
    # created depending on the tax level
    for letter in rev_tax_letters:
        ghost_dict[letter] = ghost_score
        ghost_score += 1
    # print(complete_source_list)
    ghost_nodes = 0
    # where the numbering of new ghost nodes should begin
    ghost_id_nr = result_matrix.shape[0]
    # print(ghost_id_start, type(ghost_id_start), '!!!!!!!!!!!!!')
    # temp df for ghost nodes
    ghost_temp = pd.DataFrame(columns=["source", "target", "value", "rank"])
    # parse through top df
    for i in range(top_df.shape[0]):
        if top_df.iloc[i, 3] != rev_tax_letters[0]:
            # if a match is found that is not in the source list,
            # meaning it is not a source to any lower node
            # print('not end node met!', top_df.iloc[i,1])
            if top_df.iloc[i, 1] not in complete_source_list:
                # print('both criteria met:', top_df.iloc[i,1])
                # create ghost nodes
                new_row = {
                    "source": top_df.iloc[i, 1],
                    "target": ghost_id_nr,
                    "value": 1,
                    "rank": "x",
                }
                ghost_temp.loc[len(ghost_temp)] = new_row
                ghost_id_nr += 1
                # keep track of the number of added ghost nodes
                ghost_nodes += 1
                # varying numbers of ghost nodes need to be created
                for j in range(int(ghost_dict[top_df.iloc[i, 3]]) - 1):
                    new_row = {
                        "source": ghost_id_nr - 1,
                        "target": ghost_id_nr,
                        "value": 1,
                        "rank": "x",
                    }
                    ghost_temp.loc[len(ghost_temp)] = new_row
                    ghost_id_nr += 1
                    ghost_nodes += 1
    # add the ghost nodes to the df
    top_df = pd.concat([top_df, ghost_temp])
    # top_df.drop(0)
    # print('FINAL\n', top_df)
    # print('ghost nodes:', ghost_nodes)
    # col_list = top_df["target"].values.tolist()
    # d = Counter(col_list)
    # repeated_list = list([num for num in d if d[num]>1])
    # print("Duplicate integers: ",repeated_list)
    return top_df, ghost_nodes


def fix_list_order(real_list, wrong_list):
    """
    Orders the list coming in from the user settings tax letter checkboxes,
    using the correct order from the config file.
    """
    # this will be the proper list
    fixed_list = []
    # parses through each letter in the config list
    for i in real_list:
        # if the letter is in the checkbox list
        if i in wrong_list:
            # include it in the list to use
            fixed_list.append(i)
    return fixed_list


def format_sankey(top_df, label, pad=25, thickness=10):
    """
    Organizes the data to plotly sankey plot format
    """
    link = dict(
        source=top_df[top_df.columns[0]].values.tolist(),
        target=top_df[top_df.columns[1]].values.tolist(),
        value=top_df[top_df.columns[2]].values.tolist(),
    )

    node = dict(label=label, pad=25, thickness=10, color="blue")

    sankey_data = go.Sankey(link=link, node=node)
    return sankey_data


# call
# sankey_data = format_sankey(edges=, label=)


def get_fastp_df(fastp_file):
    """
    Creates a dataframe from the cumulative fastp file.
    If no fastp file has been produced, it returns a placeholder.
    """
    # checks if the data has been created
    if os.path.isfile(fastp_file):
        # creates the df
        fastp_df = pd.read_csv(
            fastp_file,
            names=[
                "passed_filter_reads",
                "low_quality_reads",
                "too_many_N_reads",
                "too_short_reads",
            ],
        )
    else:  # if no data: creates empty placeholder df
        fastp_df = pd.DataFrame(
            columns=[
                "passed_filter_reads",
                "low_quality_reads",
                "too_many_N_reads",
                "too_short_reads",
            ]
        )
        fastp_df.loc[len(fastp_df.index)] = [1, 1, 1, 1]

    # create cumulative columns
    fastp_df["cum_passed_filter_reads"] = fastp_df[
        "passed_filter_reads"
    ].cumsum()
    fastp_df["cum_low_quality_reads"] = fastp_df["low_quality_reads"].cumsum()
    fastp_df["cum_too_many_N_reads"] = fastp_df["too_many_N_reads"].cumsum()
    fastp_df["cum_too_short_reads"] = fastp_df["too_short_reads"].cumsum()

    return fastp_df


def get_icicle_data(filt_rev_matrix, config_letters):
    """
    Organizes the data in the format needed for sunsickle charts.
    Organizes the taxon lineages by assigning parents to
    each taxon depending on which tax levels are included by the user.
    """
    Taxon = []
    Tax_ID = []
    Parent = []
    Reads = []
    # reverse the taxonomy letters
    rev_config_letters = config_letters[::-1]
    # print(rev_config_letters)

    # create a scoring dictionary for the rev tax letters
    scoring_dict = {}
    score = 0
    for letter in rev_config_letters:
        scoring_dict[letter] = score
        score += 1
    # print(scoring_dict)

    # updating of changed variable name instead of changing in script below
    rev_matrix = filt_rev_matrix
    # print(rev_matrix)
    # filter the reversed matrix to only keep the desigated levels
    mask = np.isin(rev_matrix[:, 2], rev_config_letters)
    filt_rev_matrix = rev_matrix[mask]
    # print(filt_rev_matrix)

    # go through each tax letter backwards
    for i in range(len(rev_config_letters)):
        # print('\n-----> current letter:', rev_config_letters[i])
        # when the final letter is reached (highest tax level)
        if rev_config_letters[i] == rev_config_letters[-1]:
            # parse through reversed matrix
            for j in range(filt_rev_matrix.shape[0]):
                # when a matching clade is found
                if filt_rev_matrix[j, 2] == rev_config_letters[i]:
                    # print(filt_rev_matrix[j,0], 'assigned root - reads:', filt_rev_matrix[j,3])
                    # append the info. This is an inofficial end node
                    Taxon.append(filt_rev_matrix[j, 0])
                    Tax_ID.append(filt_rev_matrix[j, 1])
                    Parent.append("root")
                    read = int(filt_rev_matrix[j, 3])
                    # print(read, type(read))
                    Reads.append(read)
        else:  # until the highest tax level is reached
            for j in range(filt_rev_matrix.shape[0]):
                # parse through reversed matrix
                if filt_rev_matrix[j, 2] == rev_config_letters[i]:
                    # if a match is found for the current tax letter,
                    # append the info
                    # print(filt_rev_matrix[j,2], '-', filt_rev_matrix[j,0])
                    Taxon.append(filt_rev_matrix[j, 0])
                    Tax_ID.append(filt_rev_matrix[j, 1])
                    read = int(filt_rev_matrix[j, 3])
                    # print(read, type(read))
                    Reads.append(read)
                    for entry in filt_rev_matrix[j + 1:, :]:
                        # the first following entry with a tax score higher than
                        # the current one, is assigned parent
                        if (
                            scoring_dict[entry[2]]
                            > scoring_dict[rev_config_letters[i]]
                        ):
                            # print('PARENT:', entry[2], '-', entry[0])
                            Parent.append(entry[0])
                            break
    # add the functional end node (needed by plotly)
    Taxon.append("root")
    Tax_ID.append("none")
    Parent.append("")
    Reads.append(0)
    return Taxon, Parent, Reads


def get_qc_df(qc_file):
    """
    Creates a dataframe from the cumulative qc file (qc_data/cumul_qc.txt).
    If no qc file has been produced, it returns a placeholder.
    """
    # checks if the data has been created
    if os.path.isfile(qc_file):
        # creates the df
        qc_df = pd.read_csv(qc_file, names=["Time", "Reads", "Bp"])

        # check and reformat the time strings
        # To avoid pandas timestamp errors
        def format_time(time_str):
            try:
                # Attempt to parse the time string as a datetime with microseconds
                time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                # If it's not in the expected format, add placeholder milliseconds
                time_str += ".111111"
                time_obj = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
            return time_obj.strftime("%Y-%m-%d %H:%M:%S.%f")

        # apply format_time function to the "Time" column
        qc_df["Time"] = qc_df["Time"].apply(format_time)

        # sorts the df by time
        qc_df = qc_df.sort_values(by=["Time"], ascending=True)
    else:  # if no data: creates empty placeholder df
        qc_df = pd.DataFrame(columns=["Time", "Reads", "Bp"])
        qc_df.loc[len(qc_df.index)] = ["2023-09-25 00:00:00.0", 0, 0]

    # create cumulative reads
    qc_df["Cumulative reads"] = qc_df["Reads"].cumsum()
    # create cumulative bp
    qc_df["Cumulative bp"] = qc_df["Bp"].cumsum()

    return qc_df


def get_result_matrix(d_filt_df, tax_letters):
    """
    Uses the domain filtered kraken df and selected tax letters to
    create a matrix and a dictionary to be used in further data processing.
    The node IDs need to be created here, before the entries are filtered,
    since the nodes are all ordered by tax hierarchy in this matrix.
    This way the label parameter of the sankey plot will have the correct
    order of node numberings.
    """
    # a counter to number the nodes
    node_nr = 0
    # list for node names; taxon names. Will become 'label' parameter
    names = []
    # list where the node nr will be stored as node id
    node_ids = []
    # using specified tax letters
    tax_rankings = []
    # for later sorting by reads
    read_nrs = []
    # important dictionary to be used later to map taxon names to node ids
    node_id_dict = {}
    # parse through each tax letter,
    # ordering the df in nodes, domains to the right with the lowest nrs,
    # going down the clades and assigning higher node nrs to ensure that
    # each sub-level has a higher nr than its parent
    for letter in tax_letters:
        # parse through df
        for i in range(d_filt_df.shape[0]):
            # if it matches current tax letter
            if d_filt_df.iloc[i, 3] == letter:
                # add name of taxon/node
                name = d_filt_df.iloc[i, 5]
                # add node id
                node_id = node_nr
                # add tax letter
                tax_ranking = d_filt_df.iloc[i, 3]
                # add nr of reads
                nr_reads = d_filt_df.iloc[i, 1]
                # append the stuff to the lists
                names.append(name)
                node_ids.append(node_id)
                tax_rankings.append(tax_ranking)
                read_nrs.append(nr_reads)
                # append the taxon name and node id to dict
                node_id_dict[name] = node_nr
                # add one to the counter to number the next node
                node_nr += 1
    # create a matrix with the nodes/entries ordered with each higher
    # clade having a lower node id
    result_matrix = np.array([names, node_ids, tax_rankings, read_nrs])
    result_matrix = np.transpose(result_matrix)
    return result_matrix, node_id_dict


def get_rev_matrix(d_filt_df):
    """
    Creates a reversed matrix from the domain filtered df
    in order to parse through the list
    starting with lowest tax level and assigning it to the corresponding
    parent clade.
    """
    rev_df = d_filt_df.iloc[::-1]  # reverses the df
    # adds the data needed
    names = rev_df[rev_df.columns[5]].values.tolist()
    tax_rankings = rev_df[rev_df.columns[3]].values.tolist()
    read_nrs = rev_df[rev_df.columns[1]].values.tolist()
    # creates a reversed matrix with names, tax letters and read nrs
    rev_matrix = np.column_stack((names, tax_rankings, read_nrs))
    return rev_matrix


def get_time():
    """
    Returns the current time.
    """
    t = time.localtime()
    current_time = time.strftime("%H:%M:%S", t)
    return current_time


def icicle_sunburst_data(
    raw_df, domains, count=10, config_file_path="config.yaml"
):
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
        with open(config_file_path, "r") as cf:
            config_contents = yaml.safe_load(cf)
    except Exception as e:
        print(
            f"Error: An issue occurred while reading the config file. Details: {e}"
        )
        return None

    # Gets the tax letters from the config file.
    config_letters = config_contents["taxonomic_hierarchy_letters"]

    # Filters by domain.
    d_filt_df = domain_filtering(raw_df, domains)
    # Filters by lowest count to be kept.
    c_filt_df = d_filt_df[d_filt_df.iloc[:, 1] > count]
    # Creates a reversed matrix for ease of parsing the kreport structure.
    filt_rev_matrix = icicle_sunburst_matrix(c_filt_df)
    # The lists needed for plotly.
    # print(filt_rev_matrix)
    # This sorts the kreport data in taxon lineages, assigning
    # parents to each taxon depending on designated tax letters.
    Taxon, Parent, Reads = get_icicle_data(filt_rev_matrix, config_letters)
    # The plotly data format.
    ice_sun_data = dict(Taxon=Taxon, Parent=Parent, Reads=Reads)
    return ice_sun_data


def icicle_sunburst_matrix(c_filt_df):
    """
    Creates a reversed matrix for sunsickle organizing.
    A reversed matrix makes parsing easier since the kreport is
    structured in a tree-like hierachical fashion.
    """
    rev_df = c_filt_df.iloc[::-1]  # reverses the df
    # adds the data needed
    names = rev_df[rev_df.columns[5]].values.tolist()
    ids = rev_df[rev_df.columns[4]].values.tolist()
    tax_rankings = rev_df[rev_df.columns[3]].values.tolist()
    read_nrs = rev_df[rev_df.columns[2]].values.tolist()
    # creates a reversed matrix with names, tax letters and read nrs
    rev_matrix = np.column_stack((names, ids, tax_rankings, read_nrs))
    return rev_matrix


def kreport2_df(kreport_file):
    """
    Imports kreport2 file and creates a pd dataframe.
    """
    raw_kraken_df = pd.read_csv(
        kreport_file,
        sep="\t",
        # removes spaces in col 5
        skipinitialspace=True,
        header=None,
    )
    return raw_kraken_df


def pathogen_df(pathogen_list, raw_df):
    """
    Creates a df of data on specified pathogens from config list.
    """

    # df makes layout much easier
    pathogen_info = pd.DataFrame(
        columns=["Name", "Tax ID", "Reads", "Percent reads", "log10(Reads)"]
    )
    # iterates through the list of tax IDs
    for entry in pathogen_list:
        # compares each pathogen against IDs in kreport
        for i in range(raw_df.shape[0]):
            # if there is a match
            if entry == raw_df.iloc[i, 4]:
                # handle zero values for log function
                if raw_df.iloc[i, 2] == 0:
                    log10reads = 0  # set it to 0
                else:  # get the log of the reads for danger meter
                    log10reads = math.log(raw_df.iloc[i, 2], 10)
                # add the species to the results df.
                pathogen_info.loc[len(pathogen_info.index)] = [
                    raw_df.iloc[i, 5],  # add pathogen name
                    raw_df.iloc[i, 4],  # add pathogen taxID
                    raw_df.iloc[i, 2],  # add pathogen nr of reads
                    raw_df.iloc[i, 0],  # add percent reads for pathogens
                    log10reads,
                ]  # log value for the danger meter
    return pathogen_info


def sankey_placeholder():
    """
    Creates placeholder sankey data to display before kraken data starts coming in.
    """
    # the values
    placeholder_link = dict(source=[0], target=[1], value=[1])
    # placeholder node
    placeholder_node = dict(label=["Waiting for data"], pad=25, thickness=10)
    # sankey data object
    placeholder_data = go.Sankey(link=placeholder_link, node=placeholder_node)

    return placeholder_data


def tax_hierarchy_list(hierarchy_letters):
    """
    A list that defines which taxonomic hierarchies are to be included.
    The letters and hierarchies can be specified in the config file.
    Returns the hierarchy list and the reversed hierarcy list needed for processing.
    """
    reversed_hierarchy_letters = hierarchy_letters[::-1]
    return hierarchy_letters, reversed_hierarchy_letters


def validation_col(validation_list, blast_dir, read_nr_list):
    """
    Finds the blast results for each species of interes ID found in the kreport.
    Adds the results from the files to a list that is then made a column
    in the pathogen df.
    """
    validated_col = []
    # validation_list = the subset of species of interest actually found in the data
    counter = 0
    for i in validation_list:
        # print('now we are working on', i)
        # print('counter is ', counter)
        # create path
        if read_nr_list[counter] == 0:
            # print('reads for ', i,'is',read_nr_list[counter])
            validated_col.append(0)
            # print('the value 0 has been added to entry',  i)
            counter += 1
            continue
        # print('entry', i, 'has', read_nr_list[counter], 'nr of reads')
        file_name = str(i) + ".txt"
        path = os.path.join(blast_dir, file_name)
        # print(path)
        if os.path.isfile(path):  # if file exists
            # print('path exists')
            # import data
            val_df = pd.read_csv(path, sep="\t", header=None)
            # print(val_df)
            # print(val_df.iloc[:,0])
            # extract nr of unique sequences. Many sequences will have several matches
            # on the genome
            unique_seqs = val_df.iloc[:, 0].nunique()
            # print(unique_seqs)
            # print(unique_seqs)
            # add nr to column
            validated_col.append(unique_seqs)
            # print(validated_col)
        else:  # if the correct file is not found
            validated_col.append(0)
        counter += 1
    return validated_col
