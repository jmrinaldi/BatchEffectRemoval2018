'''
Created on Jul 6, 2018

@author: urishaham
Resnet code is based on: https://github.com/tensorflow/models/blob/master/official/resnet/resnet_model.py
VAE code, tflib, pylib are based on https://github.com/LynnHo/VAE-Tensorflow
Transformer code is based on https://github.com/Kyubyong/transformer
'''

from functools import partial
import tensorflow as tf
import tensorflow.contrib.slim as slim
import tflib as tl



fc = partial(tl.flatten_fully_connected, activation_fn=None)
lrelu = tf.nn.leaky_relu
relu = tf.nn.relu
batch_norm = partial(slim.batch_norm, scale=True, updates_collections=None)

def mlp():
    
    def Enc(inputs, 
            hidden_dim=20, 
            code_dim=5, 
            is_training=True):
        
        with tf.variable_scope('Encoder', reuse=tf.AUTO_REUSE):
            y = fc(inputs, hidden_dim)
            y = lrelu(y)
            y = fc(y, hidden_dim)
            y = lrelu(y)
            c_mu = fc(y, code_dim)
            c_log_sigma_sq = fc(y, code_dim)
        return c_mu, c_log_sigma_sq
    
    def Dec_a(code, 
              output_dim, 
              hidden_dim=20, 
            is_training=True):
        
        with tf.variable_scope('Decoder_a', reuse=tf.AUTO_REUSE):
            y = fc(code, hidden_dim)
            y = lrelu(y)
            y = fc(y, hidden_dim)
            y = lrelu(y)
            recon = fc(y, output_dim)
        return recon
    
    def Dec_b(code, 
              output_dim, 
              hidden_dim=20, 
            is_training=True):
        
        with tf.variable_scope('Decoder_b', reuse=tf.AUTO_REUSE):
            y = fc(code, hidden_dim)
            y = lrelu(y)
            y = fc(y, hidden_dim)
            y = lrelu(y)
            recon = fc(y, output_dim)
        return recon
            
    def Disc(code, 
             hidden_dim=20):
        
        with tf.variable_scope('discriminator', reuse=tf.AUTO_REUSE):
            y = fc(code, hidden_dim)
            y = lrelu(y)
            y = fc(y, hidden_dim)
            y = lrelu(y)
            output = fc(y, 1)
        return output    
    
    return Enc, Dec_a, Dec_b, Disc


def _resnet_block_v2(inputs, 
                     block_dim, 
                     is_training,
                     reuse=tf.AUTO_REUSE):
    
    with tf.variable_scope("resnet_block", reuse=reuse):
        shortcut = inputs
        inputs = batch_norm(inputs, is_training)
        inputs = lrelu(inputs)
        inputs = fc(inputs, block_dim)
        inputs = batch_norm(inputs, is_training)
        inputs = lrelu(inputs)
        inputs = fc(inputs, block_dim)
    return inputs + shortcut
    


def resnet():
    
    def Enc(inputs, 
            n_blocks=3, 
            block_dim=20, 
            code_dim=5, 
            is_training=True):
        
        with tf.variable_scope('Encoder', reuse=tf.AUTO_REUSE):
            inputs = batch_norm(inputs, is_training)
            y = lrelu(inputs)
            y = fc(y, block_dim)
            for _ in range(n_blocks):
                y = _resnet_block_v2(y, block_dim, is_training)
            c_mu = fc(y, code_dim)
            c_log_sigma_sq = fc(y, code_dim)
        return c_mu, c_log_sigma_sq
    
    def Dec_a(code, 
              output_dim, 
              n_blocks=3, 
              block_dim=20, 
              is_training=True):
        
        with tf.variable_scope('Decoder_a', reuse=tf.AUTO_REUSE):
            code = batch_norm(code, is_training)
            y = lrelu(code)
            y = fc(y, block_dim)
            for _ in range(n_blocks):
                y = _resnet_block_v2(y, block_dim, is_training)
            recon = fc(y, output_dim)
        return recon
    
    def Dec_b(code, 
              output_dim, 
              n_blocks=3, 
              block_dim=20, 
              is_training=True):
        
        with tf.variable_scope('Decoder_b', reuse=tf.AUTO_REUSE):
            code = batch_norm(code, is_training)
            y = lrelu(code)
            y = fc(y, block_dim)
            for _ in range(n_blocks):
                y = _resnet_block_v2(y, block_dim, is_training)
            recon = fc(y, output_dim)
        return recon
            
    def Disc(code, 
             n_blocks=3, 
             block_dim=20, 
             is_training=True):
        
        with tf.variable_scope('discriminator', reuse=tf.AUTO_REUSE):
            code = batch_norm(code, is_training)
            y = lrelu(code)
            y = fc(y, block_dim)
            for _ in range(n_blocks):
                y = _resnet_block_v2(y, block_dim, is_training)
            output = fc(y, 1)
        return output    
    
    return Enc, Dec_a, Dec_b, Disc

