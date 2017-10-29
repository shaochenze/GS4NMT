import sys
import os
import re
import numpy
import shutil
import wargs
import json
import subprocess
import math

import torch as tc
import torch.nn as nn
from torch.autograd import Variable

def str1(content, encoding='utf-8'):
    return json.dumps(content, encoding=encoding, ensure_ascii=False, indent=4)
    pass

#DEBUG = True
DEBUG = False

PAD = 0
UNK = 1
BOS = 2
EOS = 3

PAD_WORD = '<pad>'
UNK_WORD = 'unk'
BOS_WORD = '<b>'
EOS_WORD = '<e>'

epsilon = 1e-20

# x, y are torch Tensors
def cor_coef(x, y):

    E_x, E_y = tc.mean(x), tc.mean(y)
    E_x_2, E_y_2 = tc.mean(x * x), tc.mean(y * y)
    rho = tc.mean(x * y) - E_x * E_y
    D_x, D_y = E_x_2 - E_x * E_x, E_y_2 - E_y * E_y
    return rho / math.sqrt(D_x * D_y) + eps

def to_pytorch_state_dict(model, eid, bid, optim):

    model_dict = model.state_dict()
    model_dict = {k: v for k, v in model_dict.items() if 'classifier' not in k}

    class_dict = model.classifier.state_dict()

    state_dict = {
        'model': model_dict,
        'class': class_dict,
        'epoch': eid,
        'batch': bid,
        'optim': optim
    }

    return state_dict

def load_pytorch_model(model_path):

    state_dict = tc.load(model_path, map_location=lambda storage, loc: storage)

    model_dict = state_dict['model']
    class_dict = state_dict['class']
    eid, bid, optim = state_dict['epoch'], state_dict['batch'], state_dict['optim']

    wlog('Loading pre-trained model from {} at epoch {} and batch {}'.format(model_path, eid, bid))

    wlog('Loading optimizer from {}'.format(model_path))
    wlog(optim)

    return model_dict, class_dict, eid, bid, optim

def format_time(time):
    '''
        :type time: float
        :param time: the number of seconds

        :print the text format of time
    '''
    rst = ''
    if time < 0.1: rst = '{:7.2f} ms'.format(time * 1000)
    elif time < 60: rst = '{:7.5f} sec'.format(time)
    elif time < 3600: rst = '{:6.4f} min'.format(time / 60.)
    else: rst = '{:6.4f} hr'.format(time / 3600.)

    return rst

def append_file(filename, content):

    f = open(filename, 'a')
    f.write(content + '\n')
    f.close()

def str_cat(pp, name):

    return '{}_{}'.format(pp, name)

def wlog(obj, newline=1):

    if newline: sys.stderr.write('{}\n'.format(obj))
    else: sys.stderr.write('{}'.format(obj))

def debug(s, nl=True):

    if DEBUG:
        if nl: sys.stderr.write('{}\n'.format(s))
        else: sys.stderr.write(s)
        sys.stderr.flush()

def get_gumbel(LB, V, eps=1e-30):

    return Variable(
        -tc.log(-tc.log(tc.Tensor(LB, V).uniform_(0, 1) + eps) + eps), requires_grad=False)

def LBtensor_to_StrList(x, xs_L):

    B = x.size(1)
    x = x.data.numpy().T
    xs = []
    for bid in range(B):
        x_one = x[bid][:int(xs_L[bid])]
        #x_one = str(x_one.astype('S10'))[1:-1].replace('\n', '')
        x_one = str(x_one.astype('S10')).replace('\n', '')
        #x_one = x_one.__str__().replace('  ', ' ')[2:-1]
        xs.append(x_one)
    return xs

def LBtensor_to_Str(x, xs_L):

    B = x.size(1)
    x = x.data.numpy().T
    xs = []
    for bid in range(B):
        x_one = x[bid][:int(xs_L[bid])]
        #x_one = str(x_one.astype('S10'))[1:-1].replace('\n', '')
        x_one = str(x_one.astype('S10')).replace('\n', '')
        #x_one = x_one.__str__().replace('  ', ' ')[2:-1]
        xs.append(x_one)
    return '\n'.join(xs)

