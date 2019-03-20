from recommenders.hybrid_base import Hybrid


class HybridRHat(Hybrid):

    def __init__(self, r_hat_array, normalization_mode, mode, weights_array):
        name = 'HybridRHat'
        super(HybridRHat, self).__init__(name=name, mode=mode, matrices_array=r_hat_array,
                                         normalization_mode=normalization_mode,
                                         weights_array=weights_array)
