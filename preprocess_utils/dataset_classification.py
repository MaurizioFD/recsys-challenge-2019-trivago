from multiprocessing import Process, Queue
from utils.check_folder import check_folder
import numpy as np
from sklearn.preprocessing import MultiLabelBinarizer
import data
import pandas as pd
from tqdm.auto import tqdm
import math
tqdm.pandas()
from preprocess_utils.session2vec import one_hot_df_column

"""
creates train and test dataframe that can be used for classification,
starting from train_df and test_df of the specified cluster and mode

the resulting dataframe have structure:
user_id | session_id | accomodation_id | feature_1 | ....  | feature_n | label

the accomodation_ids are the ones showing up in the impressions
label is 1 in case the accomodation is the one clicked in the clickout
"""

# import os

# os.chdir("../")
# print(os.getcwd())


def build_dataset(mode, cluster='no_cluster', algo='xgboost'):
    # build the onehot of accomodations attributes
    def one_hot_of_accomodation(accomodations_df):
        accomodations_df.properties = accomodations_df.properties.progress_apply(
            lambda x: x.split('|') if isinstance(x, str) else x)
        accomodations_df.fillna(value='', inplace=True)
        mlb = MultiLabelBinarizer()
        one_hot_features = mlb.fit_transform(accomodations_df.properties)
        one_hot_accomodations_df = pd.DataFrame(
            one_hot_features, columns=mlb.classes_)
        one_hot_accomodations_df.columns = [
            'accomodation feature ' + str(col) for col in one_hot_accomodations_df.columns]
        attributes_df = pd.concat([accomodations_df.drop(
            'properties', axis=1), one_hot_accomodations_df], axis=1)
        return attributes_df
        # return accomodations_df

    def build_popularity(df):
        popularity = {}
        df = df[(df['action_type'] == 'clickout item')
                & (~df['reference'].isnull())]
        clicked_references = list(map(int, list(df['reference'].values)))

        # FREQUENCY EDIT - in case of presence of 'frequence' column in dataset
        if has_frequency_columns:
            frequence = list(map(int, list(df['frequence'].values)))

            for i in tqdm(range(len(clicked_references))):
                e = clicked_references[i]
                f = frequence[i]
                if int(e) in popularity:
                    popularity[int(e)] += int(f)
                else:
                    popularity[int(e)] = int(f)
        else:
            # Case with no 'frequence' column in dataset
            popularity = {}
            df = df[(df['action_type'] == 'clickout item')
                    & (~df['reference'].isnull())]
            clicked_references = list(map(int, list(df['reference'].values)))
            for e in tqdm(clicked_references):
                if int(e) in popularity:
                    popularity[int(e)] += 1
                else:
                    popularity[int(e)] = 1

        return popularity

    def get_frenzy_and_avg_time_per_step(x, clk):
        if len(x) > 0:
            session_actions_num = int(clk.step.values[0])

            clickout_tm = int(clk.timestamp.values[0])
            time_length = clickout_tm - int(x.head(1).timestamp.values[0])

            mean_time_per_step = round(
                time_length / (session_actions_num - 1), 2)

            var = 0
            prev_tm = 0

            for i in x.index:
                curr_tm = int(x.at[i, 'timestamp'])

                if prev_tm == 0:
                    prev_tm = curr_tm
                else:
                    var += (mean_time_per_step - (curr_tm - prev_tm)) ** 2
                    prev_tm = curr_tm

            # summing var wrt of clickout
            var += (mean_time_per_step - (clickout_tm - prev_tm)) ** 2

            var = round((var / session_actions_num) ** 0.5, 2)
        else:
            var = -1
            mean_time_per_step = -1

        return mean_time_per_step, var

    def func(x):
        y = x[(x['action_type'] == 'clickout item')]
        if len(y) > 0:
            clk = y.tail(1)
            head_index = x.head(1).index
            impr = clk['impressions'].values[0].split('|')

            # !! considering only the past for all non-test sessions! !!
            x = x.loc[head_index.values[0]:clk.index.values[0] - 1]

            # features
            features = {'label': [], 'times_impression_appeared': [],
                        'time_elapsed_from_last_time_impression_appeared': [], 'impression_position': [],
                        'steps_from_last_time_impression_appeared': [], 'kind_action_reference_appeared_last_time': [],
                        'price': [], 'price_position': [],
                        'item_id': [], 'popularity': [], 'impression_position_wrt_last_interaction': [],
                        'impression_position_wrt_second_last_interaction': [],
                        'clickout_item_session_ref_this_impr': list(np.zeros(len(impr), dtype=np.int)),
                        'interaction_item_deals_session_ref_this_impr': list(np.zeros(len(impr), dtype=np.int)),
                        'interaction_item_image_session_ref_this_impr': list(np.zeros(len(impr), dtype=np.int)),
                        'interaction_item_info_session_ref_this_impr': list(np.zeros(len(impr), dtype=np.int)),
                        'interaction_item_rating_session_ref_this_impr': list(np.zeros(len(impr), dtype=np.int)),
                        'search_for_item_session_ref_this_impr': list(np.zeros(len(impr), dtype=np.int)),
                        'clickout_item_session_ref_not_in_impr': 0,
                        'interaction_item_deals_session_ref_not_in_impr': 0,
                        'interaction_item_image_session_ref_not_in_impr': 0,
                        'interaction_item_info_session_ref_not_in_impr': 0,
                        'interaction_item_rating_session_ref_not_in_impr': 0,
                        'search_for_item_session_ref_not_in_impr': 0, 'session_length_in_step': 0,
                        'device': '', 'filters_when_clickout': '', 'session_length_in_time': 0,
                        'sort_order_active_when_clickout': 'sorted by default'}

            features['session_length_in_step'] = int(clk.step.values[0])
            features['device'] = clk['device'].values[0]

            if isinstance(clk.current_filters.values[0], str):
                features['filters_when_clickout'] = '|'.join(
                    [x + ' filter active when clickout' for x in clk.current_filters.values[0].split('|')])
            else:
                features['filters_when_clickout'] = 'no filter when clickout'

            if len(x) > 0:
                features['session_length_in_time'] = int(clk['timestamp'].values[0]) - int(
                    x.head(1)['timestamp'].values[0])

                features['timing_last_action_before_clk'] = int(clk.timestamp.values[0]) - int(
                    x.tail(1).timestamp.values[0])
            else:
                features['session_length_in_time'] = -1
                features['timing_last_action_before_clk'] = -1

            features['time_per_step'], features['frenzy_factor'] = get_frenzy_and_avg_time_per_step(
                x, clk)

            poi_search_df = x[x.action_type == 'search for poi']
            if poi_search_df.shape[0] > 0:
                last_poi_search_step = int(
                    poi_search_df.tail(1).step.values[0])
                features['search_for_poi_distance_from_last_clickout'] = int(
                    clk.step.values[0]) - last_poi_search_step
                features['search_for_poi_distance_from_first_action'] = last_poi_search_step - int(
                    x.head(1).step.values[0])
            else:
                features['search_for_poi_distance_from_last_clickout'] = -1
                features['search_for_poi_distance_from_first_action'] = -1

            sort_change_df = x[x.action_type == 'change of sort order']
            if sort_change_df.shape[0] > 0:
                sort_change_step = int(sort_change_df.tail(1).step.values[0])
                features['change_sort_order_distance_from_last_clickout'] = int(
                    clk.step.values[0]) - sort_change_step
                features['change_sort_order_distance_from_first_action'] = sort_change_step - int(
                    x.head(1).step.values[0])
            else:
                features['change_sort_order_distance_from_last_clickout'] = -1
                features['change_sort_order_distance_from_first_action'] = -1

            impr = clk['impressions'].values[0].split('|')
            prices = list(map(int, clk['prices'].values[0].split('|')))
            sorted_prices = prices.copy()
            sorted_prices.sort()

            change_of_sort_order_actions = x[x['action_type']
                                             == 'change of sort order']
            if len(change_of_sort_order_actions) > 0:
                change_of_sort_order_actions = change_of_sort_order_actions.tail(
                    1)
                features['sort_order_active_when_clickout'] = 'sort by ' + \
                                                              str(change_of_sort_order_actions['reference'].values[0])

            references = x['reference'].values
            actions = x['action_type'].values

            # FREQUENCY EDIT - in case of presence of 'frequence' column in dataset
            if has_frequency_columns:
                frequency = x['frequence'].values

            position_of_last_refence_on_impressions = None
            position_of_second_last_refence_on_impressions = None

            num_references = x[pd.to_numeric(x['reference'], errors='coerce').notnull()].drop_duplicates(
                subset=['reference'], keep='last')

            if num_references.shape[0] > 0:
                last_num_reference = num_references.tail(1).reference.values[0]
                if last_num_reference in impr:
                    position_of_last_refence_on_impressions = impr.index(
                        last_num_reference) + 1

            if num_references.shape[0] > 1:
                second_last_num_reference = num_references.tail(
                    2).reference.values[0]
                if second_last_num_reference in impr:
                    position_of_second_last_refence_on_impressions = impr.index(
                        second_last_num_reference) + 1

            not_to_cons_indices = []
            count = 0
            # Start features impressions
            for i in impr:
                indices = np.where(references == str(i))[0]

                not_to_cons_indices += list(indices)
                features['impression_position'].append(count + 1)

                # Feature position wrt last interaction: if not exists a numeric reference in impressions,
                # default value is -999 (can't be -1 because values range is -24 to 24)
                if position_of_last_refence_on_impressions is not None:
                    features['impression_position_wrt_last_interaction'].append(
                        count + 1 - position_of_last_refence_on_impressions)
                else:
                    features['impression_position_wrt_last_interaction'].append(
                        -999)

                if position_of_second_last_refence_on_impressions is not None:
                    features['impression_position_wrt_second_last_interaction'].append(
                        count + 1 - position_of_second_last_refence_on_impressions)
                else:
                    features['impression_position_wrt_second_last_interaction'].append(
                        -999)

                features['price'].append(prices[count])
                features['price_position'].append(
                    sorted_prices.index(prices[count]))
                features['item_id'].append(int(i))

                if has_frequency_columns:
                    cc = 0
                    for jj in indices:
                        cc += int(frequency[jj])

                    features['times_impression_appeared'].append(cc)
                else:
                    features['times_impression_appeared'].append(len(indices))

                if len(indices) > 0:
                    row_reference = x.head(indices[-1] + 1).tail(1)
                    features['steps_from_last_time_impression_appeared'].append(
                        len(x) - indices[-1])
                    features['time_elapsed_from_last_time_impression_appeared'].append(
                        int(clk['timestamp'].values[0] - row_reference['timestamp'].values[0]))
                    features['kind_action_reference_appeared_last_time'].append(
                        'last_time_impression_appeared_as_' + row_reference['action_type'].values[0].replace(' ',
                                                                                                             '_'))

                    for idx in indices:
                        row_reference = x.head(idx + 1).tail(1)
                        if has_frequency_columns:
                            freq = int(row_reference.frequence.values[0])
                        else:
                            freq = 1
                        features['_'.join(row_reference.action_type.values[0].split(
                            ' ')) + '_session_ref_this_impr'][count] += freq

                else:
                    features['steps_from_last_time_impression_appeared'].append(
                        0)
                    features['time_elapsed_from_last_time_impression_appeared'].append(
                        -1)
                    features['kind_action_reference_appeared_last_time'].append(
                        'last_time_reference_did_not_appeared')

                popularity = 0
                if int(i) in popularity_df:
                    popularity = popularity_df[int(i)]
                if clk['reference'].values[0] == i:
                    features['label'].append(1)
                    features['popularity'].append(popularity - 1)
                else:
                    features['label'].append(0)
                    features['popularity'].append(popularity)

                count += 1

            to_cons_indices = list(
                set(list(range(len(actions)))) - set(not_to_cons_indices))
            if has_frequency_columns:
                for ind in to_cons_indices:
                    if (actions[ind].replace(' ', '_') + '_session_ref_not_in_impr') in features:
                        features[actions[ind].replace(
                            ' ', '_') + '_session_ref_not_in_impr'] += int(frequency[ind])
            else:
                for ind in to_cons_indices:
                    if (actions[ind].replace(' ', '_') + '_session_ref_not_in_impr') in features:
                        features[actions[ind].replace(
                            ' ', '_') + '_session_ref_not_in_impr'] += 1

            return pd.DataFrame(features)

    def construct_features(df, q):
        dataset = df.groupby(['user_id', 'session_id']).progress_apply(func)
        q.put(dataset)

    def save_features(dataset, count_chunk, target_session_id, target_user_id):
        # print('started onehot chunk {}'.format(count_chunk))
        if len(dataset) > 0:
            dataset = dataset.reset_index().drop(['level_2'], axis=1)

            col = dataset['filters_when_clickout']
            mid = col.apply(lambda x: x.split('|') if isinstance(x, str) else x)
            mid.fillna(value='', inplace=True)
            mlb = MultiLabelBinarizer(classes=(list(poss_filters)))
            oh = mlb.fit_transform(mid)
            one_hot = pd.DataFrame(oh, columns=mlb.classes_)
            dataset = dataset.drop(['filters_when_clickout'], axis=1)
            dataset = pd.concat([dataset, one_hot], axis=1)

            # if the algorithm is xgboost, get the onehot of all the features. otherwise leave it categorical
            if algo == 'xgboost':
                dataset = one_hot_df_column(dataset, 'device', list(poss_devices))
                dataset = one_hot_df_column(dataset, 'kind_action_reference_appeared_last_time', list(poss_actions))
                dataset = one_hot_df_column(dataset, 'sort_order_active_when_clickout', list(poss_sort_orders))

            dataset = pd.merge(dataset, one_hot_accomodation, on=['item_id'])

            if 'item_id' in dataset.columns.values:
                dataset = dataset.drop(['item_id'], axis=1)
            if 'Unnamed: 0' in dataset.columns.values:
                dataset = dataset.drop(['Unnamed: 0'], axis=1)

            if algo == 'xgboost':
                dataset = dataset.sort_values(by=['user_id', 'session_id'])

            # print('started saving chunk {}'.format(count_chunk))
            test = dataset[dataset['user_id'].isin(
                target_user_id) & dataset['session_id'].isin(target_session_id)]
            train = dataset[(dataset['user_id'].isin(
                target_user_id) & dataset['session_id'].isin(target_session_id)) == False]

            if count_chunk == 1:
                path = 'dataset/preprocessed/{}/{}/{}/classification_train.csv'.format(
                    cluster, mode, algo)
                check_folder(path)
                train.to_csv(path)

                path = 'dataset/preprocessed/{}/{}/{}/classification_test.csv'.format(
                    cluster, mode, algo)
                check_folder(path)
                test.to_csv(path)
            else:
                with open('dataset/preprocessed/{}/{}/{}/classification_train.csv'.format(cluster, mode, algo), 'a') as f:
                    train.to_csv(f, header=False)
                with open('dataset/preprocessed/{}/{}/{}/classification_test.csv'.format(cluster, mode, algo), 'a') as f:
                    test.to_csv(f, header=False)

        print('chunk {} over {} completed'.format(count_chunk, math.ceil(
            len(session_indices)/session_to_consider_in_chunk)))

    train = data.train_df(mode=mode, cluster=cluster)
    test = data.test_df(mode=mode, cluster=cluster)
    target_indices = data.target_indices(mode=mode, cluster=cluster)
    target_user_id = test.loc[target_indices]['user_id'].values
    target_session_id = test.loc[target_indices]['session_id'].values

    full = pd.concat([train, test])

    has_frequency_columns = False
    if 'frequence' in full.columns.values:
        has_frequency_columns = True

    del train
    del test

    accomodations_df = data.accomodations_df()
    one_hot_accomodation = one_hot_of_accomodation(accomodations_df)
    one_hot_accomodation = one_hot_accomodation.fillna(0)

    popularity_df = build_popularity(full)

    poss_filters = []
    for f in full[~full['current_filters'].isnull()]['current_filters'].values:
        poss_filters += [x +
                         ' filter active when clickout' for x in f.split('|')]
    poss_filters = set(poss_filters + ['no filter when clickout'])
    poss_devices = set(list(full['device'].values))
    poss_sort_orders = set(list(full[full['action_type'] == 'change of sort order'].reference.values))
    poss_sort_orders = [x for x in poss_sort_orders if isinstance(x, str)]
    poss_sort_orders = set(['sort by ' + x for x in poss_sort_orders] + ['sorted by default'])

    poss_actions = {'last_time_reference_did_not_appeared', 'last_time_impression_appeared_as_clickout_item',
                    'last_time_impression_appeared_as_interaction_item_deals',
                    'last_time_impression_appeared_as_interaction_item_image',
                    'last_time_impression_appeared_as_interaction_item_info',
                    'last_time_impression_appeared_as_interaction_item_rating',
                    'last_time_impression_appeared_as_search_for_item'}

    # build in chunk
    # avoid session truncation, explicitly specify how many session you want in a chunk
    count_chunk = 0
    session_to_consider_in_chunk = 200
    full = full.reset_index(drop=True)
    session_indices = list(
        full[['user_id']].drop_duplicates(keep='last').index.values)

    # create the dataset in parallel threads: one thread saves, the other create the dataset for the actual group
    p2 = None
    lower_index = full.head(1).index.values[0]
    session_indices_to_iterate_in = session_indices[session_to_consider_in_chunk:len(
        session_indices):session_to_consider_in_chunk]
    session_indices_to_iterate_in.append(
        session_indices[-1]) if session_indices[-1] != session_indices_to_iterate_in[-1] else session_indices_to_iterate_in
    for idx in session_indices_to_iterate_in:
        # print('lower index {} upper index {}'.format(lower_index, idx))
        gr = full.loc[lower_index:idx]
        lower_index = idx + 1
        q = Queue()
        p1 = Process(target=construct_features, args=(gr, q,))
        p1.start()
        if p2 != None:
            p2.join()
        features = q.get()
        p1.join()
        count_chunk += 1
        if len(features) > 0:
            p2 = Process(target=save_features, args=(
                features, count_chunk, target_session_id, target_user_id,))
            p2.start()


if __name__ == "__main__":
    build_dataset(mode='full', cluster='no_cluster', algo='xgboost')
