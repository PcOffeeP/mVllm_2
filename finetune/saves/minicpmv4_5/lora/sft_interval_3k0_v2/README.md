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
- Loss: 0.0823

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
| 1.3623        | 0.2304 | 50   | 1.3633          |
| 1.0914        | 0.4608 | 100  | 1.0094          |
| 0.4772        | 0.6912 | 150  | 0.5036          |
| 0.195         | 0.9217 | 200  | 0.1989          |
| 0.1569        | 1.1521 | 250  | 0.1171          |
| 0.1285        | 1.3825 | 300  | 0.0989          |
| 0.0913        | 1.6129 | 350  | 0.0908          |
| 0.1033        | 1.8433 | 400  | 0.0863          |
| 0.1169        | 2.0737 | 450  | 0.0847          |
| 0.0745        | 2.3041 | 500  | 0.0831          |
| 0.1217        | 2.5346 | 550  | 0.0826          |
| 0.1451        | 2.7650 | 600  | 0.0825          |
| 0.1181        | 2.9954 | 650  | 0.0823          |


### Framework versions

- PEFT 0.18.1
- Transformers 4.56.1
- Pytorch 2.5.1+cu124
- Datasets 4.0.0
- Tokenizers 0.22.2