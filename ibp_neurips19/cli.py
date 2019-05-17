"""Command line interface (CLI)."""

from itertools import product

import click
import torch

from . import models
from .__version__ import __version__
from .attacks import compute_robustness
from .train import train_classifier

__all__ = ['main', 'basic', 'experiment', 'pgd']


@click.group()
@click.version_option(__version__, '-v', '--version')
def main():
    """Interval Bound Propagation (NeurIPS 2019)."""
    return


@main.command()
@click.option(
    '-v/-t',
    '--validate/--train',
    'evaluate_only',
    is_flag=True,
    default=True,
    show_default=True,
    help='Whether to run in validation or training mode.')
@click.option(
    '--dataset',
    '-d',
    type=click.STRING,
    default='MNIST',
    help='Which dataset to use.')
@click.option(
    '--model',
    '-m',
    type=click.STRING,
    default='small_cnn',
    help='Which model architecture to use.')
@click.option(
    '-p/-s',
    '--pretrained/--scratch',
    'pretrained',
    is_flag=True,
    default=False,
    show_default=True,
    help='Whether to load a pretrained model.')
@click.option(
    '--learning-rate',
    '-lr',
    type=click.FloatRange(min=0),
    default=1e-1,
    help='Learning rate.')
@click.option(
    '--momentum',
    '-mm',
    type=click.FloatRange(min=0),
    default=0.9,
    help='SGD momentum.')
@click.option(
    '--weight-decay',
    '-w',
    type=click.FloatRange(min=0),
    default=1e-4,
    help='SGD weight decay.')
@click.option(
    '--number-of-epochs',
    '-n',
    'epochs',
    type=click.IntRange(min=0),
    default=90,
    help='The maximum number of epochs.')
@click.option(
    '--batch-size',
    '-b',
    type=click.IntRange(min=0),
    default=256,
    help='Mini-batch size.')
@click.option(
    '--jobs',
    '-j',
    type=click.IntRange(min=0),
    default=4,
    help='Number of threads for data loading when using cuda.')
@click.option(
    '--checkpoint',
    '-c',
    type=click.Path(path_type=str),
    default='checkpoint.pth',
    help='A checkpoint file to save the best model.')
@click.option(
    '--resume',
    '-r',
    type=click.Path(path_type=str),
    default='',
    help='A checkpoint file to resume from.')
@click.option(
    '--log-dir',
    '-l',
    type=click.Path(path_type=str),
    default='logs',
    help='A tensorboard logs directory.')
@click.option(
    '--seed',
    '-sd',
    type=click.IntRange(),
    default=None,
    help='Seed the random number generators (slow!).')
@click.option(
    '--epsilon',
    '-e',
    type=click.FloatRange(),
    default=0,
    help='Epsilon used for training with interval bounds.')
def basic(*args, **kwargs):
    """Start basic neural network training."""
    train_classifier(*args, **kwargs)


@main.command()
@click.option(
    '-r/-s',
    '--run/--show',
    'run',
    is_flag=True,
    default=False,
    show_default=True,
    help='Whether to run or show the experiment(s).')
@click.option(
    '--index',
    '-i',
    type=click.IntRange(0),
    default=None,
    help='Which experiment.')
@click.pass_context
def experiment(ctx, run, index):
    """Run one of the experiments."""
    datasets = ['MNIST', 'CIFAR10', 'SVHN', 'CIFAR100']
    epsilons = [0.001, 0.01, 0.03, 0.1, 0.2, 0.3, 0.4]
    learning_rates = [1e-1, 1e-2, 1e-3]
    models = ['small_cnn', 'medium_cnn', 'large_cnn']
    for i, (dataset, epsilon, learning_rate, model) in enumerate(
            product(datasets, epsilons, learning_rates, models)):
        if index is not None and i != index:
            continue
        directory = f'{dataset}-{model}-{epsilon}/{learning_rate}'
        command = (f'ibp basic --train -d {dataset} -m {model} -e {epsilon}'
                   f' -lr {learning_rate} -l {directory}'
                   f' -c {directory}/checkpoint.pth')
        print(i, command)
        if run:
            ctx.invoke(
                basic,
                evaluate_only=False,
                dataset=dataset,
                model=model,
                epsilon=epsilon,
                learning_rate=learning_rate,
                log_dir=directory,
                checkpoint=f'{directory}/checkpoint.pth')


@main.command()
@click.option(
    '-r/-s',
    '--run/--show',
    'run',
    is_flag=True,
    default=False,
    show_default=True,
    help='Whether to run or show the experiment(s).')
@click.option(
    '--index',
    '-i',
    type=click.IntRange(0),
    default=None,
    help='Which experiment.')
def pgd(run, index, subset=None, restarts=1, seed=None):
    """Compute PGD for the experiments."""

    def experiments():
        datasets = ['MNIST', 'CIFAR10']
        epsilons = [0.01, 0.03, 0.1, 0.2]
        model_size = ['small', 'medium']
        learning_rates = [0, 1e-1, 1e-2, 1e-3]
        test_epsilons = [2 / 255, 0.1, 0.2, 0.3]
        for dataset, epsilon, model, learning_rate, test_epsilon in product(
                datasets, epsilons, model_size, learning_rates, test_epsilons):
            if dataset == 'CIFAR10':
                if test_epsilon != 2 / 255 or epsilon != 0.01:
                    continue
            elif test_epsilon == 2 / 255 or epsilon == 0.01:
                continue
            yield dataset, epsilon, model, learning_rate, test_epsilon

    for i, (dataset, epsilon, model, learning_rate,
            test_epsilon) in enumerate(experiments()):
        if index is not None and i != index:
            continue
        if learning_rate == 0:
            checkpoint_file = (f'dm_torch/'
                               f'{dataset.lower()}-{model}-{epsilon}.pth')
        else:
            checkpoint_file = (f'{dataset}-{model}_cnn-{epsilon}'
                               f'/{learning_rate}/checkpoint.pth')
        print(i, f'{dataset}-{model}-{epsilon}', learning_rate, test_epsilon)
        if run:
            net = models.__dict__[f'{model}_cnn']()
            models.fit_to_dataset(net, dataset).eval()
            checkpoint = torch.load(checkpoint_file)
            net.load_state_dict(checkpoint['state_dict'])
            results = compute_robustness(
                net,
                dataset,
                device='cuda' if torch.cuda.is_available() else 'cpu',
                attack_name='PGD',
                restarts=restarts,
                subset=subset,
                subset_seed=seed,
                attack_kwargs=dict(epsilon=test_epsilon))
            if 'PGD' not in checkpoint:
                checkpoint['PGD'] = []
            checkpoint['PGD'].append({
                'seed': seed,
                'subset': subset,
                'restarts': restarts,
                'epsilon': test_epsilon,
                'robustness': results.robustness,
                'fooling_rate': results.fooling_rate,
                'sorted_errors': results.sorted_errors,
            })
            torch.save(checkpoint, checkpoint_file)


if __name__ == '__main__':
    main()  # pylint: disable=no-value-for-parameter
