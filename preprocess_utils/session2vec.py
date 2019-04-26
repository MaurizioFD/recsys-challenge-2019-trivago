import sys
import os
sys.path.append(os.getcwd())

import data
import pandas as pd
import utils.sparsedf as sparsedf
from utils.check_folder import check_folder
from utils.df import scale_dataframe
import utils.datasetconfig as datasetconfig
import numpy as np
import scipy.sparse as sps
from sklearn.preprocessing import MultiLabelBinarizer, MinMaxScaler
from keras.utils import to_categorical
from tqdm import tqdm
import utils.menu as menu
#import pickle

# ======== PRE-PROCESSING ========= #

def save_accomodations_one_hot(accomodations_df, path):
    """ Save a sparse dataframe with columns: item_id  |  feature1 | feature2 | feature3 | feature4... """
    # one-hot encoding of the accomodations features
    item_ids = accomodations_df.item_id
    accomodations_df.properties = accomodations_df.properties.str.split('|')
    accomodations_df.properties = accomodations_df.properties.fillna('')

    mlb = MultiLabelBinarizer() #(sparse_output=True)
    attributes_df = mlb.fit_transform(accomodations_df.properties)
    #attributes_df = pd.SparseDataFrame(attributes_df, columns=mlb.classes_, default_fill_value=0)
    attributes_df = pd.DataFrame(attributes_df, columns=mlb.classes_)

    # re-add item_id column to get: item_id  |  one_hot_features[...]
    attributes_df = pd.concat([item_ids, attributes_df], axis=1)

    print('Saving one-hot accomodations...', end=' ', flush=True)
    attributes_df.to_csv(path, index=False)
    # with open('features1hot', 'w') as f:
    #     pickle.dump(features_columns, f)
    print('Done!')
    return attributes_df

def one_hot_df_column(df, column_label, classes, sparse=False):
    """ Substitute a dataframe column with its one-hot encoding derived columns """
    mlb = MultiLabelBinarizer(classes=classes, sparse_output=sparse)
    res = mlb.fit_transform(df[column_label].values.reshape(-1,1))
    
    if sparse:
        df[classes] = pd.SparseDataFrame(res, columns=mlb.classes_, dtype='Int8', index=df.index)
    else:
        for i,col in enumerate(mlb.classes_):
            df[col] = pd.Series(res[:,i], dtype='int8', index=df.index)
    return df.drop(column_label, axis=1)

def add_accomodations_features(df, path_to_save, logic='skip', row_indices=[]):
    """
    Add the features (one-hot) to the dataframe that match the 'reference' and save the resulting dataframe.
    It is possible to specify a list of rows to skip (logic='skip'), or to join only for some rows (logic='subset').
    Return the target columns and the one-hot columns that have been added to the dataframe
    """
    # save the references series and then set the reference to NaN to skip the join on that rows
    join_data = dict()
    join_data['backup_reference_series'] = df.reference.values.copy()
    if len(row_indices) > 0:
        if logic == 'skip':
            # set to NaN the rows to be skipped
            df.loc[row_indices, 'reference'] = np.nan
        if logic == 'subset':
            # set to NaN all rows, except for the specified rows
            backup_serie = df.loc[row_indices].reference.copy()
            df.reference = np.nan            
            df.loc[row_indices, 'reference'] = backup_serie

    # cast the reference column to Int64 removing the string values
    df.reference = pd.to_numeric(df.reference, errors='coerce') #.astype('Int64')

    # one-hot encoding of the accomodations features
    attributes_df = data.accomodations_one_hot()
    # accomodations features columns
    #features_columns = attributes_df.columns
    # with open(one_hot_accomodations_features_path, 'w') as f:
    #     pickle.dump(features_columns, f)

    #original_columns = set(df.columns)

    # add the 'no-reference' column
    #df['no_reference'] = (~df.reference.fillna('').str.isnumeric()) * 1
    
    # after_one_hot_columns = set(df.columns)
    # one_hot_columns = after_one_hot_columns.difference(original_columns)
    # one_hot_columns = list(one_hot_columns.union(set(features_columns)))
    
    def post_join(chunk_df, data):
        # reset the original references
        #chunk_df.loc[:,'reference'] = data['backup_reference_series'][data['$i1']:data['$i2']]
        return chunk_df.drop('reference', axis=1)
    
    sparsedf.left_join_in_chunks(df, attributes_df, left_on='reference', right_on=None, right_index=True,
                                post_join_fn=post_join, data=join_data, path_to_save=path_to_save)

    # print('Reloading the partial dataframe...', end=' ', flush=True)
    # df = sparsedf.read(path_to_save, sparse_cols=features_columns).set_index('orig_index')
    # reset the correct references from the backup
    #df.reference = backup_reference_series

    # return the features columns and the one-hot attributes
    #return df

