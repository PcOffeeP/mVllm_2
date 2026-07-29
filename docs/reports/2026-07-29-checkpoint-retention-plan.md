# Checkpoint retention plan — 2026-07-29

## Scope

Training machine repository:

`/home/liuyang/文档/mVllm_2`

This plan covers all checkpoint directories below the managed `workspace/`
tree after the model-asset migration. It does not cover base models, root
adapters, merged models, evaluation results, logs, trainer state, model
identities, or release manifests.

## Evidence

- 22 completed experiments contain 108 checkpoints.
- Every experiment has a root adapter and a corresponding merged model.
- For 21 experiments, the root adapter SHA256 equals the checkpoint identified
  by `trainer_state.json` as best.
- The historical V2 full-data adapter does not record a best checkpoint; its
  root adapter SHA256 equals its last checkpoint.
- The current release merged and adapter artifacts independently pass their
  frozen aggregate-hash checks.
- No active training process was present during planning.

## Superseded initial decision

The initial dry-run proposed retaining only best and last for the current
release source. That proposal was rejected before deletion because checkpoints
are also required for rapid retraining and analysis of intermediate learning
ability.

No checkpoint was deleted under the superseded plan.

## Final retention decision

Retain every checkpoint and every other result file for:

1. the training experiment that produced the current release
   `v4.1-agent-pipeline-fold0-r1`;
2. all three folds of the latest
   `v4.1-prompt-concise-cv-v1-seed3411` run.

Only checkpoint directories are deleted from the other completed experiments.
Their root adapters, merged models, metrics, logs, trainer states, and model
identities remain available.

## Dry-run result

| Item | Result |
| --- | ---: |
| Experiments | 22 |
| Checkpoints before cleanup | 108 |
| Checkpoints retained | 20 |
| Checkpoints deleted | 88 |
| Retained logical bytes | 27,955,371,079 |
| Reclaimed logical bytes | 75,523,439,764 |

The machine-readable plan is stored on the training machine at:

`finetune/run_logs/checkpoint_management_20260729/checkpoint_plan.json`

Final plan SHA256:

`6b92c70fd84e994e0c0a58ce5bd5320d5e557a2902373319941492c0f4eaf3df`

## Safety boundary

The cleanup tool defaults to planning only. Applying this exact plan requires:

1. the machine-readable plan to remain unchanged;
2. all target directory metadata fingerprints to remain unchanged;
3. no detected training process;
4. every target to be a non-symlink `workspace/**/checkpoint-<step>` directory;
5. the exact confirmation string `DELETE-88-CHECKPOINTS`.

## Execution result

The corrected plan was executed after explicit authorization to delete
checkpoints belonging to the other completed training tasks.

- Deleted checkpoint directories: 88.
- Remaining checkpoint directories: 20.
- Each of the four protected adapters retains all five checkpoints.
- Remaining merged models: 22.
- Remaining adapter roots: 23, including the release adapter copy.
- Current release full artifact hash verification: passed.
- Inference service `127.0.0.1:8002`: still running after cleanup.
- Training-machine free space increased from approximately 85 GiB to 155 GiB.

The machine-readable execution report is stored at:

`finetune/run_logs/checkpoint_management_20260729/cleanup_report.json`

Execution report SHA256:

`1da14b1864b8dda815d3ed7b49d2a41f87c6a23d815f2053d8eb12edc9e56879`
