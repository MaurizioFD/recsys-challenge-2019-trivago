from extract_features.feature_base import FeatureBase
import data
import pandas as pd
from tqdm.auto import tqdm
import numpy as np

from preprocess_utils.last_clickout_indices import expand_impressions
from preprocess_utils.last_clickout_indices import find as find_last_clickout


class PastFutureSessionFeatures(FeatureBase):
    """
    say for each session the platform nationality and the city of the platform
    | user_id | session_id |


    feature description: (valid either for past / future sessions.
    If more available, the closes session to the current one will be considered.

    # PAST SESSIONS #
    past_times_interacted_impr: the number of times user interacted with impressions in past sessions

    past_session_num: number of sessions of the past
    past_closest_action_involving_impression: the kind of closest actions with which the user interacted with
                                      the impression in the session
    past_time_from_closest_interaction_impression: the time passed from the beginning of the current session in seconds
    past_mean_price_clickout : the averaged prices with which the user clicked during all past sessions
    past_mean_price_pos_clickout : the averaged price position with which the user clicked during all past sessions
    past_actions_involving_impression_session_clickout_item |
      past_actions_involving_impression_session_interaction_item_deals | ...
      | past_actions_involving_impression_session_no_action : the kind of closest actions with which the user interacted
                                                         with the impression in other sessions
    past_mean_price_interacted: average price with which the user interacted (only interacted)
    past_mean_cheap_pos_interacted : average price position with which the user interacted (only interacted)
    past_mean_pos: the averaged position of impression with which the user clicked during all past sessions
    past_pos_closest_reference: the position of the closest element clicked in past session belonging
    (None if not belonging to the current session impression
    past_position_impression_changed_closest_clickout: 1 if impressions changed wrt the clickout, 0 else

    # FUTURE SESSIONS #
    future_times_interacted_impr: the number of times user interacted with the session

    future_session_num: number of sessions of the past
    future_closest_action_involving_impression: the kind of closest actions with which the user interacted with
                                      the impression in the session
    future_time_from_closest_interaction_impression: the time passed from the beginning of the current session in seconds
    future_mean_price_clickout : the averaged prices with which the user clicked during all past sessions
    future_mean_price_pos_clickout : the averaged price position with which the user clicked during all past sessions
    future_actions_involving_impression_session_clickout_item |
      future_actions_involving_impression_session_interaction_item_deals | ...
      | future_actions_involving_impression_session_no_action : the kind of closest actions with which the user interacted
                                                         with the impression in other sessions
    future_mean_price_interacted: average price with which the user interacted (only interacted)
    future_mean_cheap_pos_interacted : average price position with which the user interacted (only interacted)
    future_mean_pos: the averaged position of impression with which the user clicked during all past sessions
    future_pos_closest_reference: the position of the closest element clicked in past session belonging
    (None if not belonging to the current session impression
    future_position_impression_changed_closest_clickout: 1 if impressions changed wrt the clickout, 0 else
    """

    def __init__(self, mode, cluster='no_cluster'):
        name = 'past_session_features'
        super(PastFutureSessionFeatures, self).__init__(
            name=name, mode=mode, cluster=cluster)

        # Feature initialization
        self.features = {'past_times_interacted_impr': [], 'past_session_num': [],
                         'past_time_from_closest_interaction_impression': [],
                         'past_times_user_interacted_impression': [],
                         'past_actions_involving_impression_session_clickout_item': [],
                         'past_actions_involving_impression_session_item_image': [],
                         'past_actions_involving_impression_session_item_rating': [],
                         'past_actions_involving_impression_session_item_deals': [],
                         'past_actions_involving_impression_session_item_info': [],
                         'past_actions_involving_impression_session_search_for_item': [],
                         'past_actions_involving_impression_session_no_action': [],
                         'past_mean_price_interacted': [], 'past_mean_cheap_pos_interacted': [], 'past_mean_pos': [],
                         'past_pos_closest_reference': [], 'past_position_impression_changed_closest_clickout': [],
                         'future_times_interacted_impr': [], 'future_session_num': [],
                         'future_time_from_closest_interaction_impression': [],
                         'future_times_user_interacted_impression': [],
                         'future_actions_involving_impression_session_clickout_item': [],
                         'future_actions_involving_impression_session_item_image': [],
                         'future_actions_involving_impression_session_item_rating': [],
                         'future_actions_involving_impression_session_item_deals': [],
                         'future_actions_involving_impression_session_item_info': [],
                         'future_actions_involving_impression_session_search_for_item': [],
                         'future_actions_involving_impression_session_no_action': [],
                         'future_mean_price_interacted': [], 'future_mean_cheap_pos_interacted': [],
                         'future_mean_pos': [],
                         'future_pos_closest_reference': [],
                         'future_position_impression_changed_closest_clickout': []}

    def extract_feature(self):
        """
        Computes all user features.
        Must distinsuish between past sessions and future sessions, and for each compute same features.
        This will help understand the moves of the user through the impressions
        """

        train_df = data.train_df(mode='full', cluster=self.cluster)
        test_df = data.test_df(mode='full', cluster=self.cluster)
        test_df = test_df.fillna(0)
        df = pd.concat([train_df, test_df])
        df.sort_values(by=['user_id', 'session_id', 'timestamp'], inplace=True)
        df = df.reset_index(drop=True)

        i = 0

        idxs_click = find_last_clickout(df, sort=False)

        users = df.user_id.values

        pbar = tqdm(total=len(idxs_click))

        # I will need a copy when iterating later
        idx_to_compute = idxs_click.copy()

        while i < idxs_click[-1]:
            initial_i = i

            user = df.at[i, 'user_id']

            # Get all user sessions indices
            for u in users[i:]:
                if u != user:
                    break
                i += 1

            # Now i start creating the features for every session

            sessions_user_idxs = []
            while len(idx_to_compute)>0 and idx_to_compute[0] < i:
                sessions_user_idxs += [idx_to_compute.pop(0)]
            sessions_count = len(sessions_user_idxs)

            if sessions_count > 1:
                if sessions_count > 3:
                    print('Having {} sessions for user {}'.format(sessions_count, user))

                # Start computing features: keeping the lasst clickouts where to iterate for getting features
                user_sessions_df = df.iloc[sessions_user_idxs, :]

                df_only_user = df[initial_i:i]

                # Iterating over clickouts to predict of session: computing features
                for idx, row in user_sessions_df.iterrows():
                    curr_session = row.session_id

                    # Get a session, get the impressions
                    impressions = list(map(str, row.impressions.split('|')))

                    df_samecity = df_only_user  # [df_only_user.city == row.city]
                    idx = list(df_samecity.session_id.values).index(curr_session)
                    idx_session_initial = df_samecity.index.values[idx]
                    idx_session_final = df_samecity.index.values[
                        len(df_samecity) - 1 - list(df_samecity.session_id.values)[::-1].index(curr_session)]

                    if df_samecity.index.values[0] < idx_session_initial:
                        self.compute_past_sessions_feat(
                            df_samecity[:idx_session_initial][df_only_user.city == row.city], impressions,
                            int(df_only_user.at[initial_i, 'timestamp']))
                    else:
                        self.add_empty_features(impressions, 'past')

                    tm_clk = int(row['timestamp'])
                    df_samecity = df_samecity[df_samecity.index > idx_session_final]

                    df_samecity = df_samecity[df_samecity.city == row.city]
                    if len(df_samecity) > 0:
                        self.compute_future_sessions_feat(df_samecity, impressions,
                                                          tm_clk)
                    else:
                        self.add_empty_features(impressions, 'future')

            else:
                # Return all features -1, if at least a session exists
                if sessions_count == 1:
                    # Case one session for one user:
                    clk_idx = sessions_user_idxs[0]
                    impressions = df.at[clk_idx, 'impressions'].split('|')
                    self.add_empty_features(impressions, 'both')

            pbar.update(sessions_count)

        pbar.close()

        df = expand_impressions(df.iloc[idxs_click, :][['user_id', 'session_id', 'reference', 'impressions']])

        print('Tot len of df is {}'.format(len(df)))
        print(len(self.features['past_actions_involving_impression_session_item_deals']))

        for key in self.features.keys():
            print(key, len(self.features[key]))
            df[key] = self.features[key]

        df.drop(['index', 'reference'], axis=1, inplace=True)
        return df

    def add_empty_features(self, impr, mode='both'):
        future_features = []
        past_features = []
        for key in self.features.keys():
            if 'future_' in key:
                future_features += [key]
            elif 'past_' in key:
                past_features += [key]
            else:
                print('ERROR: feature {} not belonging to any of the present'.format(key))
                return

        if mode == 'past' or mode == 'both':
            for key in past_features:
                self.features[key] += [-1] * len(impr)
        if mode == 'future' or mode == 'both':
            for key in future_features:
                self.features[key] += [-1] * len(impr)

    def compute_past_sessions_feat(self, df, impressions, closest_tm):

        self.features['past_times_interacted_impr'] += [len(df)] * len(impressions)

        self.features['past_session_num'] += [len(set(df.session_id.values))] * len(impressions)

        #self.features['past_closest_action_involving_impression'] += get_closest_actions_impressions(df, impressions, mode='past')

        self.features['past_times_user_interacted_impression'] += get_times_interacted_impression(df, impressions)

        self.features['past_time_from_closest_interaction_impression'] += get_time_from_closest_interacted_impression(
            df, impressions, closest_tm, mode='past')

        vectors_price = get_mean_price_info(df, impressions, mode='past')

        self.features['past_mean_price_interacted'] += vectors_price[0]

        self.features['past_mean_cheap_pos_interacted'] += vectors_price[1]

        self.features['past_mean_pos'] += vectors_price[2]

        self.features['past_pos_closest_reference'] += vectors_price[3]

        self.features['past_position_impression_changed_closest_clickout'] += vectors_price[4]

        self.get_action_involving_impressions(df, impressions, prefix='past')

    def compute_future_sessions_feat(self, df, impressions, closest_tm):

        self.features['future_times_interacted_impr'] += [len(df)] * len(impressions)

        self.features['future_session_num'] += [len(set(df.session_id.values))] * len(impressions)

        # self.features['future_closest_action_involving_impression'] += get_closest_actions_impressions(df, impressions, mode='future')

        self.features['future_times_user_interacted_impression'] += get_times_interacted_impression(df, impressions)

        self.features['future_time_from_closest_interaction_impression'] += get_time_from_closest_interacted_impression(
            df, impressions, closest_tm, mode='future')

        vectors_price = get_mean_price_info(df, impressions, mode='future')

        if vectors_price[0] is None:
            print(vectors_price)
            print(impressions)
        self.features['future_mean_price_interacted'] += vectors_price[0]

        self.features['future_mean_cheap_pos_interacted'] += vectors_price[1]

        self.features['future_mean_pos'] += vectors_price[2]

        self.features['future_pos_closest_reference'] += vectors_price[3]

        self.features['future_position_impression_changed_closest_clickout'] += vectors_price[4]

        self.get_action_involving_impressions(df, impressions, 'future')

    def get_action_involving_impressions(self, x, impr, prefix='future'):
        df_only_numeric = x[pd.to_numeric(x['reference'], errors='coerce').notnull()][[
            "reference", "action_type", "frequence"]]
        refs = list(df_only_numeric.reference.values)
        freqs = list(df_only_numeric.frequence.values)
        actions = list(df_only_numeric.action_type.values)
        count = 0
        for i in impr:
            actions_involving_impression_session_clickout_item = 0
            actions_involving_impression_session_interaction_item_deals = 0
            actions_involving_impression_session_interaction_item_image = 0
            actions_involving_impression_session_interaction_item_info = 0
            actions_involving_impression_session_interaction_item_rating = 0
            actions_involving_impression_session_search_for_item = 0
            actions_involving_impression_session_no_action = 0
            if i in refs:
                occ = [j for j, x in enumerate(refs) if x == i]
                for o in occ:
                    if actions[o] == 'clickout item':
                        actions_involving_impression_session_clickout_item += freqs[o]
                    elif actions[o] == 'interaction item deals':
                        actions_involving_impression_session_interaction_item_deals += freqs[o]
                    elif actions[o] == 'interaction item image':
                        actions_involving_impression_session_interaction_item_image += freqs[o]
                    elif actions[o] == 'interaction item info':
                        actions_involving_impression_session_interaction_item_info += freqs[o]
                    elif actions[o] == 'interaction item rating':
                        actions_involving_impression_session_interaction_item_rating += freqs[o]
                    elif actions[o] == 'search for item':
                        actions_involving_impression_session_search_for_item += freqs[o]
            else:
                actions_involving_impression_session_no_action += 1

            self.features[prefix + '_actions_involving_impression_session_clickout_item'] += [
                actions_involving_impression_session_clickout_item]
            self.features[prefix + '_actions_involving_impression_session_item_deals'] += [
                actions_involving_impression_session_interaction_item_deals]
            self.features[prefix + '_actions_involving_impression_session_item_image'] += [
                actions_involving_impression_session_interaction_item_image]
            self.features[prefix + '_actions_involving_impression_session_item_info'] += [
                actions_involving_impression_session_interaction_item_info]
            self.features[prefix + '_actions_involving_impression_session_item_rating'] += [
                actions_involving_impression_session_interaction_item_rating]
            self.features[prefix + '_actions_involving_impression_session_search_for_item'] += [
                actions_involving_impression_session_search_for_item]
            self.features[prefix + '_actions_involving_impression_session_no_action'] += [
                actions_involving_impression_session_no_action]
            count += 1


