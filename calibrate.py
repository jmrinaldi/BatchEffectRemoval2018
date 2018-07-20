'''
Created on Jul 6, 2018

@author: urishaham
The script is based on https://github.com/LynnHo/VAE-Tensorflow
WGAN-gp code is based on on https://github.com/LynnHo/DCGAN-LSGAN-WGAN-WGAN-GP-Tensorflow/blob/master/models_mnist.py

'''
import numpy as np
import argparse
import datetime
import json
import shutil
import traceback
from functools import partial
import os.path
from sklearn import decomposition
import tensorflow as tf
import os

import tflib as tl
import utils
import pylib
import scatterHist as sh


# ==============================================================================
# =                                inputs arguments                            =
# ==============================================================================

# TODO: delete for public version
if os.path.exists('./output'):
    shutil.rmtree('./output')

parser = argparse.ArgumentParser()
parser.add_argument('--use_test', dest='use_test', type=int, default=True, 
                    help="wether there are separate test data files")
parser.add_argument('--n_epochs', dest='n_epochs', type=int, default=200, help="number of training epochs")
parser.add_argument('--batch_size', dest='batch_size', type=int, default=64, help="minibatch size")
parser.add_argument('--lr', dest='lr', type=float, default=1e-3, help='initial learning rate')
parser.add_argument('--code_dim', dest='code_dim', type=int, default=15, help='dimension of code space')
parser.add_argument('--beta', dest='beta', type=float, default=.1, help="KL coefficient")
parser.add_argument('--gamma', dest='gamma', type=float, default=100, help="adversarial loss coefficient")
parser.add_argument('--delta', dest='delta', type=float, default=.1, help="gp loss coefficient")
parser.add_argument('--data_path', dest='data_path', default='./Data', help="path to data folder")
parser.add_argument('--data_type', dest='data_type', default='cytof', help="type of data")
parser.add_argument('--model', dest='model_name', default='cytof_transformer', help="model architecture, \
                    either cytof_basic of cytof_transformer")
parser.add_argument('--experiment_name', dest='experiment_name', 
                    default=datetime.datetime.now().strftime("%I:%M%p on %B %d, %Y"))

args = parser.parse_args()

use_test = args.use_test
n_epochs = args.n_epochs
batch_size = args.batch_size
lr = args.lr
code_dim = args.code_dim
beta = args.beta
gamma = args.gamma
delta = args.delta
data_path = args.data_path
data_type = args.data_type
model_name = args.model_name
experiment_name = args.experiment_name

pylib.mkdir('./output/%s' % experiment_name)
with open('./output/%s/setting.txt' % experiment_name, 'w') as f:
    f.write(json.dumps(vars(args), indent=4, separators=(',', ':')))
    
# ==============================================================================
# =                            datasets and models                             =
# ==============================================================================

source_train_data, target_train_data, source_test_data, target_test_data, \
    min_n, preprocessor = utils.get_data(data_path, data_type, use_test)
source_train_dataset = utils.make_dataset(source_train_data, batch_size = batch_size)
target_train_dataset = utils.make_dataset(target_train_data, batch_size = batch_size)
s_iterator = source_train_dataset.make_one_shot_iterator()
s_next_element = s_iterator.get_next()
t_iterator = target_train_dataset.make_one_shot_iterator()
t_next_element = t_iterator.get_next()

input_dim = source_train_data.shape[1]
Enc, Dec_a, Dec_b, Disc = utils.get_models(model_name)
Enc = partial(Enc, code_dim=code_dim)
Dec_a = partial(Dec_a, output_dim=input_dim) 
Dec_b = partial(Dec_b, output_dim=input_dim)

# ==============================================================================
# =                                    graph                                   =
# ==============================================================================

def enc_dec(input, is_training=True):
    # encode
    c_mu, c_log_sigma_sq = Enc(input, is_training=is_training)

    # sample a code
    epsilon = tf.random_normal(tf.shape(c_mu))
    if is_training:
        c = c_mu + tf.sqrt(tf.exp(c_log_sigma_sq)) * epsilon
    else:
        c = c_mu

    # reconstruct code
    rec_a = Dec_a(c, is_training=is_training)
    rec_b = Dec_b(c, is_training=is_training)

    return c_mu, c_log_sigma_sq, c, rec_a, rec_b

# input
input_a = tf.placeholder(tf.float32, [None, input_dim])
input_b = tf.placeholder(tf.float32, [None, input_dim])

# encode & decode
c_mu_a, c_log_sigma_sq_a, c_a, rec_a, _ = enc_dec(input_a)
c_mu_b, c_log_sigma_sq_b, c_b, _, rec_b = enc_dec(input_b)

_, _, c_a1, rec_a1, _ = enc_dec(input_a, is_training=False)
_, _, c_b1, _, rec_b1 = enc_dec(input_b, is_training=False)

