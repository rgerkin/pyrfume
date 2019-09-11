import os
import pickle
import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform

from .base import DATA_DIR
SNITZ_DIR = DATA_DIR / 'snitz_2013'


def get_snitz_weights(use_original=True):
    """Return a pandas Series of weights for Dragon features in Snitz"""
    if use_original:  # Use the ones from the Snitz paper, with no weights
        file_name = 'snitz-descriptors-from-paper-dragon-6.pkl'
        path = SNITZ_DIR / file_name
        with open(path, 'rb') as f:
            snitz_list = pickle.load(f)
        ones = np.ones(len(snitz_list))
        snitz_weights = pd.Series(ones, index=snitz_list)
    else:
        # Use the ones that I derived, with weights computed by optimization
        # using Snitz-space projections of each molecule's original unit vector
        file_name = 'snitz_dragon_weights.csv'
        path = SNITZ_DIR / file_name
        snitz_weights = -1*pd.read_csv(path, index_col=0)['Weight']
    return snitz_weights


def get_snitz_features(dragon, snitz_weights=None, use_original=True):
    if snitz_weights is None:
        snitz_weights = get_snitz_weights(use_original=use_original)
    snitz_features = dragon[snitz_weights.index] * snitz_weights
    # CIDs where the Snitz vector has no length
    null_vectors = list(snitz_features.index[snitz_features.sum(axis=1) == 0])
    print('Number of zero-length Snitz vectors is %d ' % len(null_vectors))
    # Fill these with median features (these molecules will become useless)
    for nv in null_vectors:
        snitz_features.loc[nv, :] = snitz_features.median()
    return snitz_features


def get_snitz_distances(dragon, snitz_features=None, snitz_weights=None,
                        use_original=True):
    # Compute Snitz distances.
    # Cosine distance is approximately the same as angle distance
    # for small-ish angles
    if snitz_features is None:
        snitz_features = get_snitz_features(dragon,
                                            snitz_weights=snitz_weights,
                                            use_original=use_original)
    x = pdist(snitz_features.values, 'cosine')
    snitz_distances = pd.DataFrame(squareform(x),
                                   index=snitz_features.index,
                                   columns=snitz_features.index)
    return snitz_distances