def add_reference_classes(df, actiontype_col='clickout item', action_equals=1, classes_prefix='ref_', num_classes=25):
    """ Add the reference index in the impressions list as a new column for each clickout in the dataframe.
    For the clickout interactions, a 1 is placed in the column with name {classes_prefix}{reference index in impressions}.
    For the non-clickout interactions, 0s are placed in every columns with names {classes_prefix}{0...}
    """
    tqdm.pandas()
    def set_class(row):
        if row[actiontype_col] == action_equals:
            try:
                ref_class = row.impressions.split('|').index(row.reference)
            except ValueError:
                ref_class = 0
            return ref_class
        else:
            return -1

    df['temp_ref_class'] = df.progress_apply(set_class, axis=1)
    # one-hot encode the classes
    ref_classes = ['{}nan'.format(classes_prefix)] + ['{}{}'.format(classes_prefix, i) for i in range(num_classes)]
    encoding = to_categorical(df['temp_ref_class']+1, num_classes=len(ref_classes), dtype='int8')
    # add the encoding columns, skipping the first one (ref_nan column)
    ref_classes = ref_classes[1:]
    for i,c in enumerate(ref_classes):
        df[c] = encoding[:,i+1]

    return df.drop('temp_ref_class', axis=1), ref_classes

def get_last_clickout(df, index_name=None, rename_index=None):
    """ Return a dataframe with the session_id as index and the reference of the last clickout of that session. """
    tqdm.pandas()
    def take_last_clickout(g, index_name, rename_index):
        clickouts = g[g.action_type == 'clickout item']
        if clickouts.shape[0] == 0:
            return None
        
        last_clickout_row = clickouts.iloc[-1]
        if index_name is None or rename_index is None:
            return pd.Series({'reference': last_clickout_row.reference})
        else:
            return pd.Series({rename_index: last_clickout_row[index_name], 'reference': last_clickout_row.reference})
    
    cols = ['session_id','action_type','reference']
    if index_name is not None:
        df = df.reset_index()
        cols.insert(0, index_name)

    df = df[cols].groupby('session_id').progress_apply(take_last_clickout, index_name=index_name, rename_index=rename_index)
    return df.dropna().astype(int)

"""
def get_labels(sess2vec_df, features_columns, columns_to_keep_in_labels=['orig_index']):
    #Get the labels: features of the clickout references.
    #For the clickout interactions, the target vector is the reference fearures.
    #For the non-clickout interactions, the target vector is all zeros.
    #EDIT:
    #Extracts only the labels of clickout interactions in the sessions
    
    df_of_cols_to_keep = sess2vec_df[columns_to_keep_in_labels]

    rows_to_set_mask = sess2vec_df['action_type_clickout item'] == 0
    sess2vec_df = sess2vec_df[features_columns]
    # create a sparse matrix to store the result
    labels_sparse_matrix = sps.csr_matrix(sess2vec_df.shape, dtype=np.uint8)
    # set the labels from the dataframe target columns
    labels_sparse_matrix[np.array(rows_to_set_mask).nonzero()] = sess2vec_df[rows_to_set_mask].values
    # set to 0 the non-clickout interactions
    #labels_df.loc[ (sess2vec_df['action_type_clickout item'] == 0), : ] = 0
    
    # rebuild the dataframe
    labels_sparse_df = pd.SparseDataFrame(labels_sparse_matrix)
    labels_sparse_df[columns_to_keep_in_labels] = df_of_cols_to_keep
    return labels_sparse_df
"""

