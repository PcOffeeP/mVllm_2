"""Performance event accounting and immutable development-only evidence wiring.

There is deliberately no implicit model runner or test-data input.  Importing
client timestamps alone cannot establish trusted display E2E evidence.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from versioning.performance import (SCHEMA, PROTOCOL, canonical, digest, file_digest, number,
    performance_binding, probe_media, validate_performance_plan, validate_media_metadata)

EVENTS = {"uploaded", "queued", "read", "preprocess", "inference", "auto_parse", "backend_complete",
          "display_complete", "retry", "error", "timeout", "oom", "crash", "agent_review", "human_review"}
FAILURES = {"error", "timeout", "oom", "crash", "agent_review", "human_review"}
IMPLEMENTATIONS = ("versioning/performance.py", "finetune/eval_performance.py", "pipeline/server_proxy.py",
    "pipeline/server_adapter.py", "finetune/validation/video_loader.py", "pipeline/preprocessing/minicpm_preprocessor.py", "finetune/eval_semantics.py", "versioning/performance_receipts.py")


class PerformanceRecorder:
    """Append-only request IDs retain original upload clocks across retries."""
    def __init__(self, plan, *, synthetic=True):
        validate_performance_plan(plan)
        if type(synthetic) is not bool:
            raise ValueError("synthetic must be an explicit boolean")
        self.plan = copy.deepcopy(plan)
        self.synthetic = synthetic
        self.events = []
        self.resources = []
        self.requests = {}
        self.stop_reason = None
        self.lifecycle = {"cold_start_started_at": None, "ready_at": None}
        self.display_receipts = {}
        self.server_attestation = None
        self.runtime_collector = None
        self.formal_started = False

    def set_lifecycle(self, *, cold_start_started_at, ready_at):
        number(cold_start_started_at, "cold start timestamp")
        number(ready_at, "ready timestamp")
        if ready_at < cold_start_started_at or cold_start_started_at < self.plan["config"]["issued_at"]:
            raise ValueError("invalid cold start/ready clock")
        if self.lifecycle["ready_at"] is not None:
            raise ValueError("cold start/ready lifecycle cannot be reset")
        self.lifecycle = {"cold_start_started_at": cold_start_started_at, "ready_at": ready_at}

    def event(self, request_id, kind, at, *, media_id=None, warmup=False, parser=None, raw_output=None, upload_nonce=None):
        if not isinstance(request_id, str) or not request_id or kind not in EVENTS or type(warmup) is not bool:
            raise ValueError("valid request/event identity required")
        number(at, "event timestamp")
        if at < self.plan["config"]["issued_at"]:
            raise ValueError("event precedes performance authorization")
        if kind == "uploaded":
            if self.stop_reason or at >= self.plan["config"]["expires_at"]:
                raise ValueError("performance budget/TTL exhausted; no new requests")
            frozen_warmup = self.plan["config"]["policies"]["warmup"]["request_ids"]
            if warmup != (request_id in frozen_warmup):
                raise ValueError("request warmup class differs from frozen request_ids")
            if warmup and self.formal_started:
                raise ValueError("new warmup cannot start after formal measurement begins")
            if not warmup:
                if any(key not in self.requests or not self.requests[key]["finished"] for key in frozen_warmup):
                    raise ValueError("all frozen warmup requests must terminate before formal measurement")
                self.formal_started = True
            if request_id in self.requests:
                raise ValueError("retry must not reset a request's original upload clock or denominator")
            if media_id not in {m["media_id"] for m in self.plan["media_allowlist"]}:
                raise ValueError("performance media outside frozen development allowlist")
            # This protocol measures one user, one request. Interleaving may not
            # silently masquerade as continuous single-request measurements.
            if any(not r["finished"] for r in self.requests.values()):
                raise ValueError("concurrent performance requests are outside the frozen protocol")
            if self.plan["config"].get("client_attestation_policy") is not None:
                from versioning.performance_receipts import _hex
                _hex(upload_nonce, 32, "original client upload nonce")
            self.requests[request_id] = {"upload_nonce": upload_nonce, "raw_output": None, "upload": at, "last": at, "media_id": media_id,
                "warmup": warmup, "failed": False, "finished": False, "backend": None, "display": None, "parser": None}
        elif request_id not in self.requests:
            raise ValueError("event has no original upload-complete request")
        r = self.requests[request_id]
        if at < r["last"]:
            raise ValueError("request events must be chronological across retries")
        if kind != "uploaded" and (upload_nonce is not None and upload_nonce != r["upload_nonce"]
                or media_id is not None and media_id != r["media_id"] or warmup != r["warmup"]):
            raise ValueError("request media/warmup identity drift")
        if kind in {"backend_complete", "display_complete"}:
            if r["parser"] not in {"strict", "rule"}:
                raise ValueError("automatic completion requires strict or frozen-rule parsing")
            if kind == "backend_complete":
                if r["backend"] is not None:
                    raise ValueError("duplicate completion cannot overwrite original latency")
                r["backend"] = at
                r["finished"] = True
            else:
                if r["backend"] is None or r["display"] is not None:
                    raise ValueError("display requires a unique prior backend completion")
                r["display"] = at
                r["finished"] = True
        if kind == "auto_parse":
            if parser not in {"strict", "rule", "unreadable", "agent", "human"}:
                raise ValueError("unknown parser provenance")
            if parser in {"strict", "rule"}:
                from finetune.eval_semantics import extract_semantics
                from finetune.v4_1_runtime import parse_v4_1_output
                parsed = extract_semantics(raw_output, rules=self.plan["semantic_rules"])
                if parsed["branch"] != parser or parsed["missing_fields"]:
                    raise ValueError("automatic completion requires complete frozen strict/rule fields")
                # Rule-extracted partial/contradictory answers cannot count as
                # complete output merely because a caller labels them parsed.
                parse_v4_1_output(json.dumps(parsed["fields"]))
            r["parser"] = parser
            r["raw_output"] = raw_output
            if parser not in {"strict", "rule"}:
                r["failed"] = True
        if kind in FAILURES:
            r["failed"] = True  # immutable failure fact even if later recovered
            r["finished"] = True
        if (r["backend"] is not None and r["backend"] - r["upload"] > 600
                or at - r["upload"] > 660 or at >= self.plan["config"]["expires_at"]):
            r["failed"] = True
        r["last"] = at
        self.events.append({"request_id": request_id, "kind": kind, "at": at,
            "media_id": r["media_id"], "warmup": r["warmup"], "parser": parser, "raw_output": raw_output, "upload_nonce": r["upload_nonce"]})

    def resource(self, at, *, vram_bytes, rss_bytes, gpu_seconds):
        for name, value in (("at", at), ("vram_bytes", vram_bytes), ("rss_bytes", rss_bytes), ("gpu_seconds", gpu_seconds)):
            number(value, name)
        if self.resources and (at <= self.resources[-1]["at"] or gpu_seconds < self.resources[-1]["gpu_seconds"]):
            raise ValueError("resource time/GPU accounting cannot reset across retries")
        if at < self.plan["config"]["issued_at"]:
            raise ValueError("resource sample precedes authorization")
        self.resources.append({"at": at, "vram_bytes": vram_bytes, "rss_bytes": rss_bytes, "gpu_seconds": gpu_seconds})
        if gpu_seconds >= self.plan["config"]["budget_gpu_hours"] * 3600:
            self.stop_reason = "gpu_budget_exhausted"

    def evidence(self, *, observed_until):
        number(observed_until, "observation end")
        if any(e["at"] > observed_until for e in self.events) or any(r["at"] > observed_until for r in self.resources):
            raise ValueError("observation end precedes evidence")
        return {"schema_version": "tensile.performance-events/v1", "plan_sha256": digest(self.plan),
            "synthetic": self.synthetic, "events": copy.deepcopy(self.events), "resources": copy.deepcopy(self.resources),
            "observed_until": observed_until, "stop_reason": self.stop_reason, "lifecycle": self.lifecycle, "display_receipts": copy.deepcopy(self.display_receipts), "server_attestation": copy.deepcopy(self.server_attestation), "runtime_collector": copy.deepcopy(self.runtime_collector)}

    def report(self, *, observed_until):
        evidence = self.evidence(observed_until=observed_until)
        rows = [r for r in self.requests.values() if not r["warmup"]]
        count = len(rows)
        failed = [r for r in rows if r["failed"] or (r["backend"] is None and observed_until - r["upload"] > 600)
                  or (r["display"] is None and observed_until - r["upload"] > 660)]
        success = [r for r in rows if r not in failed and r["display"] is not None]
        on_time = [r for r in success if r["display"] - r["upload"] <= 300]
        latencies = sorted(r["display"] - r["upload"] for r in success)
        last_processing = max((r["backend"] if r["backend"] is not None else r["last"] for r in rows), default=observed_until)
        elapsed = max(0, last_processing - min((r["upload"] for r in rows), default=last_processing))
        ordered_rows = sorted(rows, key=lambda r: r["upload"])
        gaps = [max(0, b["upload"] - (a["backend"] if a["backend"] is not None else a["last"]))
                for a, b in zip(ordered_rows, ordered_rows[1:])]
        policy = self.plan["config"]["resource_growth_policy"]
        growth = False
        covered = False
        for i, start in enumerate(self.resources):
            window = [r for r in self.resources[i:] if r["at"] <= start["at"] + policy["window_seconds"]]
            if len(window) >= policy["min_samples"] and window[-1]["at"] - start["at"] >= policy["window_seconds"]:
                covered = True
                values = [r[policy["metric"]] for r in window]
                if values[-1] - values[0] > policy["max_growth_bytes"]:
                    growth = True
        resource_span = bool(self.resources and rows and self.resources[0]["at"] <= min(r["upload"] for r in rows)
            and self.resources[-1]["at"] >= observed_until)
        collector = self.runtime_collector
        collector_qualified = bool(isinstance(collector, dict) and collector == {
            "schema_version": "tensile.performance-runtime-collector/v1", "qualified": True,
            "runtime_binding_sha256": digest(performance_binding(self.plan)), "observes_achat_exceptions": True,
            "clean_session_end": True})
        gates = {"runtime_collector_qualified": collector_qualified, "formal_phase": self.plan["config"]["phase"] == "formal", "minimum_requests": count >= 100,
            "minimum_duration": elapsed >= 1800, "on_time_rate": bool(count and len(on_time) / count >= .95),
            "failure_rate": bool(count and len(failed) / count <= .01),
            "no_oom_or_crash": not any(e["kind"] in {"oom", "crash"} for e in self.events),
            "resource_coverage": covered and resource_span, "no_sustained_growth": not growth,
            "budget_complete": not self.stop_reason, "all_requests_terminal": len(success) + len(failed) == count and count > 0}
        trust_verified = False
        verified_receipts = {}
        policy = self.plan["config"].get("client_attestation_policy")
        if policy is not None and (self.server_attestation is not None or self.display_receipts):
            from versioning.performance_receipts import verify_server_evidence, verify_display_receipt, validate_client_clock_sequence
            core = {k:v for k,v in evidence.items() if k != "server_attestation"}
            if self.server_attestation is not None:
                verify_server_evidence(self.plan, core, self.server_attestation)
                for request_id, receipt in self.display_receipts.items():
                    if request_id not in self.requests or set(receipt) != {"backend_receipt", "client_receipt"}:
                        raise ValueError("display receipt changed the original request denominator")
                    r = self.requests[request_id]
                    checked = verify_display_receipt(self.plan, receipt["client_receipt"],
                        backend_receipt=receipt["backend_receipt"], request={"request_id": request_id,
                            "media_id": r["media_id"], "upload_at": r["upload"], "backend_at": r["backend"],
                            "raw_output": r["raw_output"], "upload_nonce": r["upload_nonce"]})
                    if checked["synthetic"] != self.synthetic or r["display"] != checked["display_at"]:
                        raise ValueError("signed display receipt differs from original request clock or provenance")
                    verified_receipts[request_id] = checked
                validate_client_clock_sequence([(self.requests[key]["upload"], receipt) for key, receipt in verified_receipts.items()])
                formal_success_ids = {key for key,r in self.requests.items() if r in success}
                trust_verified = bool(formal_success_ids and formal_success_ids <= set(verified_receipts))
        e2e_verified = trust_verified and collector_qualified and not self.synthetic
        outcome = "synthetic" if self.synthetic else "incomplete"
        if not self.synthetic and e2e_verified and all(gates.values()):
            outcome = "passed"
        elif not self.synthetic and (failed or growth or self.stop_reason):
            outcome = "failed"
        return {"schema_version": "tensile.performance/v1", "purpose": "performance", "protocol": PROTOCOL,
            "eval_version": self.plan["eval_version"], "input_sha256": digest(self.plan),
            "evidence_sha256": digest(evidence), "performance_binding": performance_binding(self.plan),
            "synthetic": self.synthetic, "outcome": outcome, "e2e_verified": e2e_verified,
            "timing_scope": "signed-display-e2e" if trust_verified else ("untrusted-display-events" if any(r["display"] is not None for r in rows) else "backend-only"),
            "runtime_collector_qualified": collector_qualified, "display_signature_trust_verified": trust_verified, "verified_display_receipt_count": len(verified_receipts),
            "display_limitation": None if trust_verified else "trusted client deployment/policy/signed ledger and display receipts are missing or incomplete",
            "expected_gates": gates, "request_count": count, "failure_count": len(failed),
            "on_time_count": len(on_time), "on_time_rate": len(on_time) / count if count else None,
            "failure_rate": len(failed) / count if count else None, "success_p95_seconds": latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
            "elapsed_seconds": elapsed, "observed_until": observed_until, "request_gap_seconds": gaps, "requests_per_minute": count * 60 / elapsed if elapsed else None,
            "peak_vram_bytes": max((r["vram_bytes"] for r in self.resources), default=None),
            "stop_reason": self.stop_reason, "warmup_request_count": sum(r["warmup"] for r in self.requests.values()),
            "cold_start": {"policy": self.plan["config"]["policies"]["cold_start"], **self.lifecycle,
                "seconds": self.lifecycle["ready_at"] - self.lifecycle["cold_start_started_at"] if self.lifecycle["ready_at"] is not None else None},
            "stage_latency_seconds": [{"request_id": request_id,
                "segments": [{"stage": a["kind"], "seconds": b["at"] - a["at"]} for a,b in zip(selected,selected[1:])]}
                for request_id in self.requests for selected in [[e for e in self.events if e["request_id"] == request_id]]],
            "oom_crash_observation_scope": "explicit-events-only; adapter generic failures are not classified as OOM evidence",
            "stage_measurement_gaps": [kind for kind in ("read", "preprocess") if not any(e["kind"] == kind for e in self.events)],
            "stage_events": {kind: sum(e["kind"] == kind for e in self.events) for kind in sorted(EVENTS)}}


def replay_performance_evidence(plan, evidence):
    if (not isinstance(evidence, dict) or set(evidence) != {"schema_version", "plan_sha256", "synthetic", "events", "resources", "observed_until", "stop_reason", "lifecycle", "display_receipts", "server_attestation", "runtime_collector"}
            or evidence["schema_version"] != "tensile.performance-events/v1" or evidence["plan_sha256"] != digest(plan)):
        raise ValueError("performance evidence must match the frozen plan")
    recorder = PerformanceRecorder(plan, synthetic=evidence["synthetic"])
    if evidence["lifecycle"] != {"cold_start_started_at": None, "ready_at": None}:
        recorder.set_lifecycle(**evidence["lifecycle"])
    # Replay resources and events together so budget stops apply before later
    # uploads. Equal timestamps place resource sampling before new requests.
    items = [(e["at"], 1, i, e) for i, e in enumerate(evidence["events"])]
    items += [(r["at"], 0, i, r) for i, r in enumerate(evidence["resources"])]
    for _, kind, _, item in sorted(items, key=lambda row: row[:3]):
        if kind:
            if set(item) != {"request_id", "kind", "at", "media_id", "warmup", "parser", "raw_output", "upload_nonce"}:
                raise ValueError("unexpected performance event fields")
            recorder.event(**item)
        else:
            recorder.resource(**item)
    # Chronological input order is itself audit evidence, not normalized away.
    if recorder.events != evidence["events"] or recorder.resources != evidence["resources"]:
        raise ValueError("performance event/resource series reordered")
    if evidence["stop_reason"] not in {None, "gpu_budget_exhausted", "resource_collection_failed", "session_closed", "runtime_timeout_ambiguous", "runtime_budget_ambiguous"}:
        raise ValueError("unknown performance stop reason")
    if recorder.stop_reason and evidence["stop_reason"] != recorder.stop_reason and not (recorder.stop_reason == "gpu_budget_exhausted" and evidence["stop_reason"] in {"runtime_timeout_ambiguous", "runtime_budget_ambiguous"}):
        raise ValueError("performance import erased the budget stop")
    recorder.stop_reason = evidence["stop_reason"]
    recorder.display_receipts = copy.deepcopy(evidence["display_receipts"])
    recorder.server_attestation = copy.deepcopy(evidence["server_attestation"])
    recorder.runtime_collector = copy.deepcopy(evidence["runtime_collector"])
    return recorder.report(observed_until=evidence["observed_until"])


def build_performance_input(*, root, eval_version, model_version, model_version_number, data_version,
        config, git_commit, media_root, inputs_path=None, probe=None):
    from versioning.registry import open_registry_store, validate_model_for_evaluation
    from versioning.data_release import load_release_metadata
    from versioning.ids import parse_data_id, parse_eval_id, parse_model_id
    from versioning.prompts import load_prompt
    from finetune.train_build_dataset import build_versioned_datasets
    from finetune.eval_run import _model_binding
    root = Path(root).absolute()
    parse_eval_id(eval_version); parse_model_id(model_version); parse_data_id(data_version)
    # This gate precedes dataset construction, row reads and media probes.
    meta = load_release_metadata(root / "data", data_version)
    if meta.purpose != "development" or not meta.training_allowed:
        raise ValueError("performance accepts verified development releases only; no test/holdout")
    config = copy.deepcopy(config)
    if config.get("quantization_bit") not in (None, 4) or type(config.get("quantization_bit")) is bool:
        raise ValueError("explicit quantization_bit must be null or 4")
    if "quantization_bit" not in config:
        raise ValueError("freeze quantization_bit explicitly")
    registry = open_registry_store(root / "workspace/mlflow", data_root=root / "data")
    model = validate_model_for_evaluation(registry, model_version, model_version_number)
    if model.source_scope not in {"base", "diagnostic_fold", "full"}:
        raise ValueError("performance supports verified base/completed-fold/full sources")
    artifact_key = "base" if model.source_kind == "base" else (f"fold{model.source_evidence['fold']}" if model.source_scope == "diagnostic_fold" else "full")
    if config.get("artifact_kind") not in model.artifacts[artifact_key]:
        raise ValueError("selected performance artifact is absent from the verified source")
    if model.source_scope == "full" and model.artifacts[artifact_key][config["artifact_kind"]] != model.deploy_target:
        raise ValueError("full performance must measure the registered delivery artifact")
    prompt_id = config.get("prompt_version") if model.source_kind == "base" else model.prompt_version
    if model.source_kind != "base" and config.get("prompt_version", prompt_id) != prompt_id:
        raise ValueError("trained performance must inherit registered Prompt")
    config["prompt_version"] = prompt_id
    if model.source_scope == "diagnostic_fold" and config.get("fold") != model.source_evidence["fold"]:
        raise ValueError("diagnostic performance must use its completed fold")
    files, binding = build_versioned_datasets(root=root, data_version=data_version, prompt_version=prompt_id,
        media_root=Path(media_root), inputs_path=inputs_path)
    prompt = load_prompt(root, prompt_id)
    fold = config.get("fold")
    if type(fold) is not int or fold not in (0, 1, 2):
        raise ValueError("explicit validation fold required")
    rows = json.loads(files[f"datasets/validation/fold_{fold}.json"])
    videos = {Path(row["videos"][0]).stem: (Path(media_root) / row["videos"][0]).absolute() for row in rows}
    if len(videos) != len(rows):
        raise ValueError("development performance media identities are ambiguous")
    selected = config.get("media_ids")
    if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected) or set(selected) - set(videos):
        raise ValueError("media_ids must explicitly select unique verified development validation media")
    media = []
    for identity in selected:
        path = videos[identity]
        observed = validate_media_metadata((probe or probe_media)(path))
        if observed["size_bytes"] != path.stat().st_size:
            raise ValueError("probe size differs from actual allowlisted bytes")
        media.append({"media_id": identity, "path": str(path), "sha256": file_digest(path), "metadata": observed})
    implementation = {source: file_digest(Path(__file__).resolve().parents[1] / source) for source in IMPLEMENTATIONS}
    variant = config.get("runtime_variant", {})
    if variant.get("preprocessing_sha256") != implementation["pipeline/preprocessing/minicpm_preprocessor.py"]:
        raise ValueError("runtime_variant must freeze actual preprocessing implementation digest")
    from finetune.eval_semantics import default_rules
    value = {"semantic_rules": default_rules(), "schema_version": SCHEMA, "purpose": "performance", "protocol": PROTOCOL,
        "eval_version": eval_version, "model": _model_binding(model), "data_version": data_version,
        "data_binding": binding, "config": config, "git_commit": git_commit,
        "inputs_path": str(Path(inputs_path).absolute()) if inputs_path else None,
        "media_root": str(Path(media_root).absolute()), "media_allowlist": media,
        "prompt": {"version": prompt_id, "system_prompt": prompt.system_prompt, "user_prompt": prompt.user_prompt,
            "output_fields": list(prompt.output_fields)}, "implementation_sha256": implementation,
        "probe_provenance": "synthetic-injected" if probe is not None else "ffprobe"}
    validate_performance_plan(value)
    if not isinstance(git_commit, str) or not git_commit.strip():
        raise ValueError("git_commit required")
    return value


def prepare_performance_evaluation(**kwargs):
    from versioning.manifest import _publish_immutable
    value = build_performance_input(**kwargs)
    path = Path(kwargs["root"]) / "workspace/evaluations" / value["eval_version"] / "input/evaluation.yaml"
    _publish_immutable(path, canonical(value), label="performance frozen input")
    _publish_immutable(path.parent / "sha256", (digest(value) + "\n").encode(), label="performance input seal")
    return path


def verify_performance_evaluation(*, root, eval_version, live=True, probe=None):
    from versioning.ids import parse_eval_id
    parse_eval_id(eval_version)
    path = Path(root) / "workspace/evaluations" / eval_version / "input/evaluation.yaml"
    file_digest(path)
    value = json.loads(path.read_bytes())
    file_digest(path.parent / "sha256")
    if (path.parent / "sha256").read_text().strip() != digest(value):
        raise ValueError("performance frozen input seal differs")
    if value.get("eval_version") != eval_version:
        raise ValueError("performance frozen identity differs")
    validate_performance_plan(value)
    if live:
        actual = build_performance_input(root=root, eval_version=eval_version, model_version=value["model"]["model_id"],
            model_version_number=value["model"]["version"], data_version=value["data_version"], config=value["config"],
            git_commit=value["git_commit"], media_root=value["media_root"], inputs_path=value["inputs_path"], probe=probe)
        if actual != value:
            raise ValueError("performance source/data/Prompt/generation/variant/implementation drift")
    return value


def _metrics(report):
    return {k: float(report[k]) for k in ("request_count", "failure_count", "on_time_count", "elapsed_seconds")}


def execute_performance_evaluation(*, root, eval_version, evidence_path):
    """Import append-event evidence, never execute an implicit real-model run."""
    from versioning.backup import scoped_mlflow_client as MlflowClient
    from versioning.mlflow_eval import (open_eval_store, create_eval_run, create_eval_fold_run,
        end_eval_fold_run, log_eval_summary, transition_eval_state)
    from versioning.manifest import _publish_immutable
    value = verify_performance_evaluation(root=root, eval_version=eval_version)
    file_digest(evidence_path)
    evidence = json.loads(Path(evidence_path).read_bytes())
    report = replay_performance_evidence(value, evidence)
    output = Path(root) / "workspace/evaluations" / eval_version / "output"
    # Reserve a new output once; a second import cannot reset the request
    # denominator, switch synthetic provenance or replace a prior failure.
    output.mkdir(exist_ok=False)
    store = open_eval_store(Path(root) / "workspace/mlflow")
    record = create_eval_run(store, eval_version, model_id=value["model"]["model_id"],
        model_version_number=value["model"]["version"], data_version=value["data_version"],
        config="sha256:" + digest(value), git_commit=value["git_commit"], scope="single_fold", split="validation",
        data_root=Path(root) / "data", purpose="performance", protocol=PROTOCOL)
    client = MlflowClient(tracking_uri=store.tracking_uri)
    try:
        client.log_artifact(record.run_id, str(output.parent / "input/evaluation.yaml"), artifact_path="input")
        documents = {"evaluation.yaml": value, "events.json": evidence, "summary.json": report}
        for name, document in documents.items():
            path = _publish_immutable(output / name, canonical(document), label="performance evidence")
            client.log_artifact(record.run_id, str(path))
            client.log_param(record.run_id, "sha256_" + name, file_digest(path))
        child = create_eval_fold_run(store, eval_version, value["config"]["fold"],
            model_artifact=digest(value["model"]["artifacts"]), data_split="validation",
            sample_count=report["request_count"], records="events.json", failures="events.json")
        end_eval_fold_run(store, eval_version, value["config"]["fold"], "FINISHED", metrics=_metrics(report))
        log_eval_summary(store, eval_version, _metrics(report))
        # MLflow's legacy outcome type is binary; incomplete/synthetic retain
        # failed there and preserve the precise status in the sealed report.
        transition_eval_state(store, eval_version, "completed", outcome="passed" if report["outcome"] == "passed" else "failed")
    except Exception:
        # Keep all imported bytes and the incomplete Run; do not erase them or
        # pretend a failed registration/transfer is a completed measurement.
        raise
    return export_performance_evaluation(root=root, eval_version=eval_version)


def validate_performance_execution(*, store, record, value, artifact_root):
    """Recompute the complete event/resource denominator at every export/gate."""
    from versioning.backup import scoped_mlflow_client as MlflowClient
    from versioning.registry import validate_model_for_evaluation
    from finetune.eval_run import _model_binding
    validate_performance_plan(value)
    # Recheck development qualification, exact Prompt, receipt-backed dataset
    # and media bytes/specs at export and every service admission revalidation.
    project_root = Path(store.data_root).parent
    live = build_performance_input(root=project_root, eval_version=value["eval_version"],
        model_version=value["model"]["model_id"], model_version_number=value["model"]["version"],
        data_version=value["data_version"], config=value["config"], git_commit=value["git_commit"],
        media_root=value["media_root"], inputs_path=value["inputs_path"])
    if live != value:
        raise ValueError("performance live development receipt/media/Prompt/configuration drift")
    if (getattr(record, "purpose", None) != "performance" or getattr(record, "protocol", None) != PROTOCOL
            or record.eval_id != value["eval_version"] or record.model_id != value["model"]["model_id"]
            or record.model_version_number != value["model"]["version"] or record.data_version != value["data_version"]
            or record.config != "sha256:" + digest(value) or record.scope != "single_fold"
            or record.split != "validation" or record.git_commit != value["git_commit"]):
        raise ValueError("performance Run purpose/numeric/source/input binding mismatch")
    model = validate_model_for_evaluation(store, record.model_id, record.model_version_number)
    if _model_binding(model) != value["model"]:
        raise ValueError("performance source/weights changed")
    project = Path(__file__).resolve().parents[1]
    if set(value["implementation_sha256"]) != set(IMPLEMENTATIONS) or any(
            file_digest(project / source) != sha for source, sha in value["implementation_sha256"].items()):
        raise ValueError("performance implementation drift")
    params = MlflowClient(tracking_uri=store.tracking_uri).get_run(record.run_id).data.params
    paths = {name: Path(artifact_root) / name for name in ("evaluation.yaml", "events.json", "summary.json")}
    for name, path in paths.items():
        if file_digest(path) != params.get("sha256_" + name):
            raise ValueError("performance execution evidence digest mismatch")
    if json.loads(paths["evaluation.yaml"].read_bytes()) != value:
        raise ValueError("performance logged input changed")
    evidence = json.loads(paths["events.json"].read_bytes())
    expected = replay_performance_evidence(value, evidence)
    if json.loads(paths["summary.json"].read_bytes()) != expected or record.outcome != ("passed" if expected["outcome"] == "passed" else "failed") or dict(record.metrics) != _metrics(expected):
        raise ValueError("performance report/outcome/metrics differ from original event denominator")
    if set(record.folds) != {value["config"]["fold"]}:
        raise ValueError("performance request fold binding differs")
    child = record.folds[value["config"]["fold"]]
    if child.sample_count != expected["request_count"] or dict(child.metrics) != _metrics(expected):
        raise ValueError("performance child request denominator differs")
    return {"schema_version": "tensile.performance-manifest/v1", "eval_version": record.eval_id,
        "purpose": "performance", "protocol": PROTOCOL, "input_sha256": digest(value),
        "model_version": record.model_id, "model_version_number": record.model_version_number,
        "data_version": record.data_version, "performance_binding": performance_binding(value),
        "outcome": expected["outcome"], "synthetic": expected["synthetic"], "e2e_verified": expected["e2e_verified"],
        "expected_gates": expected["expected_gates"],
        "artifacts": {name: {"uri": f"runs:/{record.run_id}/{name}", "sha256": params["sha256_" + name]} for name in paths}}


def export_performance_evaluation(*, root, eval_version):
    from versioning.registry import open_registry_store, _run_artifact_root
    from versioning.mlflow_eval import open_eval_store, validate_eval_for_conclusion
    from versioning.manifest import _publish_immutable
    value = verify_performance_evaluation(root=root, eval_version=eval_version, live=False)
    store = open_registry_store(Path(root) / "workspace/mlflow", data_root=Path(root) / "data")
    record = validate_eval_for_conclusion(open_eval_store(store.root), eval_version)
    artifact_root = _run_artifact_root(store, record.run_id)
    input_value = json.loads((artifact_root / "input/evaluation.yaml").read_bytes())
    if input_value != value:
        raise ValueError("local and MLflow performance inputs differ")
    manifest = validate_performance_execution(store=store, record=record, value=value, artifact_root=artifact_root)
    return _publish_immutable(Path(root) / "records/evaluations" / eval_version / "manifest.yaml",
        canonical(manifest), label="performance manifest")
