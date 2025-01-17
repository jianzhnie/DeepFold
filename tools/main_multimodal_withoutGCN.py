import argparse
import logging
import os
import sys
import time

import torch
import torch.backends.cudnn as cudnn
import torch.distributed as dist
import torch.optim as optim
import torch.utils.data
import torch.utils.data.distributed
import yaml
from torch.utils.data import DataLoader

from deepfold.data.gcn_dataset import GCNDataset
from deepfold.models.esm_model import MLP
from deepfold.trainer.training import train_loop
from deepfold.utils.make_graph import build_graph
from deepfold.utils.model import load_model_checkpoint
from deepfold.utils.random_utils import random_seed

sys.path.append('../')

try:
    import wandb
    has_wandb = True
except ImportError:
    has_wandb = False

# The first arg parser parses out only the --config argument, this argument is used to
# load a yaml file containing key-values that override the defaults for the main parser below
config_parser = parser = argparse.ArgumentParser(description='Training Config',
                                                 add_help=False)
parser.add_argument('-c',
                    '--config',
                    default='',
                    type=str,
                    metavar='FILE',
                    help='YAML config file specifying default arguments')
parser = argparse.ArgumentParser(
    description='Protein function Classification Model Train config')
parser.add_argument('--data_path',
                    default='',
                    type=str,
                    help='data dir of dataset')
parser.add_argument('--train_file_name',
                    default='',
                    type=str,
                    help='data dir of dataset')
parser.add_argument('--val_file_name',
                    default='',
                    type=str,
                    help='data dir of dataset')
parser.add_argument('--namespace', default='', type=str, help='cco, mfo, bpo')
parser.add_argument('--model',
                    metavar='MODEL',
                    default='protgcn',
                    help='model architecture: (default: protgcn)')
parser.add_argument('--resume',
                    default=None,
                    type=str,
                    metavar='PATH',
                    help='path to latest checkpoint (default: none)')
parser.add_argument('--epochs',
                    default=90,
                    type=int,
                    metavar='N',
                    help='number of total epochs to run')
parser.add_argument('--start-epoch',
                    default=0,
                    type=int,
                    metavar='N',
                    help='manual epoch number (useful on restarts)')
parser.add_argument('-j',
                    '--workers',
                    type=int,
                    default=4,
                    metavar='N',
                    help='how many training processes to use (default: 1)')
parser.add_argument('-b',
                    '--batch-size',
                    default=256,
                    type=int,
                    metavar='N',
                    help='mini-batch size (default: 256) per gpu')
parser.add_argument('--lr',
                    '--learning-rate',
                    default=0.1,
                    type=float,
                    metavar='LR',
                    help='initial learning rate',
                    dest='lr')
parser.add_argument('--end-lr',
                    '--minimum learning-rate',
                    default=1e-8,
                    type=float,
                    metavar='END-LR',
                    help='initial learning rate')
parser.add_argument(
    '--lr-schedule',
    default='step',
    type=str,
    metavar='SCHEDULE',
    choices=['step', 'linear', 'cosine', 'exponential'],
    help='Type of LR schedule: {}, {}, {} , {}'.format('step', 'linear',
                                                       'cosine',
                                                       'exponential'),
)
parser.add_argument('--warmup',
                    default=0,
                    type=int,
                    metavar='E',
                    help='number of warmup epochs')
parser.add_argument('--optimizer',
                    default='sgd',
                    type=str,
                    choices=('sgd', 'rmsprop', 'adamw'))
parser.add_argument('--momentum',
                    default=0.9,
                    type=float,
                    metavar='M',
                    help='momentum')
parser.add_argument('--wd',
                    '--weight-decay',
                    default=1e-4,
                    type=float,
                    metavar='W',
                    help='weight decay (default: 1e-4)',
                    dest='weight_decay')
parser.add_argument(
    '--amp',
    action='store_true',
    default=False,
    help='use NVIDIA Apex AMP or Native AMP for mixed precision training')
parser.add_argument('--native-amp',
                    action='store_true',
                    default=False,
                    help='Use Native Torch AMP mixed precision')
