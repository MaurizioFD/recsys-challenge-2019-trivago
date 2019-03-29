import numpy as np
from tqdm import tqdm

import data
from recommenders.hybrid_base import Hybrid
from utils import log


class HybridImpressionScores(Hybrid):

    def __init__(self, mode, impression_scores_matrices, weights_array, normalization_mode, threshold):
        name = 'HybridImpressionScores'
        """
        Initialize the model

        Parameters
        ----------
        impression_scores_matrices: array of triples
            Contains n lists of triples from n different recommenders.
            [ 
                [ (s_1, impr_1, scores_1), (...), .. (s_m, impr_m, scores_m) ]1, 
                [ ... ]2, ... 
                [ ... ]n
            ]
            s = session_id, impr_1 = impressions ordered from best performing, scores_1 = scores of the impressions
            
        weights_array: list of int
            lists of weights that will be multiplied to each matrix score before the ensemble of scores
        
        normalization_mode: str
            Normalization modes of normalization of scores. can be
            - max_matrix: divide from max of every scores
            - max_row: divide from max of every row score (max score of impressions for each session) 
            - no_normalization: without normalization of scores
            - ...
            
        threshold: float, optional
            All the values under this value are cut from the final result
        """

        super(Hybrid, self).__init__(name=name, mode=mode)

        if len(weights_array)!= len(impression_scores_matrices):
            print("the matrices passed have not the same len of their weights... go get some coffee...")

        self.impression_scores_matrices = impression_scores_matrices

        self.weights_array = weights_array

        self._check_matrices_array_shapes()

        self.normalization_mode = normalization_mode

        self.threshold = threshold

        #TODO: check if all recommended hotels are ints and not strings

    def fit(self):
        """
        Fit the model on the data.
        Creates a list list_scores of 100m lines initialized to 0 representing id of each hotel

        For every Recommender matrix, for every triple, the corresponding
        cell of list_scores will be summed by the score

        """

        self.dict_scores = {}

        #Getting target sessions from list of tuples
        df_test = data.test_df(self.mode)

        df_test_target = df_test[df_test["action_type"] == "clickout item"]

        df_test_target = df_test_target.replace(r'', np.nan, regex=True)

        df_test_target = df_test_target[~df_test_target.reference.notnull()]

        target_sessions = df_test_target["session_id"]


        #Initialize list for dict containing scores of imoressions
        for s_target in target_sessions:
            self.dict_scores[s_target] = {}

        for i in range(len(self.impression_scores_matrices)):
            print("Getting scores from recommender number {} ...".format(i))

            self.matrices_array = self.impression_scores_matrices[i].copy()

            self._normalization(self.normalization_mode)

            for k in tqdm(range(len(self.impression_scores_matrices[i]))):
                triple = self.impression_scores_matrices[i][k]

                # updating scores multiplied by corresponding weight
                for j in range(len(triple[2])):
                    if triple[1][j] in self.dict_scores[triple[0]]:
                        self.dict_scores[triple[0]][triple[1][j]] += self.normalized_matrices_array[k][j]*self.weights_array[i]
                    else:
                        self.dict_scores[triple[0]][triple[1][j]] = self.normalized_matrices_array[k][j]*self.weights_array[i]


    def recommend_batch(self):
        """
        returns a list of recommendations in the format
        [(session_id_0, [acc_1, acc2, acc3, ...]),
         (session_id_1, [acc_1, acc2, acc3, ...]), ...]

        For every session_id, the list_scores will be filtered
        by nonzero elements and then argsorted.
        """

        new_recs = []
        new_recs_scores = []
        #Iterating on nonempty elements of dictionary
        print("{}: Recommending ....".format(self.name))
        for key, value in tqdm(self.dict_scores.items()):

            recs = sorted(value, key=value.get, reverse=True)
            scores = sorted(value.values(), reverse=True)

            new_recs.append((key, recs))
            new_recs_scores.append( (key, recs, scores) )

        self.recs_scores_batch = new_recs_scores
        self.recs_batch = new_recs

        return new_recs


    def get_scores_batch(self):
        return self.recs_scores_batch


    "Check if recommended score matrix have same len of target sessions"
    def _check_matrices_array_shapes(self):
        shape = len(self.impression_scores_matrices[0])
        for m in self.impression_scores_matrices:
            if len(m) != shape:
                print("the matrices passed have not the same shape... go get some coffe...")
                exit(0)

    def _normalize_max_row(self):
        """
        Normalize each row score dividing by max element of the row
        :return: return an array containing the normalized matrices
        """

        normalized_matrices_array = []
        for elem in self.matrices_array:
            if len(elem) > 0:
                normalized_matrices_array.append([x / elem[0] for x in elem])
            else:
                normalized_matrices_array.append(elem)

        return normalized_matrices_array

    def _normalize_max_matrix(self):
        """
        :return: return an array containing the normalized matrices
        """

        normalized_matrices_array = np.asarray(self.matrices_array)

        max_val = np.amax(normalized_matrices_array)

        if max_val != 0:
            normalized_matrices_array = normalized_matrices_array / max_val

        return normalized_matrices_array

    def _normalize_l2(self):
        normalized_matrices_array = np.asarray(self.matrices_array)

        for i in range(len(normalized_matrices_array)):
            array = normalized_matrices_array[i]
            if len(array) > 0:
                max_val = np.sqrt((array * array).sum(axis=1))

                if max_val != 0:
                    normalized_matrices_array = normalized_matrices_array / max_val

        return normalized_matrices_array

    def _normalization(self, normalization_mode):
        """
        Transform the matrix_array from triples into real matrix of form
        [ [ scor_1, scor_2, scor_3, .... ]s1,
          [ scor_1, scor_2, scor_3, .... ]s2,
          ... ]
        :param normalization_mode: mode of normalization
        """
        self.matrices_array = [x[2] for x in self.matrices_array]

        if normalization_mode == 'MAX_ROW':
            self.normalized_matrices_array = self._normalize_max_row()
        elif normalization_mode == 'MAX_MATRIX':
            self.normalized_matrices_array = self._normalize_max_matrix()
        elif normalization_mode == 'L2':
            self.normalized_matrices_array = self._normalize_l2()
        elif normalization_mode == 'NONE':
            self.normalized_matrices_array = self.matrices_array
        else:
            log.error('invalid string for normalization')
            return
