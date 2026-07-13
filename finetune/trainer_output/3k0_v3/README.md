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
- name: sft_interval_3k0_v3
  results: []
---

<!-- This model card has been generated automatically according to the information the Trainer had access to. You
should probably proofread and complete it, then remove this comment. -->

# sft_interval_3k0_v3

This model is a fine-tuned version of [../models/minicpm_v_4_5](https://huggingface.co/../models/minicpm_v_4_5) on the tensile_video_interval_fold0_train dataset.
It achieves the following results on the evaluation set:
- Loss: 0.3236

## Model description

More information needed

## Intended uses & limitations

More information needed

## Training and evaluation data

More information needed

## Training procedure

### Training hyperparameters

The following hyperparameters were used during training:
- learning_rate: 5e-06
- train_batch_size: 1
- eval_batch_size: 1
- seed: 3407
- gradient_accumulation_steps: 8
- total_train_batch_size: 8
- optimizer: Use OptimizerNames.PAGED_ADAMW_8BIT with betas=(0.9,0.95) and epsilon=1e-08 and optimizer_args=No additional optimizer arguments
- lr_scheduler_type: cosine
- lr_scheduler_warmup_ratio: 0.1
- num_epochs: 3

### Training results

| Training Loss | Epoch  | Step | Validation Loss |
|:-------------:|:------:|:----:|:---------------:|
| 2.0827        | 0.4197 | 50   | 2.0431          |
| 1.4314        | 0.8395 | 100  | 1.3905          |
| 0.8605        | 1.2518 | 150  | 0.8316          |
| 0.5172        | 1.6716 | 200  | 0.5076          |
| 0.3559        | 2.0839 | 250  | 0.3806          |
| 0.3262        | 2.5037 | 300  | 0.3333          |
| 0.2707        | 2.9234 | 350  | 0.3236          |


### Framework versions

- PEFT 0.18.1
- Transformers 4.56.1
- Pytorch 2.5.1+cu124
- Datasets 4.0.0
- Tokenizers 0.22.2