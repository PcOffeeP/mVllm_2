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
| Checkpoints proposed for deletion | 88 |
| Retained logical bytes | Recomputed by final machine plan |
| Proposed reclaimed logical bytes | Recomputed by final machine plan |

The machine-readable plan is stored on the training machine at:

`finetune/run_logs/checkpoint_management_20260729/checkpoint_plan.json`

The plan file and SHA256 are replaced atomically when the corrected policy is
executed on the training machine.

## Safety boundary

The cleanup tool defaults to planning only. Applying this exact plan requires:

1. the machine-readable plan to remain unchanged;
2. all target directory metadata fingerprints to remain unchanged;
3. no detected training process;
4. every target to be a non-symlink `workspace/**/checkpoint-<step>` directory;
5. an exact confirmation string containing the recomputed deletion count.

No deletion was performed while producing this report.
