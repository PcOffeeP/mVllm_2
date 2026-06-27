---
library_name: peft
license: other
base_model: ../models/minicpm_v_4_5
tags:
- base_model:adapter:../models/minicpm_v_4_5
- llama-factory
- lora
- transformers
pipeline_tag: text-generation
model-index:
- name: sft_interval_3k0
  results: []
---

<!-- This model card has been generated automatically according to the information the Trainer had access to. You
should probably proofread and complete it, then remove this comment. -->

# sft_interval_3k0

This model is a fine-tuned version of [../models/minicpm_v_4_5](https://huggingface.co/../models/minicpm_v_4_5) on the tensile_video_interval_fold0_train dataset.
It achieves the following results on the evaluation set:
- Loss: 0.0833

## Model description

More information needed

## Intended uses & limitations

More information needed

## Training and evaluation data

More information needed

## Training procedure

### Training hyperparameters

The following hyperparameters were used during training:
- learning_rate: 1.5e-05
- train_batch_size: 1
- eval_batch_size: 1
- seed: 42
- gradient_accumulation_steps: 16
- total_train_batch_size: 16
- optimizer: Use OptimizerNames.PAGED_ADAMW_8BIT with betas=(0.9,0.95) and epsilon=1e-08 and optimizer_args=No additional optimizer arguments
- lr_scheduler_type: cosine
- lr_scheduler_warmup_ratio: 0.05
- num_epochs: 8

### Training results

| Training Loss | Epoch | Step | Validation Loss |
|:-------------:|:-----:|:----:|:---------------:|
| 0.1288        | 1.0   | 99   | 0.0868          |
| 0.0542        | 2.0   | 198  | 0.0833          |
| 0.0529        | 3.0   | 297  | 0.0884          |
| 0.0468        | 4.0   | 396  | 0.0957          |
| 0.0331        | 5.0   | 495  | 0.1074          |
| 0.0419        | 6.0   | 594  | 0.1062          |
| 0.0372        | 7.0   | 693  | 0.1097          |
| 0.033         | 8.0   | 792  | 0.1096          |


### Framework versions

- PEFT 0.18.1
- Transformers 4.56.1
- Pytorch 2.5.1+cu124
- Datasets 4.0.0
- Tokenizers 0.22.2