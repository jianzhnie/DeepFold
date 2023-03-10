# ProteinTransformer

[![OSCS Status](https://www.oscs1024.com/platform/badge/jianzhnie/X-DeepGO.svg?size=small)](https://www.oscs1024.com/project/jianzhnie/X-DeepGO?ref=badge_small)

ProteinTransformer is toolkit using deep learning for protein function annotation

[Toc]

## Installation

The sources for Deepfold can be downloaded from the `Github repo`.

You can either clone the public repository:

```bash
# clone project
git clone https://github.com/jianzhnie/X-DeepGO.git  
# First, install dependencies
pip install -r requirements.txt
```

Once you have a copy of the source, you can install it with:

```bash
python setup.py install
```

## How to use

### Single GPU Training

```sh
python main.py  \
--data_path ./protein \
--output-dir ./work_dir \
--lr 0.0001 \
--epochs 10 \
--batch-size 2 \
--log_wandb \
--workers 4
```

### Distributed Training

```sh
torchrun --nnodes=1 --nproc_per_node=2  --rdzv_id=0 main.py  \
--data_path ./protein \
--output-dir ./work_dir \
--lr 0.0001 \
--epochs 10 \
--batch-size 2 \
--log_wandb \
--workers 4
```

### Evaluate

```sh
## evaluate diamond
python  evaluate_diamondscore.py \
    --train-data-file ./protein/train_data.pkl \
    --test-data-file ./protein/test_data.pkl \
    --diamond-scores-file ./protein/test_diamond.res \
    --ontology-obo-file ./protein/go.obo \
    --output_dir ./work_dir


## evaluate model
python  evaluate_deepmodel.py \
    --train-data-file ./protein/train_data.pkl \
    --test-data-file ./protein/predictions.pkl \
    --terms-file ./protein/terms.pkl \
    --ontology-obo-file ./protein/go.obo \
    --output_dir ./work_dir
```

### Inference

```sh
## inference
python inference_embedding.py  \
--data_path ./protein \
--output-dir ./work_dir \
--resume ./work_dir/ProtLM_esm_embedding_mean/model_best.pth.tar \
--model esm_embedding \
--pool_mode  mean \
--batch-size  128 \
--workers 4
```

### Extract Embeddings

```sh
python extract_embeddings.py  \
--data_path ./protein \
--split "test" \
--batch-size 32
```

## License

This library is licensed under the Apache 2.0 License.

## Contributing to X-DeepGO

We are actively accepting code contributions to the X-DeepGO project. If you are interested in contributing to X-DeepGO, please contact me.