def get_closest_actions_impressions(df, impressions, mode='past'):
    """
    Compute features given:
    :param df:
    :param impressions:
    :param mode: if 'past', get the LAST action of impression,
                 if 'future', get the FIRST action of impression
    """
    df = df[pd.to_numeric(df['reference'], errors='coerce').notnull()]

    if mode == 'past':
        references_inv = list(df.reference.values)[::1]
        action_type_inv = list(df.action_type.values)[::1]
    elif mode == 'future':
        references_inv = list(df.reference.values)
        action_type_inv = list(df.action_type.values)
    else:
        print("Error: incorrect mode for get_actions_impressions")
        return

    vector_closest_actions = []
    for i in impressions:
        if i not in references_inv:
            vector_closest_actions += ['no_action']
        else:
            vector_closest_actions += [action_type_inv[references_inv.index(i)]]

    return vector_closest_actions


def get_times_interacted_impression(x, impr):
    vector_times_interacted_impr = []
    df_only_numeric = x[x['reference'].astype(str).str.isdigit()]

    refs = []
    if df_only_numeric.shape[0] > 0:
        refs = list(df_only_numeric.reference.values)
        freq = list(df_only_numeric.frequence.values)
    for i in impr:
        if i in refs:
            idx = [j for j, x in enumerate(refs) if x == i]
            occ = 0
            for k in idx:
                occ += freq[k]
            vector_times_interacted_impr += [occ]
        else:
            vector_times_interacted_impr += [0]
    return vector_times_interacted_impr


