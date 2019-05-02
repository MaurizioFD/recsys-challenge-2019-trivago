import sys
import os
sys.path.append(os.getcwd())

import utils.menu as menu
from clusterize.cluster_recurrent import ClusterRecurrent
from extract_features.reference_position_in_next_clickout_impressions import ReferencePositionInNextClickoutImpressions
import preprocess_utils.session2vec as sess2vec



if __name__ == "__main__":
        
    mode = menu.mode_selection()
    cluster_name = 'cluster_recurrent'

    # create the cluster
    cluster = ClusterRecurrent()
    cluster.save(mode)
    print()

    # create the features to join
    ref_pos_next_clk_feat = ReferencePositionInNextClickoutImpressions(mode=mode, cluster=cluster_name)
    ref_pos_next_clk_feat.save_feature(overwrite_if_exists=True)
    print()

    features = [ref_pos_next_clk_feat]
    # create the tensors dataset
    sess2vec.create_dataset_for_classification(mode, cluster_name, pad_sessions_length=10, features=features)


