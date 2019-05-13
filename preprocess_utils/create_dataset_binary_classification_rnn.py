import sys
import os
sys.path.append(os.getcwd())

import data
import utils.menu as menu
import numpy as np
import utils.df as df_utils
import preprocess_utils.sessions_to_predict as sess2predict
from utils.check_folder import check_folder
import utils.datasetconfig as datasetconfig

from clusterize.cluster_recurrent import ClusterRecurrent
from clusterize.cluster_up_to_len6 import ClusterUpToLen6

from extract_features.reference_position_in_next_clickout_impressions import ReferencePositionInNextClickoutImpressions
#from extract_features.global_interactions_popularity import GlobalInteractionsPopularity
from extract_features.global_clickout_popularity import GlobalClickoutPopularity
from extract_features.reference_price_in_next_clickout import ReferencePriceInNextClickout
from extract_features.average_price_in_next_clickout import AveragePriceInNextClickout
from extract_features.reference_price_position_in_next_clickout import ReferencePricePositionInNextClickout

import preprocess_utils.session2vec as sess2vec


def create_dataset_for_binary_classification(mode, cluster, pad_sessions_length, add_item_features, add_dummy_actions=False,
                                    features=[], only_test=False, resample=False, one_target_per_session=True):
    """
    pad_sessions_length (int): final length of sessions after padding/truncating
    add_item_features (bool): whether to add the accomodations features as additional columns
    add_dummy_actions (bool): whether to add dummy interactions representing the impressions before each clickout
    features (list): list of classes (inheriting from FeatureBase) that will provide additional features to be joined
    only_test (bool): whether to create only the test dataset (useful to make predictions with a pre-trained model)
    resample (bool): whether to resample to reduce the unbalance between classes
    """
    
    path = f'dataset/preprocessed/{cluster}/{mode}/dataset_binary_classification_p{pad_sessions_length}'
    check_folder(path)

    def create_ds_class(df, path, for_train, add_dummy_actions=add_dummy_actions, pad_sessions_length=pad_sessions_length, 
                        add_item_features=add_item_features, resample=resample, one_target_per_session=one_target_per_session,
                        new_row_index=99000000):
        """ Create X and Y dataframes if for_train, else only X dataframe.
            Return the number of rows of the new dataframe and the final index
        """

        ds_type = 'train' if for_train else 'test'
        devices_classes = ['mobile', 'desktop', 'tablet']
        actions_classes = ['show_impression', 'clickout item', 'interaction item rating', 'interaction item info',
                'interaction item image', 'interaction item deals', 'change of sort order', 'filter selection',
                'search for item', 'search for destination', 'search for poi']
        
        # merge the features
        print('Merging the features...')
        for f in features:
            df = f.join_to(df)
        print('Done!\n')
    
        # add the impressions as new interactions
        if add_dummy_actions:
            print('Adding impressions as new actions...')
            df, new_row_index = sess2vec.add_impressions_as_new_actions(df, drop_cols=['prices'], new_rows_starting_index=new_row_index)
            print('Done!\n')
        else:
            df = df.drop('prices', axis=1)

        # pad the sessions
        if pad_sessions_length > 0:
            print('Padding/truncating sessions...')
            df = sess2vec.pad_sessions(df, max_session_length=pad_sessions_length)
            print('Done!\n')
    
        # print('Getting the last clickout of each session...')
        # print('Done!\n')

        # add the one-hot of the device
        # df = df.drop('device', axis=1)
        print('Adding one-hot columns of device...', end=' ', flush=True)
        df = sess2vec.one_hot_df_column(df, 'device', classes=devices_classes)
        print('Done!\n')

        # add the one-hot of the action-type
        print('Adding one-hot columns of action_type...', end=' ', flush=True)
        df = sess2vec.one_hot_df_column(df, 'action_type', classes=actions_classes)
        print('Done!\n')

        # add the reference classes if TRAIN
        if for_train:
            print('Adding references classes...')
            df = sess2vec.add_reference_binary_labels(df, actiontype_col='clickout item', action_equals=1)
            ref_classes = ['ref_class']
            print('Done!\n')
        else:
            ref_classes = []

        # remove the impressions column
        df = df.drop('impressions', axis=1)

        if for_train and resample:
            # resample the dataset to balance the classes
            resample_perc = 0.5 / df.ref_class.mean()
            print('resample perc:', resample_perc)
            df = df_utils.resample_sessions(df, by=resample_perc, when=df_utils.ref_class_is_1)

        # join the accomodations one-hot features
        if add_item_features:
            print('Adding accomodations features...')
            df = sess2vec.merge_reference_features(df, pad_sessions_length)

        X_LEN = df.shape[0]

        # save the X dataframe without the labels (reference classes)
        x_path = os.path.join(path, 'X_{}.csv'.format(ds_type))
        print('Saving X {}...'.format(ds_type), end=' ', flush=True)
        df.drop(ref_classes, axis=1).to_csv(x_path, index_label='orig_index', float_format='%.4f')
        print('Done!\n')

        if for_train:
            # set the columns to be placed in the labels file
            Y_COLUMNS = ['user_id','session_id','timestamp','step'] + ref_classes
            df = df[Y_COLUMNS]

            # take only the target rows from y
            if one_target_per_session:
                df = df.iloc[np.arange(-1,len(df),pad_sessions_length)[1:]]

            # save the Y dataframe
            y_path = os.path.join(path, 'Y_train.csv')
            print('Saving Y_train...', end=' ', flush=True)
            df.to_csv(y_path, index_label='orig_index', float_format='%.4f')
            print('Done!\n')
            
        return X_LEN, new_row_index

    final_new_index = 99000000
    TRAIN_LEN = 0
    
    # remove the sessions to be not predicted and move into the train
    print('Removing sessions in test not to be predicted...')
    test_df = data.test_df(mode, cluster)
    test_df, sessions_not_to_predict = sess2predict.find(test_df)

    if not only_test:
        ## ======== TRAIN ======== ##
        train_df = data.train_df(mode, cluster)
        train_df = train_df.append(sessions_not_to_predict)
        TRAIN_LEN, final_new_index = create_ds_class(train_df, path, for_train=True, new_row_index=final_new_index)
        del train_df

    ## ======== TEST ======== ##
    TEST_LEN, _ = create_ds_class(test_df, path, for_train=False, new_row_index=final_new_index)
    del test_df

    ## ======== CONFIG ======== ##
    # save the dataset config file that stores dataset length and the list of sparse columns
    #x_sparse_cols = devices_classes + actions_classes
    datasetconfig.save_config(path, mode, cluster, TRAIN_LEN, TEST_LEN,
                                rows_per_sample=pad_sessions_length)
                            #X_sparse_cols=x_sparse_cols, Y_sparse_cols=ref_classes)



