# Copyright 2019 The TensorFlow Ranking Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

r"""TF Ranking sample code for LETOR datasets in LibSVM format.

WARNING: All data sets are loaded into memory in this sample code. It is
for small data sets whose sizes are < 10G.

A note on the LibSVM format:
--------------------------------------------------------------------------
Due to the sparse nature of features utilized in most academic datasets for
learning to rank such as LETOR datasets, data points are represented in the
LibSVM format. In this setting, every line encapsulates features and a (graded)
relevance judgment of a query-document pair. The following illustrates the
general structure:

<relevance int> qid:<query_id int> [<feature_id int>:<feature_value float>]

For example:

1 qid:10 32:0.14 48:0.97  51:0.45
0 qid:10 1:0.15  31:0.75  32:0.24  49:0.6
2 qid:10 1:0.71  2:0.36   31:0.58  51:0.12
0 qid:20 4:0.79  31:0.01  33:0.05  35:0.27
3 qid:20 1:0.42  28:0.79  35:0.30  42:0.76

In the above example, the dataset contains two queries. Query "10" has 3
documents, two of which relevant with grades 1 and 2. Similarly, query "20"
has 1 relevant document. Note that query-document pairs may have different
sets of zero-valued features and as such their feature vectors may only
partly overlap or not at all.
--------------------------------------------------------------------------

Sample command lines:

OUTPUT_DIR=/tmp/output && \
TRAIN=tensorflow_ranking/examples/data/train.txt && \
VALI=tensorflow_ranking/examples/data/vali.txt && \
TEST=tensorflow_ranking/examples/data/test.txt && \
rm -rf $OUTPUT_DIR && \
bazel build -c opt \
tensorflow_ranking/examples/tf_ranking_libsvm_py_binary && \
./bazel-bin/tensorflow_ranking/examples/tf_ranking_libsvm_py_binary \
--train_path=$TRAIN \
--vali_path=$VALI \
--test_path=$TEST \
--output_dir=$OUTPUT_DIR \
--num_features=136

You can use TensorBoard to display the training results stored in $OUTPUT_DIR.
"""

from absl import flags

import utils.check_folder as cf
import utils.telegram_bot as HERA
from recommenders.tf_ranking import TensorflowRankig
import numpy as np
import six
import tensorflow as tf
import tensorflow_ranking as tfr
import datetime
from utils.best_checkpoint_copier import BestCheckpointCopier



class IteratorInitializerHook(tf.train.SessionRunHook):
  """Hook to initialize data iterator after session is created."""

  def __init__(self):
    super(IteratorInitializerHook, self).__init__()
    self.iterator_initializer_fn = None

  def after_create_session(self, session, coord):
    """Initialize the iterator after the session has been created."""
    del coord
    self.iterator_initializer_fn(session)


def example_feature_columns():
  """Returns the example feature columns."""
  feature_names = ["{}".format(i + 1) for i in range(FLAGS.num_features)]
  return {
      name: tf.feature_column.numeric_column(
          name, shape=(1,), default_value=0.0) for name in feature_names
  }