def add_impressions_as_new_actions(df, new_rows_starting_index=99000000, drop_cols=['impressions','prices'], append_every=1000000):
    """
    Add dummy actions before each clickout to indicate each one of the available impressions.
    Prices are incorporated inside the new rows in a new column called 'impression_price'.
    Since this is the most expensive task of the creation process, a multicore implementation would allow to split
    the work between the cpu cores (but obviuosly not working!)
    """
    df['impression_price'] = -1     #np.nan
    clickout_rows = df[df.action_type == 'clickout item']
    print('Total clickout interactions found:', clickout_rows.shape[0], flush=True)

    columns = clickout_rows.columns
    def append_to_df(temp_df, df, columns, drop_cols):
        return df.append(pd.DataFrame(temp_df, columns=columns), sort=False).drop(drop_cols, axis=1)

    temp_df = []
    for _, row in tqdm(clickout_rows.iterrows()):
        impressions = list(map(int, row.impressions.split('|')))
        prices = list(map(int, row.prices.split('|')))
        row.action_type = 'show_impression'
  
        steps = np.linspace(row.step-1+1/len(impressions),row.step,len(impressions)+1)
        for imprsn, impr_price, step in zip(impressions, prices, steps):
            # a copy is needed otherwise row seems to be taken by reference
            r = row.copy()
            r.name = new_rows_starting_index
            
            r.reference = imprsn
            r.impression_price = impr_price
            r.step = step
            new_rows_starting_index += 1

            temp_df.append(r)
        
        if len(temp_df) >= append_every:
            df = append_to_df(temp_df, df, columns, drop_cols)
            temp_df = []
    
    if len(temp_df) > 0:
        df = append_to_df(temp_df, df, columns, drop_cols)


    df.index = df.index.set_names(['index'])    
    return df.sort_values(['user_id','session_id','timestamp','step']), new_rows_starting_index

def pad_sessions(df, max_session_length):
    """ Pad/truncate each session to have the specified length (pad by adding a number of initial rows) """
    tqdm.pandas()

    def pad(g, max_length):
        # remove all interactions after the last clickout
        clickout_rows = g[g.action_type == 'clickout item']
        if clickout_rows.shape[0] > 0:
            index_of_last_clickout = clickout_rows.iloc[[-1]].index.values[0]
            g = g.loc[:index_of_last_clickout]
        
        grouplen = g.shape[0]
        if grouplen <= max_length:
            # pad with zeros
            array = np.zeros((max_length, g.shape[1]), dtype=object)
            # set index to -1 timestamp as the first one
            array[:,0] = -1
            # user_id and session_id are set equal to the ones for the current session
            array[:,1] = g.user_id.values[0]
            array[:,2] = g.session_id.values[0]
            # timestamp is set equal to the first of the sequence
            array[:,3] = g.timestamp.values[0]
            # the final part is written in place of the zeros
            array[-grouplen:] = g.values[-grouplen:]
        else:
            # truncate
            array = g.values[-max_length:]
        return pd.DataFrame(array, columns=g.columns)
    
    return df.reset_index().groupby('session_id').progress_apply(pad, max_length=max_session_length).set_index('index')

