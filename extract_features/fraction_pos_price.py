from extract_features.feature_base import FeatureBase
import data
import pandas as pd
import numpy as np
from tqdm.auto import tqdm
from preprocess_utils.last_clickout_indices import find as find_last_clickout_indices
tqdm.pandas()
import os

class FractionPosPrice(FeatureBase):

    """
    | user_id | session_id | item_id | fraction_pos_price
    """

    def __init__(self, mode, cluster='no_cluster'):
        name = 'fraction_pos_price'
        super(FractionPosPrice, self).__init__(
            name=name, mode=mode, cluster=cluster)

    def extract_feature(self):
        train = data.train_df(mode=self.mode, cluster=self.cluster)
        test = data.test_df(mode=self.mode, cluster=self.cluster)
        df = pd.concat([train, test])

        idxs_click = find_last_clickout_indices(df)
        df = df.loc[idxs_click][['user_id', 'session_id', 'impressions', 'prices']]

        impression_price_position_list = []
        fraction_pos_price_list = []
        for i in tqdm(df.index):
            impr = list(map(int, df.at[i, 'impressions'].split('|')))
            prices = list(map(int, df.at[i, 'prices'].split('|')))

            impression_position = np.arange(len(impr)) + 1

            couples = zip(prices, impression_position, impr)
            couples = sorted(couples, key=lambda a: a[0])

            prices_ordered, position, impressions_ordered = zip(*couples)

            _, price_pos = list(zip(*sorted(list(zip(position, impression_position)), key=lambda a: a[0])))
            fraction_pos_price = list(impression_position / price_pos)

            fraction_pos_price_list.append(np.array(fraction_pos_price))
            impression_price_position_list.append(np.array(price_pos))
        df['fraction_pos_price'] = fraction_pos_price_list

        df['impressions'] = df['impressions'].str.split('|')
        df['prices'] = df['prices'].str.split('|')

        final_df = pd.DataFrame({col: np.repeat(df[col], df['impressions'].str.len())
                                 for col in df.columns.drop(['impressions', 'prices'])}).assign(
            **{'item_id': np.concatenate(df['impressions'].values),
               'fraction_pos_price': np.concatenate(df['fraction_pos_price'].values),
               'price_log': np.concatenate(df['prices'].values)})

        final_df['item_id'] = pd.to_numeric(final_df['item_id'])
        final_df['fraction_pos_price'] = pd.to_numeric(final_df['fraction_pos_price'])

        return final_df

if __name__ == '__main__':
    from utils.menu import mode_selection, cluster_selection
    cluster = cluster_selection()
    mode = mode_selection()
    c = FractionPosPrice(mode=mode, cluster=cluster)
    c.save_feature()