Disc_a = Disc(c_a)
Disc_b = Disc(c_b)


# G loss components
rec_loss_a = tf.losses.mean_squared_error(input_a, rec_a)
rec_loss_b = tf.losses.mean_squared_error(input_b, rec_b)
rec_loss = rec_loss_a + rec_loss_b

kld_loss_a = -tf.reduce_mean(0.5 * (1 + c_log_sigma_sq_a - c_mu_a**2 - tf.exp(c_log_sigma_sq_a)))
kld_loss_b = -tf.reduce_mean(0.5 * (1 + c_log_sigma_sq_b - c_mu_b**2 - tf.exp(c_log_sigma_sq_a)))
kld_loss = kld_loss_a + kld_loss_b

adv_loss =  tf.losses.mean_squared_error(tf.reduce_mean(Disc_a), tf.reduce_mean(Disc_b))

G_loss = rec_loss + kld_loss * beta + adv_loss * gamma

# D loss components
wd_loss = tf.reduce_mean(Disc_b) - tf.reduce_mean(Disc_a)
gp_loss = utils.gradient_penalty(c_a, c_b, Disc)


D_loss = wd_loss + gp_loss * delta


# otpimizers
d_vars = utils.trainable_variables('discriminator')
g_vars = utils.trainable_variables(['Encoder', 'Decoder_a', 'Decoder_b'])


G_step = tf.train.AdamOptimizer(learning_rate=lr, beta1=0.5).minimize(G_loss, var_list=g_vars)
D_step = tf.train.AdamOptimizer(learning_rate=lr, beta1=0.5).minimize(D_loss, var_list=d_vars)

# summary
G_summary = tl.summary({rec_loss_a: 'rec_loss_a',
                      rec_loss_b: 'rec_loss_b',
                      rec_loss: 'rec_loss',
                      kld_loss_a: 'kld_loss_a',
                      kld_loss_b: 'kld_loss_b',
                      kld_loss: 'kld_loss',
                      adv_loss: 'adv_loss',
                      G_loss: 'G_loss'})
D_summary = tl.summary({wd_loss: 'wd_loss',
                      gp_loss: 'gp_loss',
                      D_loss: 'D_loss'})


# ==============================================================================
# =                                    train                                   =
# ==============================================================================

# number of points to plot during training    
n_s = np.min([len(source_train_data),10000]) 
n_t = np.min([len(target_train_data),10000])    

# compute PCA
pca = decomposition.PCA()
pca.fit(target_train_data)
pc1 = 0
pc2 = 1
axis1 = 'PC'+str(pc1)
axis2 = 'PC'+str(pc2)
    
# session
sess = tl.session()

# saver
saver = tf.train.Saver(max_to_keep=1)

# summary writer
summary_writer = tf.summary.FileWriter('./output/%s/summaries' % experiment_name, sess.graph)

# initialization
ckpt_dir = './output/%s/checkpoints' % experiment_name
pylib.mkdir(ckpt_dir)
try:
    tl.load_checkpoint(ckpt_dir, sess)
except:
    sess.run(tf.global_variables_initializer())


# train
iters_per_epoch = int(min_n/batch_size)
overall_it = 0
try:

    for ep in range(n_epochs):
        for it in range(iters_per_epoch):
            overall_it += 1
            t_batch = sess.run(t_next_element)
            s_batch = sess.run(s_next_element)


            # train D
            D_summary_opt, _ = sess.run([D_summary, D_step], 
                                        feed_dict={input_a: t_batch, input_b:s_batch})
            summary_writer.add_summary(D_summary_opt, overall_it)
            
            # train G
            g_summary_opt, _ = sess.run([G_summary, G_step], 
                                        feed_dict={input_a: t_batch, input_b:s_batch})
            summary_writer.add_summary(g_summary_opt, overall_it)

            # display
            if (it + 1) % 1 == 0:
                print("Epoch: (%3d/%5d) iteration: (%5d/%5d)" % (ep+1,n_epochs, it+1, iters_per_epoch))
                
        s_cal = sess.run(rec_a1, feed_dict={input_a: source_train_data[:n_s]})
        t_rec = sess.run(rec_a1, feed_dict={input_a: target_train_data[:n_t]})
        
        save_dir = './output/%s/sample_training' % experiment_name
        save_path = saver.save(sess, '%s/Epoch_%d.ckpt' % (ckpt_dir, ep))
        print('Model is saved in file: %s' % save_path)
except:
    traceback.print_exc()
finally:
    sess.close()

# ==============================================================================
# =                 visualize calibration on test data                         =
# ==============================================================================

sess = tl.session()

try:
    tl.load_checkpoint(ckpt_dir, sess)
except:
    sess.run(tf.global_variables_initializer())

