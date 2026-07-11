# Incremental Review Queue Design

## Goal and scope

Preserve the completed manual-review baseline and support a small, separate
review round for only `needs_regenerate` records and explicitly selected
frame-interval conflicts. The new flow must not require re-reviewing approved
samples or regenerate split assignments.

## Constraints

- The historical decision file is immutable input to an incremental round.
- Queue media is produced on the training computer. This repository copy has
  original videos and metadata but no usable subvideo/frame media.
- Existing `fold_*`/`test` assignments are frozen inputs; no split generation
  is part of this flow.
- A delta may not silently replace an approved historical decision.

## Recommended architecture

1. `prepare_incremental_review_queue.py` reads baseline metadata, decisions,
   source metadata, and frozen splits. It writes queue-only metadata and CSV
   with stable IDs, selection reasons, baseline decision snapshots, frame
   mappings, and input SHA-256 hashes. It does not write decisions or media.
2. `review_subvideos_app.py --incremental-delta` opens only queue metadata.
   It writes only a delta decision file and never loads or writes the complete
   baseline decision file. The UI displays the queue reason and baseline
   decision as read-only context.
3. `merge_incremental_review_decisions.py` validates queue membership and
   input hashes before producing a new final decision file. By default it may
   replace only `needs_regenerate` baseline decisions. Replacing an approved
   baseline decision requires `--allow-approved-supersede` and a non-empty
   reviewer note.

## Non-goals

- No full subvideo regeneration, media copying, or split recomputation.
- No pixel-based automatic fracture detection.
- No automatic modification of source CSV labels.

## Failure handling

- Queue creation fails for duplicate/missing IDs or a missing baseline decision.
- Delta UI rejects a non-queue output path only by explicit incremental mode;
  it writes queue IDs only.
- Merge fails for duplicate delta IDs, non-queue IDs, stale input hashes,
  unresolved delta status, or an unauthorized approved-decision replacement.

## Validation

- Unit tests cover selection, immutable baseline preservation, resume from a
  delta file, and all merge rejection paths.
- The merge output is passed to the existing audit and strict training gate.