parser.add_argument(
    '--early-stopping-patience',
    default=-1,
    type=int,
    metavar='N',
    help='early stopping after N epochs without improving',
)
parser.add_argument(
    '--gradient_accumulation_steps',
    default=1,
    type=int,
    metavar='N',
    help='=To run gradient descent after N steps',
)
parser.add_argument('--evaluate',
                    dest='evaluate',
                    action='store_true',
                    help='evaluate model on validation set')
parser.add_argument('--training-only',
                    action='store_true',
                    help='do not evaluate')
parser.add_argument('--local_rank', default=0, type=int)
parser.add_argument(
    '--static-loss-scale',
    type=float,
    default=1,
    help='Static loss scale',
)
parser.add_argument(
    '--dynamic-loss-scale',
    action='store_true',
    help='Use dynamic loss scaling.  If supplied, this argument supersedes ' +
    '--static-loss-scale.',
)
parser.add_argument(
    '--no-checkpoints',
    action='store_false',
    dest='save_checkpoints',
    help='do not store any checkpoints, useful for benchmarking',
)
parser.add_argument('--seed',
                    type=int,
                    default=42,
                    metavar='S',
                    help='random seed (default: 42)')
parser.add_argument('--log_interval',
                    default=10,
                    type=int,
                    metavar='N',
                    help='print frequency (default: 10)')
parser.add_argument('--output-dir',
                    default='./work_dirs',
                    type=str,
                    help='output directory for model and log')
parser.add_argument('--log_wandb',
                    action='store_true',
                    help='while to use wandb log systerm')
parser.add_argument('--experiment', default='protein-annotation', type=str)


def main(args):
    if args.log_wandb:
        if has_wandb:
            wandb.init(project=args.experiment,
                       config=args,
                       entity='hushuangwei')
        else:
            logger.warning(
                "You've requested to log metrics to wandb but package not found. "
                'Metrics not being logged to wandb, try `pip install wandb`')

    args.distributed = False
    if 'WORLD_SIZE' in os.environ:
        args.distributed = int(os.environ['WORLD_SIZE']) > 1
        args.local_rank = int(os.environ['LOCAL_RANK'])
    else:
        args.local_rank = 0

    args.gpu = 0
    args.world_size = 1
    args.rank = 0

    if args.distributed:
        args.gpu = args.local_rank % torch.cuda.device_count()
        torch.cuda.set_device(args.local_rank)
        dist.init_process_group(backend='nccl', init_method='env://')
        args.world_size = torch.distributed.get_world_size()
        args.rank = torch.distributed.get_rank()

        logger.info(
            'Training in distributed mode with multiple processes, 1 GPU per process. Process %d, total %d.'
            % (args.rank, args.world_size))
    else:
        logger.info('Training with a single process on %s .' % args.gpu)
    assert args.rank >= 0

    random_seed(args.seed, args.rank)

    # get data loaders
    # Dataset and DataLoader
    adj, multi_hot_vector, label_map, label_map_ivs = build_graph(
        data_path=args.data_path, namespace=args.namespace)
    nb_classes = len(label_map)
    train_dataset = GCNDataset(label_map,
                               root_path=args.data_path,
                               file_name=args.train_file_name)
    val_dataset = GCNDataset(label_map,
                             root_path=args.data_path,
                             file_name=args.val_file_name)

    if args.distributed:
        train_sampler = torch.utils.data.distributed.DistributedSampler(
            train_dataset)
        val_sampler = torch.utils.data.distributed.DistributedSampler(
            val_dataset)
    else:
        train_sampler = torch.utils.data.RandomSampler(train_dataset)
        val_sampler = torch.utils.data.RandomSampler(val_dataset)

    # dataloders
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=(train_sampler is None),
        num_workers=args.workers,
        sampler=train_sampler,
        pin_memory=True,
    )

    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch_size,
        shuffle=(val_sampler is None),
        num_workers=args.workers,
        sampler=val_sampler,
        pin_memory=True,
    )

    # model
    nodes = multi_hot_vector.cuda()
    adj = adj.cuda()
    model = MLP(1280,nb_classes)

    if args.resume is not None:
        if args.local_rank == 0:
            model_state, optimizer_state = load_model_checkpoint(args.resume)
            model.load_state_dict(model_state)

    scaler = torch.cuda.amp.GradScaler(
        init_scale=args.static_loss_scale,
        growth_factor=2,
        backoff_factor=0.5,
        growth_interval=100 if args.dynamic_loss_scale else 1000000000,
        enabled=args.amp,
    )
    # define loss function (criterion) and optimizer
    # optimizer and lr_policy
    optimizer = optim.AdamW(filter(lambda p: p.requires_grad,
                                   model.parameters()),
                            lr=args.lr,
                            weight_decay=args.weight_decay)
    lr_policy = optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.8)

    if args.distributed:
        # For multiprocessing distributed, DistributedDataParallel constructor
        # should always set the single device scope, otherwise,
        # DistributedDataParallel will use all available devices.
        if args.gpu is not None:
            torch.cuda.set_device(args.gpu)
            model.cuda(args.gpu)
            # When using a single GPU per process and per
            # DistributedDataParallel, we need to divide the batch size
            # ourselves based on the total number of GPUs we have
            model = torch.nn.parallel.DistributedDataParallel(
                model,
                device_ids=[args.gpu],
                output_device=args.gpu,
                find_unused_parameters=True)
        else:
            model.cuda()
            # DistributedDataParallel will divide and allocate batch_size to all
            # available GPUs if device_ids are not set
            model = torch.nn.parallel.DistributedDataParallel(
                model, output_device=0, find_unused_parameters=True)
    else:
        model.cuda()

    start_epoch = 0
    if args.start_epoch is not None:
        # a specified start_epoch will always override the resume epoch
        start_epoch = args.start_epoch
    if lr_policy is not None and start_epoch > 0:
        lr_policy.step(start_epoch)

    if args.local_rank == 0:
        logger.info('Scheduled epochs: {}'.format(args.epochs))

    gradient_accumulation_steps = args.gradient_accumulation_steps

    train_loop(model,
               optimizer,
               lr_policy,
               scaler,
               gradient_accumulation_steps,
               train_loader,
               val_loader,
               use_amp=args.amp,
               logger=logger,
               start_epoch=start_epoch,
               end_epoch=args.epochs,
               early_stopping_patience=args.early_stopping_patience,
               skip_training=args.evaluate,
               skip_validation=args.training_only,
               save_checkpoints=args.save_checkpoints and not args.evaluate,
               output_dir=args.output_dir,
               log_wandb=args.log_wandb,
               log_interval=args.log_interval)
    print('Experiment ended')