def load_libsvm_data(path, list_size):
  """Returns features and labels in numpy.array."""

  def _parse_line(line):
    """Parses a single line in LibSVM format."""
    tokens = line.split("#")[0].split()
    assert len(tokens) >= 2, "Ill-formatted line: {}".format(line)
    label = float(tokens[0])
    qid = tokens[1]
    kv_pairs = [kv.split(":") for kv in tokens[2:]]
    features = {k: float(v) for (k, v) in kv_pairs}
    return qid, features, label

  tf.logging.info("Loading data from {}".format(path))

  # The 0-based index assigned to a query.
  qid_to_index = {}
  # The number of docs seen so far for a query.
  qid_to_ndoc = {}
  # Each feature is mapped an array with [num_queries, list_size, 1]. Label has
  # a shape of [num_queries, list_size]. We use list for each of them due to the
  # unknown number of quries.
  feature_map = {k: [] for k in example_feature_columns()}
  label_list = []
  total_docs = 0
  discarded_docs = 0
  with open(path, "rt") as f:
    for line in f:
      qid, features, label = _parse_line(line)
      if qid not in qid_to_index:
        # Create index and allocate space for a new query.
        qid_to_index[qid] = len(qid_to_index)
        qid_to_ndoc[qid] = 0
        for k in feature_map:
          feature_map[k].append(np.zeros([list_size, 1], dtype=np.float32))
        label_list.append(np.ones([list_size], dtype=np.float32) * -1.)
      total_docs += 1
      batch_idx = qid_to_index[qid]
      doc_idx = qid_to_ndoc[qid]
      qid_to_ndoc[qid] += 1
      # Keep the first 'list_size' docs only.
      if doc_idx >= list_size:
        discarded_docs += 1
        continue
      for k, v in six.iteritems(features):
        assert k in feature_map, "Key {} not found in features.".format(k)
        feature_map[k][batch_idx][doc_idx, 0] = v
      label_list[batch_idx][doc_idx] = label

  tf.logging.info("Number of queries: {}".format(len(qid_to_index)))
  tf.logging.info("Number of documents in total: {}".format(total_docs))
  tf.logging.info("Number of documents discarded: {}".format(discarded_docs))

  # Convert everything to np.array.
  for k in feature_map:
    feature_map[k] = np.array(feature_map[k])
  return feature_map, np.array(label_list)


def get_train_inputs(features, labels, batch_size):
  """Set up training input in batches."""
  iterator_initializer_hook = IteratorInitializerHook()

  def _train_input_fn():
    """Defines training input fn."""
    features_placeholder = {
        k: tf.placeholder(v.dtype, v.shape) for k, v in six.iteritems(features)
    }
    labels_placeholder = tf.placeholder(labels.dtype, labels.shape)
    dataset = tf.data.Dataset.from_tensor_slices((features_placeholder,
                                                  labels_placeholder))

    dataset = dataset.shuffle(1000).repeat().batch(batch_size)

    #1000
    iterator = dataset.make_initializable_iterator()
    feed_dict = {labels_placeholder: labels}
    feed_dict.update(
        {features_placeholder[k]: features[k] for k in features_placeholder})
    iterator_initializer_hook.iterator_initializer_fn = (
        lambda sess: sess.run(iterator.initializer, feed_dict=feed_dict))
    return iterator.get_next()
  return _train_input_fn, iterator_initializer_hook

def get_batches(features, labels, batch_size):
  """Set up training input in batches."""
  iterator_initializer_hook = IteratorInitializerHook()

  def _train_input_fn():
    """Defines training input fn."""
    features_placeholder = {
        k: tf.placeholder(v.dtype, v.shape) for k, v in six.iteritems(features)
    }
    labels_placeholder = tf.placeholder(labels.dtype, labels.shape)
    dataset = tf.data.Dataset.from_tensor_slices((features_placeholder,
                                                  labels_placeholder))

    dataset = dataset.batch(batch_size)

    #1000
    iterator = dataset.make_initializable_iterator()
    feed_dict = {labels_placeholder: labels}
    feed_dict.update(
        {features_placeholder[k]: features[k] for k in features_placeholder})
    iterator_initializer_hook.iterator_initializer_fn = (
        lambda sess: sess.run(iterator.initializer, feed_dict=feed_dict))
    return iterator.get_next()
  return _train_input_fn, iterator_initializer_hook


def batch_inputs(features, labels, batch_size):
    dataset = tf.data.Dataset.from_tensor_slices((features, labels))
    return dataset.batch(batch_size)