def init_params(p, name='what', uniform=False):

    if uniform is True:
        wlog('Uniform \t {} '.format(name))
        p.data.uniform_(-0.1, 0.1)
    else:
        if len(p.size()) == 2:
            if p.size(0) == 1 or p.size(1) == 1:
                wlog('Zero \t {} '.format(name))
                p.data.zero_()
            else:
                wlog('Normal \t {} '.format(name))
                p.data.normal_(0, 0.01)
        elif len(p.size()) == 1:
            wlog('Zero \t {} '.format(name))
            p.data.zero_()

def init_dir(dir_name, delete=False):

    if not dir_name == '':
        if os.path.exists(dir_name):
            if delete:
                shutil.rmtree(dir_name)
                wlog('\n{} exists, delete'.format(dir_name))
            else:
                wlog('\n{} exists, no delete'.format(dir_name))
        else:
            os.mkdir(dir_name)
            wlog('\nCreate {}'.format(dir_name))

def part_sort(vec, num):
    '''
    vec:    [ 3,  4,  5, 12,  1,  3,  29999, 33,  2, 11,  0]
    '''

    idx = numpy.argpartition(vec, num)[:num]

    '''
    put k-min numbers before the _th position and get indexes of the k-min numbers in vec (unsorted)
    idx = np.argpartition(vec, 5)[:5]:
        [ 4, 10,  8,  0,  5]
    '''

    kmin_vals = vec[idx]

    '''
    kmin_vals:  [1, 0, 2, 3, 3]
    '''

    k_rank_ids = numpy.argsort(kmin_vals)

    '''
    k_rank_ids:    [1, 0, 2, 3, 4]
    '''

    k_rank_ids_invec = idx[k_rank_ids]

    '''
    k_rank_ids_invec:  [10,  4,  8,  0,  5]
    '''

    '''
    sorted_kmin = vec[k_rank_ids_invec]
    sorted_kmin:    [0, 1, 2, 3, 3]
    '''

    return k_rank_ids_invec


# beam search
def init_beam(beam, cnt=50, score_0=0.0, loss_0=0.0, hs0=None, s0=None, detail=False):
    del beam[:]
    for i in range(cnt + 1):
        ibeam = []  # one beam [] for one char besides start beam
        beam.append(ibeam)
    # indicator for the first target word (<b>)
    if detail:
        beam[0].append((loss_0, hs0, s0, BOS, 0))
    else:
        beam[0].append((loss_0, s0, BOS, 0))

def back_tracking(beam, best_sample_endswith_eos):
    # (0.76025655120611191, [29999], 0, 7)
    if wargs.len_norm: best_loss, accum, w, bp, endi = best_sample_endswith_eos
    else: best_loss, w, bp, endi = best_sample_endswith_eos
    # starting from bp^{th} item in previous {end-1}_{th} beam of eos beam, w is <eos>
    seq = []
    check = (len(beam[0][0]) == 4)
    for i in reversed(xrange(1, endi)): # [1, endi-1], not <bos> 0 and <eos> endi
        # the best (minimal sum) loss which is the first one in the last beam,
        # then use the back pointer to find the best path backward
        # <eos> is in pos endi, we do not keep <eos>
        if check:
            _, _, w, backptr = beam[i][bp]
        else:
            _, _, _, w, backptr = beam[i][bp]
        seq.append(w)
        bp = backptr
    return seq[::-1], best_loss  # reverse

def filter_reidx(best_trans, tV_i2w=None, ifmv=False, ptv=None):

    if ifmv and ptv is not None:
        # OrderedDict([(0, 0), (1, 1), (3, 5), (8, 2), (10, 3), (100, 4)])
        # reverse: OrderedDict([(0, 0), (1, 1), (5, 3), (2, 8), (3, 10), (4, 100)])
        # part[index] get the real index in large target vocab firstly
        true_idx = [ptv[i] for i in best_trans]
    else:
        true_idx = best_trans

    true_idx = filter(lambda y: y != BOS and y != EOS, true_idx)

    return idx2sent(true_idx, tV_i2w), true_idx

