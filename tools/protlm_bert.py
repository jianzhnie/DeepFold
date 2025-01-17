import sys

import torch
from torch.optim import AdamW
from transformers import (BertConfig, EarlyStoppingCallback, EvalPrediction,
                          Trainer, TrainingArguments)

from deepfold.core.metrics.multilabel_metrics import multi_label_metrics
from deepfold.data.protein_dataset import ProtBertDataset
from deepfold.models.transformers.multilabel_transformer import \
    BertForMultiLabelSequenceClassification

sys.path.append('../')


def compute_metrics(p: EvalPrediction, threshold=0.2):
    preds = p.predictions[0] if isinstance(p.predictions,
                                           tuple) else p.predictions
    labels = p.label_ids

    results = multi_label_metrics(predictions=preds,
                                  labels=labels,
                                  threshold=threshold)
    return results


class MultilabelTrainer(Trainer):
    def compute_loss(self, model, inputs, return_outputs=False):
        """How the loss is computed by Trainer. By default, all models return
        the loss in the first element.

        Subclass and override for custom behavior.
        """
        labels = inputs.pop('labels')
        outputs = model(**inputs)
        logits = outputs.logits
        loss_fct = torch.nn.BCEWithLogitsLoss()
        loss = loss_fct(logits.view(-1, self.model.config.num_labels),
                        labels.float().view(-1, self.model.config.num_labels))
        return (loss, outputs) if return_outputs else loss


if __name__ == '__main__':
    model_name = 'Rostlab/prot_bert_bfd'
    data_root = '/data/xbiome/protein_classification'
    train_dataset = ProtBertDataset(
        data_path=data_root,
        split='train',
        tokenizer_name=model_name,
        max_length=128)  # max_length is only capped to speed-up example.
    val_dataset = ProtBertDataset(data_path=data_root,
                                  split='valid',
                                  tokenizer_name=model_name,
                                  max_length=128)
    test_dataset = ProtBertDataset(data_path=data_root,
                                   split='test',
                                   tokenizer_name=model_name,
                                   max_length=128)
    train_dataset = val_dataset
    num_classes = train_dataset.num_classes
    model_config = BertConfig.from_pretrained(model_name,
                                              num_labels=num_classes)

    model = BertForMultiLabelSequenceClassification.from_pretrained(
        model_name, config=model_config)

    # setting custom optimization parameters. You may implement a scheduler here as well.
    param_optimizer = list(model.named_parameters())
    no_decay = ['bias', 'gamma', 'beta']
    optimizer_grouped_parameters = [{
        'params':
        [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)],
        'weight_decay_rate':
        0.01
    }, {
        'params':
        [p for n, p in param_optimizer if any(nd in n for nd in no_decay)],
        'weight_decay_rate':
        0.0
    }]
    optimizer = AdamW(optimizer_grouped_parameters, lr=2e-5)

    training_args = TrainingArguments(
        report_to='none',
        output_dir='./work_dir',  # output directory
        num_train_epochs=30,  # total number of training epochs
        per_device_train_batch_size=8,  # batch size per device during training
        per_device_eval_batch_size=8,  # batch size for evaluation
        learning_rate=2e-5,  # learning_rate
        warmup_steps=1000,  # number of warmup steps for learning rate scheduler
        weight_decay=0.01,  # strength of weight decay
        gradient_accumulation_steps=8,
        # total number of steps before back propagation
        fp16=True,  # Use mixed precision
        fp16_opt_level='02',  # mixed precision mode
        do_train=True,  # Perform training
        do_eval=True,  # Perform evaluation
        save_strategy='epoch',  # save model every epoch
        evaluation_strategy='epoch',  # evalute after each epoch
        # report_to='wandb',  # enable logging to W&B
        load_best_model_at_end=True,
        metric_for_best_model='f1',  # use f1 score for model eval metric
        run_name='ProBert-BFD-MS',  # experiment name
        logging_dir='./logs',  # directory for storing logs
        logging_steps=100,  # How often to print logs
        seed=3  # Seed for experiment reproducibility 3x3
    )

    trainer = Trainer(
        model=model,  # the instantiated 🤗 Transformers model to be trained
        args=training_args,  # training arguments, defined above
        train_dataset=train_dataset,  # training dataset
        eval_dataset=val_dataset,  # evaluation dataset
        compute_metrics=compute_metrics,  # evaluation metrics
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )

    trainer.train()
    trainer.save_model('models/')
    # Load trained model
    model_path = 'work_dir/checkpoint-5000'
    model = BertForMultiLabelSequenceClassification.from_pretrained(
        model_path, num_labels=num_classes)
    # Define test trainer
    test_trainer = Trainer(model)
    predictions, label_ids, metrics = trainer.predict(val_dataset)
