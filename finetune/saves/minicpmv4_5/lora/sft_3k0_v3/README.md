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
- name: sft_interval_3k0_v2
  results: []
---

<!-- This model card has been generated automatically according to the information the Trainer had access to. You
should probably proofread and complete it, then remove this comment. -->

# sft_interval_3k0_v2

This model is a fine-tuned version of [../models/minicpm_v_4_5](https://huggingface.co/../models/minicpm_v_4_5) on the tensile_video_interval_fold0_train dataset.
It achieves the following results on the evaluation set:
- Loss: 0.0867

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
| 1.2558        | 0.3249 | 50   | 1.2034          |
| 1.0226        | 0.6499 | 100  | 0.8107          |
| 0.3401        | 0.9748 | 150  | 0.4055          |
| 0.3099        | 1.2989 | 200  | 0.1925          |
| 0.1537        | 1.6239 | 250  | 0.1125          |
| 0.1168        | 1.9488 | 300  | 0.0969          |
| 0.1239        | 2.2729 | 350  | 0.0901          |
| 0.0727        | 2.5979 | 400  | 0.0870          |
| 0.0944        | 2.9228 | 450  | 0.0867          |


### Framework versions

- PEFT 0.18.1
- Transformers 4.56.1
- Pytorch 2.5.1+cu124
- Datasets 4.0.0
- Tokenizers 0.22.2