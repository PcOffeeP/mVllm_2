---
library_name: peft
license: other
base_model: /home/liuyang/.cache/modelscope/hub/models/openbmb/MiniCPM-V-4_5
tags:
- base_model:adapter:/home/liuyang/.cache/modelscope/hub/models/openbmb/MiniCPM-V-4_5
- llama-factory
- lora
- transformers
pipeline_tag: text-generation
model-index:
- name: sft_512
  results: []
---

<!-- This model card has been generated automatically according to the information the Trainer had access to. You
should probably proofread and complete it, then remove this comment. -->

# sft_512

This model is a fine-tuned version of [/home/liuyang/.cache/modelscope/hub/models/openbmb/MiniCPM-V-4_5](https://huggingface.co//home/liuyang/.cache/modelscope/hub/models/openbmb/MiniCPM-V-4_5) on the tensile_video dataset.

## Model description

More information needed

## Intended uses & limitations

More information needed

## Training and evaluation data

More information needed

## Training procedure

### Training hyperparameters

The following hyperparameters were used during training:
- learning_rate: 1e-05
- train_batch_size: 1
- eval_batch_size: 8
- seed: 42
- gradient_accumulation_steps: 12
- total_train_batch_size: 12
- optimizer: Use OptimizerNames.PAGED_ADAMW_8BIT with betas=(0.9,0.999) and epsilon=1e-08 and optimizer_args=No additional optimizer arguments
- lr_scheduler_type: cosine
- lr_scheduler_warmup_ratio: 0.1
- num_epochs: 3

### Training results



### Framework versions

- PEFT 0.17.1
- Transformers 4.57.1
- Pytorch 2.10.0+cu128
- Datasets 4.0.0
- Tokenizers 0.22.2