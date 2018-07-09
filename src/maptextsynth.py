# CNN-LSTM-CTC-OCR
# Copyright (C) 2017 Jerod Weinman
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import tensorflow as tf
import numpy as np
from map_generator import data_generator
import pipeline

# The list (well, string) of valid output characters
# If any example contains a character not found here, an error will result
# from the calls to .index in the decoder below
out_charset=pipeline.out_charset

def get_data(num_threads=4,
             batch_size=32,
             boundaries=[32, 64, 96, 128, 160, 192, 224, 256],
             input_device=None,
             filter_fn=None):
    """Get input dataset with elements bucketed by image width
    Returns:
      image  : float32 image tensor [batch_size 32 ? 1] padded 
                 to max width in batch
      width  : int32 image widths (for calculating post-CNN sequence length)
      label  : Sparse tensor with label sequences for the batch
      length : Length of label sequence (text length)
      text   : Human readable string for the image
    """
    # Elements to be buffered
    num_buffered_elements = num_threads*batch_size*2

    dataset = _get_dataset().prefetch(num_buffered_elements)
    
    with tf.device(input_device):
        dataset = dataset.map(_preprocess_dataset, 
                              num_parallel_calls=num_threads)
        dataset = dataset.prefetch(num_buffered_elements)

        # Remove input that doesn't fit necessary specifications
        if filter_fn:
            dataset = dataset.filter(filter_fn)

        # Bucket and batch appropriately
        if boundaries:
            dataset = dataset.apply(tf.contrib.data.bucket_by_sequence_length(
                element_length_func=_element_length_fn,
                bucket_batch_sizes=np.full(len(boundaries)+1, batch_size),
                bucket_boundaries=boundaries,)) 
        else:
            # Dynamically pad batches to match largest in batch
            dataset = dataset.padded_batch(batch_size, 
                                           padded_shapes=dataset.output_shapes,)

        # Convert labels to sparse tensor for CNN purposes
        dataset = dataset.map(
            lambda image, width, label, length, text:
                (image, 
                 width, 
                 # -1 EOS token
                 tf.contrib.layers.dense_to_sparse(label,-1),
                 length, text),
            num_parallel_calls=num_threads)
        
        # Prefetch some more
        dataset = dataset.prefetch(8)
    return dataset

def _element_length_fn(image, width, label, length, text):
    return width

def _get_dataset():
    """
    Get a dataset from generator
    Format: [text|image|labels] -- types and shapes can be seen below 
    """
    return tf.data.Dataset.from_generator(_generator_wrapper, 
               (tf.string, tf.int32, tf.int32), # Output Types
               (tf.TensorShape([]),             # Shape 1st element
               (tf.TensorShape((32, None, 3))), # Shape 2nd element
               (tf.TensorShape([None]))))       # Shape 3rd element

def _preprocess_dataset(caption, image, labels):
    """Prepare dataset for ingestion"""

    #NOTE: final image should be pre-grayed by opencv *before* generation
    image = tf.image.rgb_to_grayscale(image) 
    image = _preprocess_image(image)

    # Width is the 2nd element of the image tuple
    width = tf.size(image[1]) 

    # Length is the length of labels - 1 (because labels has -1 EOS token here)
    length = tf.subtract(tf.size(labels) - 1) 

    text = caption

    return image, width, labels, length, text

def _generator_wrapper():
    """
    Compute the labels in python before everything becomes tensors
    Note: Really should not be doing this in python if we don't have to!!!
    """
    gen = data_generator()
    while True:
        data = next(gen)
        caption = data[0]
        image = data[1]

        # Transform string text to sequence of indices using charset
        labels = [out_charset.index(c) for c in list(caption)]
        labels.append(-1)
        yield caption, image, labels

def _preprocess_image(image):
    # Rescale from uint8([0,255]) to float([-0.5,0.5])
    image = tf.image.convert_image_dtype(image, tf.float32)
    image = tf.subtract(image, 0.5)

    return image