def get_time_from_closest_interacted_impression(df, impressions, closest_tm, mode='past'):
    df = df[pd.to_numeric(df['reference'], errors='coerce').notnull()]
    if mode == 'past':
        references_inv = list(df.reference.values)[::1]
        timestamps_inv = list(df.timestamp.values)[::1]
    elif mode == 'future':
        references_inv = list(df.reference.values)
        timestamps_inv = list(df.timestamp.values)
    else:
        print("Error: incorrect mode for get_actions_impressions")
        return

    vector_closest_actions = []
    for i in impressions:
        if i not in references_inv:
            vector_closest_actions += [-1]
        else:
            vector_closest_actions += [abs(
                int(timestamps_inv[references_inv.index(i)]) - closest_tm)]

    return vector_closest_actions


def get_mean_price_info(x, impressions, mode='past'):
    mean_pos = -1
    pos_last_reference = -1
    mean_cheap_position = -1
    mean_price_interacted = -1

    # 0 if same, 1 if changed
    position_impression_changed_closest_clickout = 1

    y = x[x.action_type == 'clickout item']
    if len(x) > 1:
        impressions_pos_available = y[['impressions', 'prices']].drop_duplicates()

        # [13, 43, 4352, 543, 345, 3523] impressions
        # [45, 34, 54, 54, 56, 54] prices
        # -> [(13,45), (43,34), ...]
        # Then create dict
        # {13: 45, 43: 34, ... }

        # [13, 43, 4352, 543, 345, 3523] impressions
        # -> [(13,1), (43,2), ...]
        # Then create dict impression-position
        # {13: 1, 43: 2, ... }
        tuples_impr_prices = []
        tuples_impr_price_pos_asc = []

        tuples_impr_pos = []

        for i in impressions_pos_available.index:
            impr = impressions_pos_available.at[i, 'impressions'].split('|')
            prices = list(map(int, impressions_pos_available.at[i, 'prices'].split('|')))
            tuples_impr_prices += list(zip(impr, prices))

            tuples_impr_pos += [(impr[idx], idx + 1) for idx in range(len(impr))]

            prices_sorted = prices.copy()
            prices_sorted.sort()

            tuples_impr_price_pos_asc += [(impr[idx], prices_sorted.index(prices[idx]) + 1) for idx in
                                          range(len(impr))]

        # dictionary: from impression, get its price
        dict_impr_price = dict(list(set(tuples_impr_prices)))

        # dictionary: from impression, get its position on impression
        dict_impr_pos = dict(list(set(tuples_impr_pos)))

        # dictionary: from impression, get its price position wrt the ascending price order
        dict_impr_price_pos = dict(list(set(tuples_impr_price_pos_asc)))

        # If an impression is also clicked, that price counts double
        # considering reference, impressions and action type as a row, I can distinguish from clickouts and impressions dropping duplicates
        df_only_numeric = x[["reference", "impressions", "action_type"]].drop_duplicates()

        sum_price = 0
        sum_pos_price = 0
        sum_pos_impr = 0
        count_interacted_pos_impr = 0
        count_interacted = 0
        for i in df_only_numeric.index:
            reference = df_only_numeric.at[i, 'reference']

            if reference in dict_impr_price.keys():
                sum_pos_impr += int(dict_impr_pos[reference])
                sum_price += int(dict_impr_price[reference])
                sum_pos_price += int(dict_impr_price_pos[reference])
                count_interacted_pos_impr += 1
                count_interacted += 1

        if count_interacted > 0:
            mean_cheap_position = round(sum_pos_price / count_interacted, 2)
            mean_price_interacted = round(sum_price / count_interacted, 2)
            mean_pos = round(sum_pos_impr / count_interacted_pos_impr, 2)

            relevant_references = []  # TODO speed up
            for x in df_only_numeric.reference.values:
                if x in impressions:
                    relevant_references += [x]

            if len(relevant_references) > 0:
                if mode == 'past':
                    closest_reference = relevant_references[-1]

                    if len(impressions_pos_available) > 0 and impressions == \
                            impressions_pos_available.tail(1).impressions.values[-1].split('|'):
                        position_impression_changed_closest_clickout = 0


                elif mode == 'future':
                    closest_reference = relevant_references[0]

                    if len(impressions_pos_available) > 0 and impressions == \
                            impressions_pos_available.tail(1).impressions.values[0].split('|'):
                        position_impression_changed_closest_clickout = 0

                else:
                    print("ERROR: wrong mode in mean price info!")
                    return

                pos_last_reference = impressions.index(closest_reference) + 1

    lenIm = len(impressions)
    return ([mean_price_interacted] * lenIm, [mean_cheap_position] * lenIm,
            [mean_pos] * lenIm, [pos_last_reference] * lenIm, [position_impression_changed_closest_clickout] * lenIm)


if __name__ == '__main__':
    import utils.menu as menu

    mode = menu.mode_selection()
    cluster = menu.cluster_selection()

    c = PastFutureSessionFeatures(mode, cluster)

    print('Creating {} for {} {}'.format(c.name, c.mode, c.cluster))
    c.save_feature()

    print(c.read_feature(one_hot=False))