t_rec_train, t_c_train = sess.run([rec_a1, c_a1], feed_dict={input_a: target_train_data})
s_cal_train = sess.run(rec_a1, feed_dict={input_a: source_train_data})
s_rec_train, s_c_train = sess.run([rec_b1, c_b1], feed_dict={input_b: source_train_data})  
if use_test:
    t_rec_test, t_c_test = sess.run([rec_a1, c_a1], feed_dict={input_a: target_test_data})
    s_cal_test = sess.run(rec_a1, feed_dict={input_a: source_test_data})
    s_rec_test, s_c_test = sess.run([rec_b1, c_b1], feed_dict={input_b: source_test_data})  


sess.close()


target_pca = pca.transform(target_train_data)
source_pca = pca.transform(source_train_data)
sh.scatterHist(target_pca[:,pc1], target_pca[:,pc2], source_pca[:,pc1], 
            source_pca[:,pc2], axis1, axis2, title="train data before calibration",
            name1='target', name2='source')


target_rec_pca = pca.transform(t_rec_train)
source_cal_pca = pca.transform(s_cal_train)
sh.scatterHist(target_rec_pca[:,pc1], target_rec_pca[:,pc2], 
               source_cal_pca[:,pc1], source_cal_pca[:,pc2], axis1, axis2, 
               title="train data after calibration", name1='target', name2='source')

# ==============================================================================
# =                                  save data                                 =
# ==============================================================================

# save data for visualization
save_dir = './output/%s/calibrated_data' % experiment_name
pylib.mkdir(save_dir)
np.savetxt(fname=save_dir+'/calibrated_source_train_data.csv', X=s_cal_train, delimiter=',')
np.savetxt(fname=save_dir+'/reconstructed_source_train_data.csv', X=s_rec_train, delimiter=',')
np.savetxt(fname=save_dir+'/reconstructed_target_train_data.csv', X=t_rec_train, delimiter=',')
np.savetxt(fname=save_dir+'/source_train_data.csv', X=source_train_data, delimiter=',')
np.savetxt(fname=save_dir+'/target_train_data.csv', X=target_train_data, delimiter=',')
np.savetxt(fname=save_dir+'/source_train_code.csv', X=s_c_train, delimiter=',')
np.savetxt(fname=save_dir+'/target_train_code.csv', X=t_c_train, delimiter=',')
if use_test:
    np.savetxt(fname=save_dir+'/calibrated_source_test_data.csv', X=s_cal_test, delimiter=',')
    np.savetxt(fname=save_dir+'/reconstructed_source_test_data.csv', X=s_rec_test, delimiter=',')
    np.savetxt(fname=save_dir+'/reconstructed_target_test_data.csv', X=t_rec_test, delimiter=',')
    np.savetxt(fname=save_dir+'/source_test_data.csv', X=source_test_data, delimiter=',')
    np.savetxt(fname=save_dir+'/target_test_data.csv', X=target_test_data, delimiter=',')
    np.savetxt(fname=save_dir+'/source_test_code.csv', X=s_c_test, delimiter=',')
    np.savetxt(fname=save_dir+'/target_test_code.csv', X=t_c_test, delimiter=',')
    
# save data in original scale
save_dir = './output/%s/calibrated_data_org_scale' % experiment_name 
pylib.mkdir(save_dir)

target_train_data = utils.recover_org_scale(target_train_data, data_type, preprocessor)
source_train_data = utils.recover_org_scale(source_train_data, data_type, preprocessor)
t_rec_train = utils.recover_org_scale(t_rec_train, data_type, preprocessor)
s_cal_train = utils.recover_org_scale(s_cal_train, data_type, preprocessor)
np.savetxt(fname=save_dir+'/source_train_data.csv', X=source_train_data, delimiter=',')
np.savetxt(fname=save_dir+'/target_train_data.csv', X=target_train_data, delimiter=',')
np.savetxt(fname=save_dir+'/calibrated_source_train_data.csv', X=s_cal_train, delimiter=',')
np.savetxt(fname=save_dir+'/caalibrated_source_train_data.csv', X=t_rec_train, delimiter=',')
if use_test:
    target_test_data = utils.recover_org_scale(target_test_data, data_type, preprocessor)
    source_test_data = utils.recover_org_scale(source_test_data, data_type, preprocessor)
    t_rec_test = utils.recover_org_scale(t_rec_test, data_type, preprocessor)
    s_cal_test = utils.recover_org_scale(s_cal_test, data_type, preprocessor)
    np.savetxt(fname=save_dir+'/source_test_data.csv', X=source_train_data, delimiter=',')
    np.savetxt(fname=save_dir+'/target_test_data.csv', X=target_train_data, delimiter=',')
    np.savetxt(fname=save_dir+'/calibrated_source_test_data.csv', X=s_cal_train, delimiter=',')
    np.savetxt(fname=save_dir+'/calibrated_source_test_data.csv', X=t_rec_train, delimiter=',')

print ('Data saved successfully')
input("Press Enter to exit")     