if __name__ == "__main__":
        
    mode = menu.mode_selection()
    #cluster_name = 'cluster_recurrent'
    cluster = menu.single_choice('Which cluster?', ['cluster recurrent','cluster recurrent len <= 6'],
                                    callbacks=[lambda: ClusterRecurrent, lambda: ClusterUpToLen6])
    c = cluster()

    # create the cluster
    cluster_choice = menu.yesno_choice('Do you want to create the cluster?', lambda: True, lambda: False)
    if cluster_choice:
        print('Creating the cluster...')
        c.save(mode)
        print()

    only_test = False
    if mode != 'small':
        only_test = menu.yesno_choice('Do you want to create only the test dataset?', lambda: True, lambda: False)
    
    sess_length = int(input('Insert the desired sessions length, -1 to not to pad/truncate the sessions: '))

    features_to_join = [
        ReferencePositionInNextClickoutImpressions,
        GlobalClickoutPopularity,
        #GlobalInteractionsPopularity,
        AveragePriceInNextClickout,
        ReferencePriceInNextClickout,
        ReferencePricePositionInNextClickout,
    ]
    features = []
    # create the features to join
    for f in features_to_join:
        feat = f(mode, c.name)
        feat.save_feature()
        features.append(feat)

    # create the tensors dataset
    print('Creating the dataset ({})...'.format(mode))
    create_dataset_for_binary_classification(mode, c.name, pad_sessions_length=sess_length, resample=False,
                                                add_item_features=True, features=features, only_test=only_test)