def _normalize(inputs, 
              epsilon = 1e-8,
              scope="ln",
              reuse=tf.AUTO_REUSE):
    '''Applies layer normalization.
    
    Args:
      inputs: A tensor with 2 or more dimensions, where the first dimension has
        `batch_size`.
      epsilon: A floating number. A very small number for preventing ZeroDivision Error.
      scope: Optional scope for `variable_scope`.
      reuse: Boolean, whether to reuse the weights of a previous layer
        by the same name.
      
    Returns:
      A tensor with the same shape and data dtype as `inputs`.
    '''
    with tf.variable_scope(scope, reuse=reuse):
        inputs_shape = inputs.get_shape()
        params_shape = inputs_shape[-1:]
    
        mean, variance = tf.nn.moments(inputs, [-1], keep_dims=True)
        beta= tf.Variable(tf.zeros(params_shape))
        gamma = tf.Variable(tf.ones(params_shape))
        normalized = (inputs - mean) / ( (variance + epsilon) ** (.5) )
        outputs = gamma * normalized + beta
        
    return outputs

def _multihead_attention(keys, 
                         is_training,
                         num_units=20, 
                         num_heads=5, 
                         dropout_rate=0,
                         reuse=tf.AUTO_REUSE):
    '''Applies multihead attention.
    
    Args:

      keys: A 2d tensor with shape of [N, h].
      num_units: A scalar. Attention size.
      dropout_rate: A floating point number.
      is_training: Boolean. Controller of mechanism for dropout.
      num_heads: An int. Number of heads.
      reuse: Boolean, whether to reuse the weights of a previous layer
        by the same name.
        
    Returns
      A 2d tensor with shape of (N, h)  
    '''
    
    with tf.variable_scope("multihead_attention", reuse=reuse):
        # Linear projections
        proj = tf.layers.dense(keys, num_units * num_heads, activation=lrelu) # (N, c*h)
        attn_weights = tf.layers.dense(keys, num_units * num_heads, activation=lrelu) # (N, c*h)
        
        # Split and concat
        proj_ = tf.concat(tf.split(proj, num_heads, axis=1), axis=0) # (h*N, c) 
        attn_weights_ = tf.concat(tf.split(attn_weights, num_heads, axis=1), axis=0) # (h*N, c) 

        # Activation
        attn_weights_ = tf.nn.softmax(attn_weights_) # (h*N, c) 
        
        # Weighted sum
        outputs = tf.reduce_sum(tf.multiply(proj_, attn_weights_),1, keep_dims=False)# (h*N)
        
        # Restore shape
        outputs = tf.concat(tf.split(tf.expand_dims(outputs,1), num_heads, axis=0), axis=1) # (N, h)
  
        # Residual connection
        outputs += keys # (N, h)

        # Normalize
        #outputs = _normalize(outputs) # (N, h)
    
    return outputs

def _feedforward(inputs, 
                 num_units=20,
                 reuse=tf.AUTO_REUSE):
    '''Point-wise feed forward net.
    
    Args:
      inputs: A 2d tensor with shape of [N, h].
      num_units: an integer, should be same as the same hyperparam in multihead_attention
      reuse: Boolean, whether to reuse the weights of a previous layer
        by the same name.
        
    Returns:
      A 2d tensor with the same shape and dtype as inputs
    '''
    with tf.variable_scope("forward", reuse=reuse):
        
        input_dim = inputs.get_shape().as_list()[-1]
        
        # Inner layer
        outputs = fc(inputs, num_units)
        outputs = lrelu(outputs)
        
        # Readout layer
        outputs = fc(outputs, input_dim)
        outputs = lrelu(outputs)
        
        # Residual connection
        outputs += inputs
        
        # Normalize
        #outputs = _normalize(outputs)
    
    return outputs