def make_score_fn():
  """Returns a groupwise score fn to build `EstimatorSpec`."""

  def _score_fn(unused_context_features, group_features, mode, unused_params,
                unused_config):
    """Defines the network to score a group of documents."""

    with tf.name_scope("input_layer"):
      names = sorted(example_feature_columns())
      group_input = [
          tf.layers.flatten(group_features[name])

          for name in names
      ]
      input_layer = tf.concat(group_input, 1)
      tf.summary.scalar("input_sparsity", tf.nn.zero_fraction(input_layer))
      tf.summary.scalar("input_max", tf.reduce_max(input_layer))

      tf.summary.scalar("input_min", tf.reduce_min(input_layer))

    is_training = (mode == tf.estimator.ModeKeys.TRAIN)
    cur_layer = tf.layers.batch_normalization(input_layer, training=is_training)
    for i, layer_width in enumerate(int(d) for d in FLAGS.hidden_layer_dims):
      cur_layer = tf.layers.dense(cur_layer, units=layer_width)
      cur_layer = tf.layers.batch_normalization(cur_layer, training=is_training)
      cur_layer = tf.nn.relu(cur_layer)
      tf.summary.scalar("fully_connected_{}_sparsity".format(i),
                        tf.nn.zero_fraction(cur_layer))
      cur_layer = tf.layers.dropout(
    cur_layer, rate=FLAGS.dropout_rate, training=is_training)
    logits = tf.layers.dense(cur_layer, units=FLAGS.group_size)
    return logits

  return _score_fn


def get_eval_metric_fns():
  """Returns a dict from name to metric functions."""
  metric_fns = {}
  metric_fns.update({
      "metric/%s" % name: tfr.metrics.make_ranking_metric_fn(name) for name in [
          tfr.metrics.RankingMetricKey.MRR,
      ]
  })
  return metric_fns


def train_and_eval():
  """Train and Evaluate."""

  features, labels = load_libsvm_data(FLAGS.train_path, FLAGS.list_size)
  train_input_fn, train_hook = get_train_inputs(features, labels,
                                                FLAGS.train_batch_size)

  features_vali, labels_vali = load_libsvm_data(FLAGS.vali_path,
                                                FLAGS.list_size)
  vali_input_fn, vali_hook = get_batches(features_vali, labels_vali,
                                                FLAGS.train_batch_size)

  def _train_op_fn(loss):
    """Defines train op used in ranking head."""
    return tf.contrib.layers.optimize_loss(
        loss=loss,
        global_step=tf.train.get_global_step(),
        learning_rate=FLAGS.learning_rate,
        optimizer="Adagrad")
  #Adagrad

  best_copier = BestCheckpointCopier(
      name='best',  # directory within model directory to copy checkpoints to
      checkpoints_to_keep=1,  # number of checkpoints to keep
      score_metric='metric/mrr',  # metric to use to determine "best"
      compare_fn=lambda x, y: x.score < y.score,
      # comparison function used to determine "best" checkpoint (x is the current checkpoint; y is the previously copied checkpoint with the highest/worst score)
      sort_key_fn=lambda x: x.score,
      sort_reverse=True,
      dataset_name=FLAGS.dataset_name,
      save_path=f'{FLAGS.save_path}',
      #save_path=f'dataset/preprocessed/tf_ranking/{_CLUSTER}/full/{_DATASET_NAME}/predictions',
      test_x=features_vali,
      test_y=labels_vali,
      mode=FLAGS.mode,
      loss=FLAGS.loss,
      min_mrr_start=FLAGS.min_mrr_start,
      params=FLAGS
      )


  ranking_head = tfr.head.create_ranking_head(
      loss_fn=tfr.losses.make_loss_fn(FLAGS.loss, lambda_weight=tfr.losses.create_reciprocal_rank_lambda_weight(smooth_fraction=0.5, topn=25)),
      eval_metric_fns=get_eval_metric_fns(),
      train_op_fn=_train_op_fn)

  #weights_feature_name=FLAGS.weights_feature_number
  #lambda_weight=tfr.losses.create_reciprocal_rank_lambda_weight(smooth_fraction=0.5)

  estimator = tf.estimator.Estimator(
      model_fn=tfr.model.make_groupwise_ranking_fn(
          group_score_fn=make_score_fn(),
          group_size=FLAGS.group_size,
          transform_fn=None,
          #tfr.feature.make_identity_transform_fn(['5'])
          ranking_head=ranking_head),
    config=tf.estimator.RunConfig(
      FLAGS.output_dir, save_checkpoints_steps=1000))


  train_spec = tf.estimator.TrainSpec(
      input_fn=train_input_fn,
      hooks=[train_hook],
      max_steps=FLAGS.num_train_steps)
  vali_spec = tf.estimator.EvalSpec(
      input_fn=vali_input_fn,
      hooks=[vali_hook],
      steps=None,
      exporters=best_copier,
      start_delay_secs=0,
      throttle_secs=30)

  # Train and validate
  tf.estimator.train_and_evaluate(estimator, train_spec, vali_spec)