def sessions2tensor(df, drop_cols=[], return_index=False):
    """
    Build a tensor of shape (number_of_sessions, sessions_length, features_count).
    It can return also the indices of the tensor elements.
    """
    if len(drop_cols) > 0:
        sessions_values_indices_df = df.groupby('session_id').apply(lambda g: pd.Series({'tensor': g.drop(drop_cols, axis=1).values, 'indices': g.index.values}))
    else:
        sessions_values_indices_df = df.groupby('session_id').apply(lambda g: pd.Series({'tensor': g.values, 'indices': g.index.values}))
    
    #print(sessions_values_indices_df.shape)
    if return_index:
        return np.array(sessions_values_indices_df['tensor'].to_list()), np.array(sessions_values_indices_df['indices'].to_list())
    else:
        return np.array(sessions_values_indices_df['tensor'].to_list())


def create_dataset_for_regression(mode, cluster, pad_sessions_length=70, add_item_features=True, save_X_Y=True):
    """
    pad_sessions_length (int): final length of sessions after padding/truncating
    add_item_features (bool): whether to add the one-hot accomodations features to the training data
    save_X_Y (bool): whether to save the train data into 2 separate files (X_train, Y_train) or in a unique file (train_vec)
    """
    train_df = data.train_df(mode, cluster='cluster_recurrent')
    test_df = data.test_df(mode, cluster='cluster_recurrent')

    path = f'dataset/preprocessed/cluster_recurrent/{mode}/dataset_regression'
    check_folder(path)

    devices_classes = ['mobile', 'desktop', 'tablet']
    actions_classes = ['show_impression', 'clickout item', 'interaction item rating', 'interaction item info',
           'interaction item image', 'interaction item deals', 'change of sort order', 'filter selection',
           'search for item', 'search for destination', 'search for poi']
    
    ## ======== TRAIN ======== ##
    # add the impressions as new interactions
    print('Adding impressions as new actions...')
    train_df, final_new_index = add_impressions_as_new_actions(train_df)
    print('Done!\n')

    # pad the sessions
    if pad_sessions_length > 0:
        print('Padding/truncating sessions...')
        train_df = pad_sessions(train_df, max_session_length=pad_sessions_length)
        print('Done!\n')

    if save_X_Y:
        print('Getting the last clickout of each session...')
        train_clickouts_df = get_last_clickout(train_df, index_name='index', rename_index='orig_index')
        train_clickouts_indices = train_clickouts_df.orig_index.values
        train_clickouts_indices.sort()
        print('Done!\n')

    # add the one-hot of the device
    print('Adding one-hot columns of device...', end=' ', flush=True)
    train_df = one_hot_df_column(train_df, 'device', classes=devices_classes)
    print('Done!\n')

    # add the one-hot of the action-type
    print('Adding one-hot columns of action_type...', end=' ', flush=True)
    train_df = one_hot_df_column(train_df, 'action_type', classes=actions_classes)
    print('Done!\n')

    TRAIN_LEN = train_df.shape[0]
    TRAIN_NAME = ''

    if save_X_Y:
        # set the columns to be placed in the labels file
        Y_COLUMNS = ['user_id','session_id','timestamp','step','reference']
    
        # join the accomodations one-hot features
        X_train_path = os.path.join(path, 'X_train.csv')
        if add_item_features:
            print('Joining the accomodations features...')
            add_accomodations_features(train_df.copy(), X_train_path, logic='skip', row_indices=train_clickouts_indices)
        else:
            # set the last clickouts to NaN and save the X dataframe
            backup_ref_serie = train_df.reference.values.copy()
            train_df.loc[train_clickouts_indices, 'reference'] = np.nan
            train_df.to_csv(X_train_path, index_label='orig_index', float_format='%.4f')
            train_df.reference = backup_ref_serie
            del backup_ref_serie
        
        Y_train_path = os.path.join(path, 'Y_train.csv')
        train_df = train_df[Y_COLUMNS]
        if add_item_features:
            add_accomodations_features(train_df.copy(), Y_train_path, logic='subset', row_indices=train_clickouts_indices)
        else:
            # set all clickouts to NaN except for the last clickouts and save the Y dataframe
            backup_ref_serie = train_df.loc[train_clickouts_indices].reference.copy()
            train_df.reference = np.nan
            train_df.loc[train_clickouts_indices, 'reference'] = backup_ref_serie
            train_df.to_csv(Y_train_path, index_label='orig_index', float_format='%.4f')

        # clean ram
        del train_clickouts_df
        del train_clickouts_indices
    else:
        TRAIN_NAME = 'train_vec.csv'
        train_path = os.path.join(path, TRAIN_NAME)
        train_df.to_csv(train_path, index_label='orig_index', float_format='%.4f')

    del train_df

    ## ======== TEST ======== ##
    print('Adding impressions as new actions...')
    test_df, _ = add_impressions_as_new_actions(test_df, final_new_index)
    print('Done!\n')

    # pad the sessions
    if pad_sessions_length > 0:
        print('Padding/truncating sessions...')
        test_df = pad_sessions(test_df, max_session_length=pad_sessions_length)
        print('Done!\n')

    print('Getting the last clickout of each session...')
    test_clickouts_df = get_last_clickout(test_df, index_name='index', rename_index='orig_index')
    test_clickouts_indices = test_clickouts_df.orig_index.values
    test_clickouts_indices.sort()
    print('Done!\n')

    # add the one-hot of the device
    print('Adding one-hot columns of device...', end=' ', flush=True)
    test_df = one_hot_df_column(test_df, 'device', classes=devices_classes)
    print('Done!\n')

    # add the one-hot of the action-type
    print('Adding one-hot columns of action_type...', end=' ', flush=True)
    test_df = one_hot_df_column(test_df, 'action_type', classes=actions_classes)
    print('Done!\n')

    TEST_LEN = test_df.shape[0]

    # join the accomodations one-hot features
    X_test_path = os.path.join(path, 'X_test.csv')
    if add_item_features:
        print('Joining the accomodations features...')
        add_accomodations_features(test_df.copy(), X_test_path, logic='skip', row_indices=test_clickouts_indices)
    else:
        # set the last clickouts to NaN and save the X dataframe
        backup_ref_serie = test_df.reference.values.copy()
        test_df.loc[test_clickouts_indices, 'reference'] = np.nan
        test_df.to_csv(X_test_path, index_label='orig_index', float_format='%.4f')
        #test_df.reference = backup_ref_serie
        del backup_ref_serie
    
    ## ======== CONFIG ======== ##
    # save the dataset config file that stores dataset length and the list of sparse columns
    features_cols = list(data.accomodations_one_hot().columns) if add_item_features else []    
    x_sparse_cols = devices_classes + actions_classes + features_cols
    datasetconfig.save_config(path, mode, cluster, TRAIN_LEN, TEST_LEN, train_name=TRAIN_NAME,
                            rows_per_sample=pad_sessions_length,
                            X_sparse_cols=x_sparse_cols, Y_sparse_cols=features_cols)

    
