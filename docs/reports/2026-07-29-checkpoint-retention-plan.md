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

## Retention decision

Keep two checkpoints for the training experiment that produced the current
release `v4.1-agent-pipeline-fold0-r1`:

- `workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/checkpoint-250`
  — best checkpoint and source of the saved root adapter.
- `workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/checkpoint-1125`
  — last checkpoint, retained for recovery and trajectory comparison.

Delete all checkpoints from the other 21 completed comparison/archive
experiments. Their root adapters, merged models, metrics, logs, and identities
remain available.

## Dry-run result

| Item | Result |
| --- | ---: |
| Experiments | 22 |
| Checkpoints before cleanup | 108 |
| Checkpoints retained | 2 |
| Checkpoints proposed for deletion | 106 |
| Retained logical bytes | 2,795,556,058 |
| Proposed reclaimed logical bytes | 100,683,254,785 |

The machine-readable plan is stored on the training machine at:

`finetune/run_logs/checkpoint_management_20260729/checkpoint_plan.json`

Plan SHA256:

`3d5cfbdb32786f8160ffe9c46714a5d965911bae96aa50e510911a700725b7a0`

## Safety boundary

The cleanup tool defaults to planning only. Applying this exact plan requires:

1. the machine-readable plan to remain unchanged;
2. all target directory metadata fingerprints to remain unchanged;
3. no detected training process;
4. every target to be a non-symlink `workspace/**/checkpoint-<step>` directory;
5. the exact confirmation string `DELETE-106-CHECKPOINTS`.

No deletion was performed while producing this report.