def train_and_test():
    features, labels = load_libsvm_data(FLAGS.train_path, FLAGS.list_size)
    train_input_fn, train_hook = get_train_inputs(features, labels,
                                                  FLAGS.train_batch_size)
    features_test, labels_test = load_libsvm_data(FLAGS.test_path,
                                                  FLAGS.list_size)

    def _train_op_fn(loss):
        """Defines train op used in ranking head."""
        return tf.contrib.layers.optimize_loss(
            loss=loss,
            global_step=tf.train.get_global_step(),
            learning_rate=FLAGS.learning_rate,
            optimizer="Adagrad")

    ranking_head = tfr.head.create_ranking_head(
        loss_fn=tfr.losses.make_loss_fn(FLAGS.loss, lambda_weight=tfr.losses.create_reciprocal_rank_lambda_weight(topn=25)),
        eval_metric_fns=get_eval_metric_fns(),
        train_op_fn=_train_op_fn)
    # tfr.losses.create_p_list_mle_lambda_weight(25)
    # lambda_weight=tfr.losses.create_reciprocal_rank_lambda_weight()

    estimator = tf.estimator.Estimator(
        model_fn=tfr.model.make_groupwise_ranking_fn(
            group_score_fn=make_score_fn(),
            group_size=FLAGS.group_size,
            transform_fn=None,
            ranking_head=ranking_head))

    estimator.train(train_input_fn, hooks=[train_hook], steps=FLAGS.num_train_steps)

    pred = np.array(list(estimator.predict(lambda: batch_inputs(features_test, labels_test, 128))))

    pred_name=f'predictions_{FLAGS.loss}_learning_rate_{FLAGS.learning_rate}_train_batch_size_{FLAGS.train_batch_size}_' \
        f'hidden_layers_dim_{FLAGS.hidden_layer_dims}_num_train_steps_{FLAGS.num_train_steps}_dropout_{FLAGS.dropout_rate}_{FLAGS.grup_size}'
    np.save(f'{FLAGS.save_path}/{pred_name}', pred)

    HERA.send_message(f'EXPORTING A SUB... mode:{FLAGS.mode}')
    model = TensorflowRankig(mode=FLAGS.mode, cluster='no_cluster', dataset_name=FLAGS.dataset_name,
                             pred_name=pred_name)
    model.name = f'tf_ranking_{pred_name}'
    model.run()
    HERA.send_message(f'EXPORTED... mode:{FLAGS.mode}')


def main(_):
  tf.logging.set_verbosity(tf.logging.INFO)

  if FLAGS.mode == 'full':
    train_and_test()
  else:
    train_and_eval()