def create_dataset_for_classification(mode, cluster, pad_sessions_length=70):
    """
    pad_sessions_length (int): final length of sessions after padding/truncating
    add_item_features (bool): whether to add the one-hot accomodations features to the training data
    """
    train_df = data.train_df(mode, cluster='cluster_recurrent')
    test_df = data.test_df(mode, cluster='cluster_recurrent')

    path = f'dataset/preprocessed/cluster_recurrent/{mode}/dataset_classification'
    check_folder(path)

    devices_classes = ['mobile', 'desktop', 'tablet']
    actions_classes = ['show_impression', 'clickout item', 'interaction item rating', 'interaction item info',
           'interaction item image', 'interaction item deals', 'change of sort order', 'filter selection',
           'search for item', 'search for destination', 'search for poi']
    
    ## ======== TRAIN ======== ##
    # add the impressions as new interactions
    print('Adding impressions as new actions...')
    train_df, final_new_index = add_impressions_as_new_actions(train_df, drop_cols=['prices'])
    print('Done!\n')

    # pad the sessions
    if pad_sessions_length > 0:
        print('Padding/truncating sessions...')
        train_df = pad_sessions(train_df, max_session_length=pad_sessions_length)
        print('Done!\n')
    
    # print('Getting the last clickout of each session...')
    # train_clickouts_df = get_last_clickout(train_df, index_name='index', rename_index='orig_index')
    # train_clickouts_indices = train_clickouts_df.orig_index.values
    # train_clickouts_indices.sort()
    # print('Done!\n')

    # add the one-hot of the device
    print('Adding one-hot columns of device...', end=' ', flush=True)
    train_df = one_hot_df_column(train_df, 'device', classes=devices_classes)
    print('Done!\n')

    # add the one-hot of the action-type
    print('Adding one-hot columns of action_type...', end=' ', flush=True)
    train_df = one_hot_df_column(train_df, 'action_type', classes=actions_classes)
    print('Done!\n')

    # add the reference classes
    print('Adding references classes...')
    train_df, ref_classes = add_reference_classes(train_df, actiontype_col='clickout item', action_equals=1)
    print('Done!\n')
    
    TRAIN_LEN = train_df.shape[0]
    TRAIN_NAME = ''

    # set the columns to be placed in the labels file
    Y_COLUMNS = ['user_id','session_id','timestamp','step'] + ref_classes

    # join the accomodations one-hot features
    X_train_path = os.path.join(path, 'X_train.csv')
    
    # save the X dataframe without the reference classes
    train_df.drop(ref_classes + ['impressions','reference'], axis=1).to_csv(X_train_path, index_label='orig_index', float_format='%.4f')
    
    Y_train_path = os.path.join(path, 'Y_train.csv')
    train_df = train_df[Y_COLUMNS]
    # if add_item_features:
    #     add_accomodations_features(train_df.copy(), Y_train_path, logic='subset', row_indices=train_clickouts_indices)
    # else:

    # set all clickouts to NaN except for the last clickouts and save the Y dataframe
    train_df.to_csv(Y_train_path, index_label='orig_index', float_format='%.4f')

    # clean ram
    del train_df

    ## ======== TEST ======== ##
    print('Adding impressions as new actions...')
    test_df, _ = add_impressions_as_new_actions(test_df, final_new_index)
    print('Done!\n')

    # pad the sessions
    if pad_sessions_length > 0:
        print('Padding/truncating sessions...')
        test_df = pad_sessions(test_df, max_session_length=pad_sessions_length)
        print('Done!\n')

    # print('Getting the last clickout of each session...')
    # test_clickouts_df = get_last_clickout(test_df, index_name='index', rename_index='orig_index')
    # test_clickouts_indices = test_clickouts_df.orig_index.values
    # test_clickouts_indices.sort()
    # print('Done!\n')

    # add the one-hot of the device
    print('Adding one-hot columns of device...', end=' ', flush=True)
    test_df = one_hot_df_column(test_df, 'device', classes=devices_classes)
    print('Done!\n')

    # add the one-hot of the action-type
    print('Adding one-hot columns of action_type...', end=' ', flush=True)
    test_df = one_hot_df_column(test_df, 'action_type', classes=actions_classes)
    print('Done!\n')

    TEST_LEN = test_df.shape[0]

    # join the accomodations one-hot features
    X_test_path = os.path.join(path, 'X_test.csv')
    # if add_item_features:
    #     print('Joining the accomodations features...')
    #     add_accomodations_features(test_df.copy(), X_test_path, logic='skip', row_indices=test_clickouts_indices)
    # else:

    # save the test X dataframe without the reference column
    test_df.drop('reference', axis=1).to_csv(X_test_path, index_label='orig_index', float_format='%.4f')
    
    
    ## ======== CONFIG ======== ##
    # save the dataset config file that stores dataset length and the list of sparse columns
    x_sparse_cols = devices_classes + actions_classes
    datasetconfig.save_config(path, mode, cluster, TRAIN_LEN, TEST_LEN, train_name=TRAIN_NAME,
                            rows_per_sample=pad_sessions_length,
                            X_sparse_cols=x_sparse_cols, Y_sparse_cols=ref_classes)