def _parse_args():
    # Do we have a config file to parse?
    args_config, remaining = config_parser.parse_known_args()
    if args_config.config:
        with open(args_config.config, 'r') as f:
            cfg = yaml.safe_load(f)
            parser.set_defaults(**cfg)

    # The main arg parser parses the rest of the args, the usual
    # defaults will have been overridden if config file specified.
    args = parser.parse_args(remaining)

    # Cache the args as a text string to save them in the output dir later
    args_text = yaml.safe_dump(args.__dict__, default_flow_style=False)
    return args, args_text


if __name__ == '__main__':
    args, args_text = _parse_args()
    # Cache the args as a text string to save them in the output dir later
    args_text = yaml.safe_dump(args.__dict__, default_flow_style=False)

    task_name = 'ProtLM' + '_' + 'withoutGCN_' + args.namespace + '_less_terms_' + args.model
    args.output_dir = os.path.join(args.output_dir, task_name)
    if not torch.distributed.is_initialized() or torch.distributed.get_rank(
    ) == 0:
        if not os.path.exists(args.output_dir):
            os.makedirs(args.output_dir)

    with open(os.path.join(args.output_dir, 'args.yaml'), 'w') as f:
        f.write(args_text)

    logger = logging.getLogger('')
    filehandler = logging.FileHandler(
        os.path.join(args.output_dir, 'summary.log'))
    streamhandler = logging.StreamHandler()
    logger.setLevel(logging.INFO)
    logger.addHandler(filehandler)
    logger.addHandler(streamhandler)
    cudnn.benchmark = True
    start_time = time.time()
    main(args)