def sent_filter(sent):

    list_filter = filter(lambda x: x != PAD, sent)

    return list_filter

def idx2sent(vec, vcb_i2w):
    # vec: [int, int, ...]
    r = [vcb_i2w[idx] for idx in vec]
    return ' '.join(r)

def dec_conf():

    wlog('\n######################### Construct Decoder #########################\n')
    if wargs.search_mode == 0: wlog('# Greedy search => ')
    elif wargs.search_mode == 1: wlog('# Naive beam search => ')
    elif wargs.search_mode == 2: wlog('# Cube pruning => ')

    wlog('\t Beam size: {}'
         '\n\t KL_threshold: {}'
         '\n\t Batch decoding: {}'
         '\n\t Vocab normalized: {}'
         '\n\t Length normalized: {}'
         '\n\t Manipulate vocab: {}'
         '\n\t Cube pruning merge way: {}'
         '\n\t Average attent: {}\n\n'.format(
             wargs.beam_size,
             wargs.m_threshold,
             True if wargs.with_batch else False,
             True if wargs.vocab_norm else False,
             True if wargs.len_norm else False,
             True if wargs.with_mv else False,
             wargs.merge_way,
             True if wargs.avg_att else False
         )
    )

''' Layer normalization module '''
class Layer_Norm(nn.Module):

    def __init__(self, d_hid, eps=1e-3):
        super(Layer_Norm, self).__init__()

        self.eps = eps
        self.g = nn.Parameter(tc.ones(d_hid), requires_grad=True)
        self.b = nn.Parameter(tc.zeros(d_hid), requires_grad=True)

    def forward(self, z):

        if z.size(1) == 1: return z
        mu = tc.mean(z, keepdim=True, dim=-1)
        sigma = tc.std(z, keepdim=True, dim=-1)
        ln_out = (z - mu.expand_as(z)) / (sigma.expand_as(z) + self.eps)
        ln_out = ln_out * self.g.expand_as(ln_out) + self.b.expand_as(ln_out)

        return ln_out

class LayerNorm(nn.Module):

    def __init__(self, features, eps=1e-6):
        super(LayerNorm, self).__init__()
        self.gamma = nn.Parameter(tc.ones(features))
        self.beta = nn.Parameter(tc.zeros(features))
        self.eps = eps

    def forward(self, x):
        mean = x.mean(-1, keepdim=True)
        std = x.std(-1, keepdim=True)
        return self.gamma * (x - mean) / (std + self.eps) + self.beta

class LayerNormalization(nn.Module):
    ''' Layer normalization module '''

    def __init__(self, d_hid, eps=1e-3):
        super(LayerNormalization, self).__init__()

        self.eps = eps
        self.a_2 = nn.Parameter(tc.ones(d_hid), requires_grad=True)
        self.b_2 = nn.Parameter(tc.zeros(d_hid), requires_grad=True)

    def forward(self, z):
        if z.size(1) == 1:
            return z

        mu = tc.mean(z, keepdim=True, dim=0)
        sigma = tc.std(z, keepdim=True, dim=0)
        ln_out = (z - mu.expand_as(z)) / (sigma.expand_as(z) + self.eps)
        ln_out = ln_out * self.a_2.expand_as(ln_out) + self.b_2.expand_as(ln_out)

        return ln_out


def memory_efficient(outputs, gold, gold_mask, classifier):

    batch_loss, batch_correct_num = 0, 0
    outputs = Variable(outputs.data, requires_grad=True, volatile=False)
    cur_batch_count = outputs.size(1)

    os_split = tc.split(outputs, wargs.snip_size)
    gs_split = tc.split(gold, wargs.snip_size)
    ms_split = tc.split(gold_mask, wargs.snip_size)

    for i, (o_split, g_split, m_split) in enumerate(zip(os_split, gs_split, ms_split)):

        loss, correct_num = classifier(o_split, g_split, m_split)
        batch_loss += loss.data[0]
        batch_correct_num += correct_num.data[0]
        loss.div(cur_batch_count).backward()
        del loss, correct_num

    grad_output = None if outputs.grad is None else outputs.grad.data

    return batch_loss, grad_output, batch_correct_num