# ======== POST-PROCESSING ========= #

def load_training_dataset_for_regression(mode):
    """ Load the one-hot dataset and return X_train, Y_train """
    path = f'dataset/preprocessed/cluster_recurrent/{mode}'
    X_path = os.path.join(path, 'X_train.csv')
    Y_path = os.path.join(path, 'Y_train.csv')

    X_train_df = pd.read_csv(X_path, index_col=0) #sparsedf.read(X_path, sparse_cols=X_sparsecols).set_index('orig_index')
    Y_train_df = pd.read_csv(Y_path, index_col=0) #sparsedf.read(Y_path, sparse_cols=Y_sparsecols).set_index('orig_index')

    #X_test_df = pd.read_csv(f'dataset/preprocessed/cluster_recurrent/{mode}/X_test.csv').set_index('orig_index')

    # turn the timestamp into the day of year
    X_train_df.timestamp = pd.to_datetime(X_train_df.timestamp, unit='s')
    X_train_df['dayofyear'] = X_train_df.timestamp.dt.dayofyear

    cols_to_drop_in_X = ['user_id','session_id','timestamp','step','platform','city','current_filters']
    cols_to_drop_in_Y = ['session_id','user_id','timestamp','step']
    
    # scale the dataframe
    #X_train_df = scale_dataframe(X_train_df, ['impression_price'])
    scaler = MinMaxScaler()
    X_train_df.loc[:,~X_train_df.columns.isin(cols_to_drop_in_X)] = scaler.fit_transform(
        X_train_df.drop(cols_to_drop_in_X, axis=1).astype('float64').values)

    # get the tensors and drop currently unused columns
    X_train = sessions2tensor(X_train_df, drop_cols=cols_to_drop_in_X)
    print('X_train:', X_train.shape)

    Y_train = sessions2tensor(Y_train_df, drop_cols=cols_to_drop_in_Y)
    print('Y_train:', Y_train.shape)

    # X_test = sessions2tensor(X_test_df, drop_cols=['user_id','session_id','step','reference','platform','city','current_filters'], return_index=False)
    # print('X_test:', X_test.shape)

    # X_train.impression_price = X_train.impression_price.fillna(value=0)
    # X_test.impression_price = X_test.impression_price.fillna(value=0)
    
    return X_train, Y_train #, X_test