if __name__ == "__main__":

    print('type mode: small, local or full')
    _MODE = input()
    print('type cluster')
    _CLUSTER=input()
    print('type dataset_name')
    _DATASET_NAME = input()
    _BASE_PATH = f'dataset/preprocessed/tf_ranking/{_CLUSTER}/{_MODE}/{_DATASET_NAME}'
    _TRAIN_PATH = f'{_BASE_PATH}/train.txt'
    _TEST_PATH = f'{_BASE_PATH}/test.txt'
    _VALI_PATH = f'{_BASE_PATH}/vali.txt'

    cf.check_folder(f'{_BASE_PATH}/output_dir_{datetime.datetime.now().strftime("%Y-%m-%d_%H:%M")}')
    _OUTPUT_DIR = f'{_BASE_PATH}/output_dir_{datetime.datetime.now().strftime("%Y-%m-%d_%H:%M")}'

    flags.DEFINE_string("save_path", _BASE_PATH, "path used for save the predictions")
    flags.DEFINE_string("train_path", _TRAIN_PATH, "Input file path used for training.")
    flags.DEFINE_string("vali_path", _VALI_PATH, "Input file path used for validation.")
    flags.DEFINE_string("test_path", _TEST_PATH, "Input file path used for testing.")
    flags.DEFINE_string("output_dir", _OUTPUT_DIR, "Output directory for models.")
    flags.DEFINE_string("mode", _MODE, "mode of the models.")
    flags.DEFINE_string("dataset_name", _DATASET_NAME, "name of the dataset")


    # let the user choose the params
    print('insert the min_MRR from which export the sub')
    min_mrr = input()
    print('insert train batch size')
    train_batch_size = input()
    print('insert learning rate')
    learning_rate = input()
    print('insert dropout rate')
    dropout_rate = input()
    print('insert hidden layer dims as numbers separeted by spaces')
    hidden_layer_dims = input().split(' ')
    print('select loss:\n'
          '1) PAIRWISE_HINGE_LOSS\n'
          '2) PAIRWISE_LOGISTIC_LOSS\n'
          '3) PAIRWISE_SOFT_ZERO_ONE_LOSS\n'
          '4) SOFTMAX_LOSS\n'
          '5) SIGMOID_CROSS_ENTROPY_LOSS\n'
          '6) MEAN_SQUARED_LOSS\n'
          '7) LIST_MLE_LOSS\n'
          '8) APPROX_NDCG_LOSS\n')

    selection=input()
    loss = None
    if selection == '1':
        loss = 'pairwise_hinge_loss'
    elif selection == '2':
        loss = 'pairwise_logistic_loss'
    elif selection == '3':
        loss = 'pairwise_soft_zero_one_loss'
    elif selection == '4':
        loss = 'softmax_loss'
    elif selection == '5':
        loss = 'sigmoid_cross_entropy_loss'
    elif selection == '6':
        loss = 'mean_squared_loss'
    elif selection == '7':
        loss = 'list_mle_loss'
    elif selection == '8':
        loss = 'approx_ndcg_loss'

    if _MODE == 'full':
        print('insert_num_train_step')
        num_train_steps = input()
    else:
        num_train_steps = None

    flags.DEFINE_float("min_mrr_start", min_mrr, "min_mrr_from_which_save_model")
    flags.DEFINE_integer("train_batch_size", train_batch_size, "The batch size for training.")
    # 32
    flags.DEFINE_integer("num_train_steps", num_train_steps, "Number of steps for training.")
    flags.DEFINE_float("learning_rate", learning_rate, "Learning rate for optimizer.")
    #0.01
    flags.DEFINE_float("dropout_rate", dropout_rate, "The dropout rate before output layer.")
    # 0.5
    flags.DEFINE_list("hidden_layer_dims", hidden_layer_dims,
                    "Sizes for hidden layers.")
    # ["256", "128", "64"]
    # best ["256", "128"]

    flags.DEFINE_integer("num_features", 58, "Number of features per document.")
    flags.DEFINE_integer("list_size", 25, "List size used for training.")
    flags.DEFINE_integer("group_size", 1, "Group size used in score function.")
    #1

    flags.DEFINE_string("loss", loss,
                      "The RankingLossKey for loss function.")

    FLAGS = flags.FLAGS

    tf.app.run()
