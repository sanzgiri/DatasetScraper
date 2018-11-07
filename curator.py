import os
import numpy as np
from itertools import combinations

import torch
import torch.nn as nn
import torchvision.transforms as transforms
import torchvision.models as models
from torch.utils.data import Dataset, DataLoader
from fastai.widgets.image_cleaner import FileDeleter
from PIL import Image

class Numpize(nn.Module):
    """ Converts our output into a numpy array"""
    def __init__(self):
        super(Numpize, self).__init__()
        
    def forward(self, x):
        return x.cpu().detach().numpy().reshape(x.shape[0],-1)

class ImageDataset(Dataset):
    """ Standard pytorch dataset"""
    def __init__(self, img_paths, device, img_size=224):
        self.loader = transforms.Compose([
            transforms.Resize((img_size, img_size)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406],[0.229, 0.224, 0.225])])

        self.imgs = img_paths
        self.device = device 
        
    def __len__(self):
        return len(self.imgs)

    def __getitem__(self, idx):
        name = self.imgs[idx]
        img = Image.open(name).convert('RGB')
        return self.loader(img).to(self.device, torch.float)
    
class Curator:
    """Jupyter Notebook widget for removing images which are too similar or don't
        belong.

    Args:
        img_paths (list): paths to images to curate. Images should be of one class
        
        img_size (int): images must get resized for processing. Don't change unless
            you're having memory issues.
        
        batch_size (int): images will be processed in batches to limit memory
            consumption. Increase for faster processing, derease if running out
            of memory.

    Returns:
        A Curator instance capable of finding near duplicates or garbage images.

    Methods:
        duplicate_detection(num_pairs=100): this presents a widget in the Jupyter
        Notebook which displays pairs of images in order of simularity. Duplicates
        will be shown first, followed by near duplicates with increasing differences.
        Remove images interactively until you stop seeing duplicates. The num_pairs
        argument limits processing to the top [num_pairs] number of pairs. If you
        have more than 100 duplicate pairs this should be increased, or a new Curator
        instance should be created after the first pass of removals.

        garbage_detection(): this presents a widget in the Jupyter Notebook which 
        displays images which are the most dissimilar with the other images in the
        dataset. Usually, images which don't belong in the set will have high
        dissimilarity. The images will be presented in order of dissimilarity.
    """
    def __init__(self, img_paths, img_size=224, batch_size=16):
        
        # images
        self.img_paths = img_paths
        # gpu or cpu?
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # get our dataset, resize images to 224
        self.dataset = ImageDataset(img_paths, self.device, img_size)
        self.n_images = len(self.dataset)
        
        # loader will load them in 16 at a time
        loader = DataLoader(self.dataset, batch_size=batch_size, shuffle=False)

        # I'm gonna use the first few layers from vgg19 to get content simularity
        vgg = models.vgg19(pretrained=True).features.to(self.device).eval()
        
        # build a model from the first few layers of the vgg19
        model = nn.Sequential()
        i = 0
        j = 0
        for layer in vgg.children():
            if isinstance(layer, nn.Conv2d):
                i += 1
                name = f'conv_{i}'
            else:
                name = f'thing_{j}'
                j += 1
            model.add_module(name, layer)
            
            if name == 'conv_4':
                # this is the last layer we want want from vgg
                # add some pooling to get a smaller numpy vector
                model.add_module('pool',nn.AdaptiveAvgPool2d(1))
                model.add_module('numpy', Numpize())
                break

        # store our image vectors here
        img_vecs = np.zeros((self.n_images, 128), dtype=np.float)
        count = 0
        for batch in loader:
            # fetch vectors and store
            vecs = model(batch)
            img_vecs[count:count+vecs.shape[0]] = vecs
            count += vecs.shape[0]

        # get the mean squared error between all pairs of image vectors
        pairs = list(combinations(range(self.n_images), 2))
        mse = np.mean((img_vecs[pairs,:][:,0,:] - img_vecs[pairs,:][:,1,:])**2,1)
        self.results = sorted(list(zip(pairs,mse)), key=lambda x: x[1])

    def duplicate_detection(self, num_pairs=100):
        """ Presents most similar image pairs"""

        # go through pairs of images in order of most similar
        paths = []
        for pair,mse in self.results[:num_pairs]:
            img0, img1 = pair
            path0 = self.img_paths[img0]
            path1 = self.img_paths[img1]

            if os.path.exists(path0) and os.path.exists(path1):
                paths = paths + [path0, path1]

        fd = FileDeleter(paths, batch_size=2)

    def garbage_detection(self):    
        """ Presents most dissimilar images in the dataset"""
        
        # garbage images are probably the most disimilar in the dataset
        scores = np.zeros(self.n_images)
        for pair,mse in self.results:
            scores[pair[0]] += mse
            scores[pair[1]] += mse
        
        # get index in reverse order (most similar last)
        paths = []
        for idx in scores.argsort()[::-1]:
            path = self.img_paths[idx]
            if os.path.exists(path):
                paths.append(path)
        fd = FileDeleter(paths)
