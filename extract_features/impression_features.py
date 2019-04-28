from extract_features.feature_base import FeatureBase
import data
import pandas as pd
from tqdm.auto import tqdm
tqdm.pandas()


class ImpressionFeature(FeatureBase):

    """
    impression features
    item_id | properties
    """

    def __init__(self, mode, cluster='no_cluster'):
        name = 'impression_features'
        columns_to_onehot = [('properties', 'multiple')]
        super(ImpressionFeature, self).__init__(
            name=name, mode=mode, cluster=cluster, columns_to_onehot=columns_to_onehot)

    def extract_feature(self):
        s = data.accomodations_df().drop('Unnamed: 0', axis=1)
        return s

if __name__ == '__main__':
    c = ImpressionFeature(mode='small', cluster='no_cluster')
    c.save_feature()