def get_session_groups_indices_df(X_df, Y_df, cols_to_group=['user_id','session_id'], indices_col_name='intrctns_indices'):
    """
    Return a dataframe with columns 'user_id', 'session_id', 'intrctns_indices'. This is used to retrieve the
    interaction indices from a particular session id of a user
    """
    return X_df.groupby(cols_to_group).apply(lambda r: pd.Series({indices_col_name: r.index.values})).reset_index()



if __name__ == "__main__":
    mode = menu.mode_selection()
    cluster = 'cluster_recurrent'

    dataset_type = menu.single_choice('Choose which type of dataset you want to create:',
                                ['For regression', 'For classification'],
                                [lambda: 'regression', lambda: 'classification'])

    print()
    sess_length = int(input('Insert the desired sessions length, -1 to not to pad/truncate the sessions: '))
    
    if dataset_type == 'regression':
        save_XY = menu.single_choice('Choose the dataset structure:',
                                    ['X_train, Y_train for training', 'X_test for testing',
                                        'train_vec for training, X_test for testing'],
                                    [lambda: True, lambda: False])
        item_feat_choice = menu.yesno_choice('Do you want to add item features?', lambda: True, lambda: False)
        create_dataset_for_regression(mode, cluster, pad_sessions_length=sess_length,
                                    add_item_features=item_feat_choice, save_X_Y=save_XY)
    
    elif dataset_type == 'classification':
        create_dataset_for_classification(mode, cluster, pad_sessions_length=sess_length)
