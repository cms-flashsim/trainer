import h5py
import torch
from torch.utils.data import Dataset
import pandas as pd
import numpy as np

def postprocess_disc(disc):
    range_disc = 20.56
    min = -0.8281470664258219
    disc = np.where(disc < min, -0.1, (np.tanh(disc * range_disc) + 1) / 2)
    return disc

class ObjectDataset(Dataset):
    """Dataset for Electron training

    Args:
        Dataset (Dataset): _description_
    """

    def __init__(self, h5_paths, start, limit, x_dim, y_dim):
        self.h5_paths = h5_paths
        self._archives = [h5py.File(h5_path, "r") for h5_path in self.h5_paths]
        self._archives = None

        y = self.archives[0]["data"][start : (start + limit), 0:y_dim]
        x = self.archives[0]["data"][start : (start + limit), y_dim : (y_dim + x_dim)]
        self.x_train = torch.tensor(x, dtype=torch.float32)
        self.y_train = torch.tensor(y, dtype=torch.float32)
        print("Dataset created.")
        print("x_max: ", self.x_train.max())
        print("x_min: ", self.x_train.min())
        print("y_max: ", self.y_train.max())
        print("y_min: ", self.y_train.min())
        print("Nan in x", torch.isnan(self.x_train).sum())
        print("Nan in y", torch.isnan(self.y_train).sum())
        print("Inf in x", torch.isinf(self.x_train).sum())
        print("Inf in y", torch.isinf(self.y_train).sum())

    @property
    def archives(self):
        if self._archives is None:
            self._archives = [h5py.File(h5_path, "r") for h5_path in self.h5_paths]
        return self._archives

    def __len__(self):
        return len(self.y_train)

    def __getitem__(self, idx):
        return self.x_train[idx], self.y_train[idx]


class FatJetsDataset(Dataset):
    """Very simple Dataset for reading hdf5 data
        This is way simpler than muons as we heve enough jets in a single file
        Still, dataloading is a bottleneck even here
    Args:
        Dataset (Pytorch Dataset): Pytorch Dataset class
    """

    def __init__(self, pkl_paths, start, limit, remove_sig_not_H=False):
        self.pkl_paths = pkl_paths
        self.df = pd.read_pickle(self.pkl_paths[0])

        if remove_sig_not_H:
            # remove all is_signal==1 but has_H_within_0_8==0
            self.df = self.df[~((self.df['is_signal'] == 1) & (self.df['Mhas_H_within_0_8'] == 0))]

        y = self.df[
            [
                "MgenjetAK8_pt",
                "MgenjetAK8_phi",
                "MgenjetAK8_eta",
                "MgenjetAK8_hadronFlavour",
                "MgenjetAK8_partonFlavour",
                "MgenjetAK8_mass",
                "MgenjetAK8_ncFlavour",
                "MgenjetAK8_nbFlavour",
                "Mhas_H_within_0_8",
                "is_signal",
            ]
        ].values[start:limit]

        x = self.df[
            [
                "Mpt_ratio",
                "Meta_sub",
                "Mphi_sub",
                "Mfatjet_msoftdrop",
                "Mfatjet_particleNetMD_XbbvsQCD",
            ]
        ].values[start:limit]

        self.x_train = torch.tensor(x, dtype=torch.float32)
        self.y_train = torch.tensor(y, dtype=torch.float32)

    def __len__(self):
        return len(self.y_train)

    def __getitem__(self, idx):
        return self.x_train[idx], self.y_train[idx]


class DataPreprocessor:
    """Class for preprocessing the training data.
    """

    def __init__(self, dataset_path, reshaped=False):
        self.df = pd.read_pickle(dataset_path)
        self.reshaped = reshaped
    
        self.X = self.df[
            [
                "Mpt_ratio",
                "Meta_sub",
                "Mphi_sub",
                "Mfatjet_msoftdrop",
                "Mfatjet_particleNetMD_XbbvsQCD",
            ]
        ].values

        self.Y = self.df[
            [
                "MgenjetAK8_pt",
                "MgenjetAK8_phi",
                "MgenjetAK8_eta",
                "MgenjetAK8_hadronFlavour",
                "MgenjetAK8_partonFlavour",
                "MgenjetAK8_mass",
                "MgenjetAK8_ncFlavour",
                "MgenjetAK8_nbFlavour",
                "Mhas_H_within_0_8",
                "is_signal",
            ]
        ].values

    def get_dataset(self):
        return self.X, self.Y
    
    def postprocess(self, X, Y):
        # sum X eta, phi and Y eta, phi
        X[:, 1] = X[:, 1] + Y[:, 2]
        X[:, 2] = X[:, 2] + Y[:, 1]

        # multpily X pt, msoftdrop and Y pt, mass
        X[:, 0] = X[:, 0] * Y[:, 0]
        X[:, 3] = X[:, 3] * Y[:, 5]

        # where softdrom < 0, put -10
        X[:, 3] = np.where(X[:, 3] < 0, -10, X[:, 3])

        # postprocess discriminator
        if self.reshaped:
            X[:, 4] = postprocess_disc(X[:, 4])

        return X