def transformer():
    
    
    def Enc(inputs, 
            n_blocks=3, 
            num_units=10, 
            num_heads=8,
            code_dim=5, 
            is_training=True,
            dropout_rate=0):
        
        with tf.variable_scope('Encoder', reuse=tf.AUTO_REUSE):
            y = fc(inputs, num_heads)
            y = lrelu(y)
            for _ in range(n_blocks):
                y = _multihead_attention(keys=y, 
                                         num_units=num_units, 
                                         num_heads=num_heads, 
                                         dropout_rate=dropout_rate,
                                         is_training=is_training)
                #y = _feedforward(y,
                #                 num_units=num_units)
                
            c_mu = fc(y, code_dim)
            c_log_sigma_sq = fc(y, code_dim)
            return c_mu, c_log_sigma_sq
    
    def Dec_a(code, 
              output_dim, 
              n_blocks=3, 
              num_units=10, 
              num_heads=8,
              is_training=True,
              dropout_rate=0):
        
        with tf.variable_scope('Decoder_a', reuse=tf.AUTO_REUSE):
            y = fc(code, num_heads)
            y = lrelu(y)
            for _ in range(n_blocks):
                y = _multihead_attention(keys=y, 
                                         num_units=num_units, 
                                         num_heads=num_heads, 
                                         dropout_rate=dropout_rate,
                                         is_training=is_training)
                y = _feedforward(y,
                                 num_units=num_units)
                
            recon = fc(y, output_dim)
            return recon
    
    def Dec_b(code, 
              output_dim, 
              n_blocks=3, 
              num_units=10, 
              num_heads=8,
              is_training=True,
              dropout_rate=0):
        
        with tf.variable_scope('Decoder_b', reuse=tf.AUTO_REUSE):
            y = fc(code, num_heads)
            y = lrelu(y)
            for _ in range(n_blocks):
                y = _multihead_attention(keys=y, 
                                         num_units=num_units, 
                                         num_heads=num_heads, 
                                         dropout_rate=dropout_rate,
                                         is_training=is_training)
                y = _feedforward(y,
                                 num_units=num_units)
                
            recon = fc(y, output_dim)
            return recon
        
    def Disc(code, 
             n_blocks=3, 
             num_units=10, 
             num_heads=8,
             is_training=True,
             dropout_rate=0):
        
        with tf.variable_scope('discriminator', reuse=tf.AUTO_REUSE):
            y = fc(code, num_heads)
            y = lrelu(y)
            for _ in range(n_blocks):
                y = _multihead_attention(keys=y, 
                                         num_units=num_units, 
                                         num_heads=num_heads, 
                                         dropout_rate=dropout_rate,
                                         is_training=is_training)
                y = _feedforward(y,
                                 num_units=num_units)
                
            output = fc(y, 1)
            return output    
    
    return Enc, Dec_a, Dec_b, Disc

def Cell_type_classifier():

    def cell_type_classifier(inputs, 
                             num_classes=5, 
                             is_training=False,
                             dropout_keep_prob=0.5,
                             prediction_fn=slim.softmax,
                             scope='classifier'):
      
      
      end_points = {}
        
      with tf.variable_scope('cell_type_classifier', reuse=tf.AUTO_REUSE):
        net = fc(inputs, 20, scope='fc1')
        net = end_points['fc1'] = lrelu(net)
        net = fc(net, 20, scope='fc2')
        net = end_points['fc2'] = lrelu(net)
        net = slim.dropout(
            net, dropout_keep_prob, is_training=is_training, scope='dropout')
        logits = end_points['Logits'] = slim.fully_connected(
            net, num_classes, activation_fn=None, scope='logits')
    
      end_points['Predictions'] = prediction_fn(logits, scope='Predictions')
      
      return logits, end_points
    
    return cell_type_classifier



        
    
    
    
    
    
    