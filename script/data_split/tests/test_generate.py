"""Synthetic behavior checks for the confirmed source-group split contract.

No fixture reads project annotations, split members, or media. A group declaration
is supplied explicitly; these tests do not establish real source independence.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from script.data_split import generate as splitter


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_FIELDS = (
    "断裂状态", "断裂模式", "断裂位置",
    "异常_未夹紧", "异常_视频异常", "异常_爆炸性断裂",
    "现象_伸长", "现象_颈缩", "现象_开裂", "现象_界面分离", "现象_断后脱夹",
)


def video_id(alias):
    if alias.startswith("video_"):
        return alias
    fixed = {"a": 901, "b": 902, "c": 903, "d": 904, "test": 999, "unknown": 9999}
    if alias in fixed:
        number = fixed[alias]
    elif alias.startswith("rare"):
        number = 101 + int(alias[4:])
    elif alias.startswith("common"):
        number = 201 + int(alias[6:])
    else:
        number = 1 + int(alias[1:])
    return f"video_{number:04d}"


def row(alias, **changes):
    value = {
        "id": video_id(alias),
        "video_path": f"not-real-media/{video_id(alias)}.mp4",
        "标注状态": "已标注·有断裂",
        "断裂状态": "发生断裂",
        "断裂模式": "韧性断裂",
        "断裂位置": "标距内",
        **{field: "否" for field in MODEL_FIELDS[3:]},
    }
    value.update(changes)
    return value


def labels_for(rows):
    return splitter.validate_labels(rows, expected_count=None)


def group(group_id, *video_ids):
    return {"group_id": group_id, "video_ids": [video_id(v) for v in video_ids]}


def problem(rows, groups):
    labels = labels_for(rows)
    return splitter.Problem(labels, groups)


def test_singleton_is_held_out_once_and_two_positives_use_two_validation_folds():
    rows = [row(f"v{i}") for i in range(6)]
    rows[0]["异常_视频异常"] = "是"  # One supporting group, not permanent training.
    rows[1]["现象_开裂"] = rows[2]["现象_开裂"] = "是"
    groups = [group(f"g{i}", f"v{i}") for i in range(6)]
    result = splitter.search(problem(rows, groups))
    assignment = result["best_assignment"]

    singleton_fold = assignment[0]
    assert sum(singleton_fold == fold for fold in range(3)) == 1
    assert sum(singleton_fold != fold for fold in range(3)) == 2
    assert assignment[1] != assignment[2]
    assert sorted(sum(assignment[i] == fold for i in (1, 2)) for fold in range(3)) == [0, 1, 1]


def test_coverage_outranks_a_more_balanced_video_count():
    rows = [row(f"rare{i}", **{"现象_开裂": "是"}) for i in range(3)]
    rows += [row(f"common{i}") for i in range(3)]
    groups = [group(f"g{i}", f"rare{i}") for i in range(3)]
    groups.append(group("g3", "common0", "common1", "common2"))
    candidate = problem(rows, groups)

    covered = candidate.score((0, 1, 2, 0))  # Validation video counts 4, 1, 1.
    balanced = candidate.score((0, 0, 1, 2))  # Counts 2, 1, 3, but one rare fold absent.
    assert covered[:3] == (0, 6, 12)
    assert balanced[:3] == (1, 3, 6)
    assert covered < balanced


def test_group_evidence_is_union_of_member_labels_not_number_of_videos():
    rows = [row("a", **{"现象_开裂": "是"}), row("b", **{"现象_开裂": "是"}), row("c"), row("d")]
    candidate = problem(rows, [group("g0", "a", "b"), group("g1", "c"), group("g2", "d")])
    # There is only one supporting group for 是. Duplicating its videos cannot
    # turn it into g=2 or create a required second validation fold.
    assert candidate.score((0, 1, 2))[0] == 0


def test_unknown_multiselect_does_not_supply_negative_evidence():
    rows = [row(f"v{i}", **{"现象_伸长": "否" if i < 2 else "无法判断"}) for i in range(6)]
    candidate = problem(rows, [group(f"g{i}", f"v{i}") for i in range(6)])
    # Two known negatives share fold 0, whereas unknowns appear in every fold.
    # Only the known negatives trigger g=2 coverage, leaving exactly one gap.
    assert candidate.score((0, 0, 0, 1, 2, 2))[0] == 1


def test_unknown_and_fixed_none_do_not_create_determined_coverage_targets():
    rows = [row(f"v{i}", **{
        "断裂状态": "未断裂" if i < 3 else "无法确定",
        "断裂模式": "无" if i < 3 else "无法确定",
        "断裂位置": "无" if i < 3 else "无法确定",
        "标注状态": "已标注·无断裂" if i < 3 else "无法判读",
    }) for i in range(6)]
    candidate = problem(rows, [group(f"g{i}", f"v{i}") for i in range(6)])
    # Determined 未断裂 is balanced. 无 and unknown each cluster, but do not
    # generate coverage penalties; they remain separate distribution targets.
    score = candidate.score((0, 1, 2, 0, 0, 0))
    assert score[0] == 0
    assert score[3] > 0


@pytest.mark.parametrize("damage", ["missing_id", "duplicate_id", "blank_label", "bad_enum", "bad_fixed_combination"])
def test_incomplete_or_invalid_labels_fail_closed(damage):
    rows = [row("a"), row("b")]
    if damage == "missing_id":
        del rows[0]["id"]
    elif damage == "duplicate_id":
        rows[1]["id"] = rows[0]["id"]
    elif damage == "blank_label":
        rows[0]["现象_开裂"] = ""
    elif damage == "bad_enum":
        rows[0]["现象_开裂"] = "未知的新标签"
    else:
        rows[0]["断裂状态"] = "未断裂"  # Requires mode/location 无.
        rows[0]["标注状态"] = "已标注·无断裂"
    with pytest.raises(ValueError):
        labels_for(rows)


@pytest.mark.parametrize("groups,test_ids", [
    ([group("g", "a", "test")], ["test"]),
    ([group("g", "a"), group("h", "a", "test")], ["test"]),
    ([group("g", "a")], ["test"]),
    ([group("g", "a", "unknown"), group("t", "test")], ["test"]),
    ([group("g", "a"), group("g", "test")], ["test"]),
])
def test_cross_boundary_or_incomplete_group_declarations_are_rejected(groups, test_ids):
    labels = labels_for([row("a"), row("test")])
    with pytest.raises(ValueError):
        splitter.validate_groups({"groups": groups}, labels, [video_id(v) for v in test_ids])


def test_final_tie_uses_sorted_group_id_fold_sequence():
    candidate = problem([row("a"), row("b"), row("c")], [group("g0", "a"), group("g1", "b"), group("g2", "c")])
    left = candidate.score((0, 1, 2))
    right = candidate.score((1, 0, 2))
    assert left[:-1] == right[:-1]
    assert left < right


def test_declared_seed_range_and_input_order_give_reproducible_search():
    rows = [row(f"v{i}", **{"现象_开裂": "是" if i < 2 else "否"}) for i in range(6)]
    groups = [group(f"g{i}", f"v{i}") for i in range(6)]
    first = splitter.search(problem(rows, groups), seeds=range(42, 142))
    second = splitter.search(problem(list(reversed(rows)), list(reversed(groups))), seeds=range(42, 142))
    assert first == second
    assert len(first["candidates"]) == 100


def write_inputs(directory, *, reverse=False):
    directory.mkdir(parents=True)
    rows = [row(f"video_{i+1:04d}") for i in range(110)]
    rows[0].update({"断裂状态": "未断裂", "断裂模式": "无", "断裂位置": "无", "标注状态": "已标注·无断裂"})
    rows[1].update({"断裂状态": "无法判断", "断裂模式": "无法识别", "断裂位置": "无法确定", "标注状态": "无法判读"})
    rows[2]["现象_伸长"] = "无法判断"
    for index, entry in enumerate(rows):
        entry["标注备注"] = '合成备注，保留逗号,"引号"\n以及换行' if index in (1, 90) else ""
        entry["断裂时间点"] = "无" if index == 0 else f"{index}.25"
    test_ids = [entry["id"] for entry in rows[89:]]
    # Deliberately declare only three synthetic development sources, each with
    # multiple videos. 110 IDs are not evidence of 110 independent sources.
    groups = [
        group("dev_a", *(entry["id"] for entry in rows[:30])),
        group("dev_b", *(entry["id"] for entry in rows[30:60])),
        group("dev_c", *(entry["id"] for entry in rows[60:89])),
        *[group(f"test_{i:03d}", entry["id"]) for i, entry in enumerate(rows[89:])],
    ]
    if reverse:
        rows.reverse()
        groups.reverse()
        for entry in groups:
            entry["video_ids"].reverse()
    labels_path = directory / "labels.csv"
    with labels_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    test_path = directory / "test.json"
    test_path.write_text(json.dumps({"video_ids": test_ids}, ensure_ascii=False), encoding="utf-8")
    groups_path = directory / "groups.json"
    groups_path.write_text(json.dumps({"groups": groups}, ensure_ascii=False), encoding="utf-8")
    return labels_path, test_path, groups_path


def run_cli(inputs, output_dir, *, hash_seed="1"):
    labels, test, groups = inputs
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "script/data_split/generate.py"),
         "--labels", str(labels), "--test-split", str(test), "--groups", str(groups),
         "--output-dir", str(output_dir)],
        cwd=PROJECT_ROOT, env={**os.environ, "PYTHONHASHSEED": hash_seed},
        capture_output=True, text=True, timeout=120,
    )


def output_bytes(directory):
    return {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("*") if path.is_file()}


def test_existing_output_directory_is_preserved(tmp_path):
    inputs = write_inputs(tmp_path / "inputs")
    output = tmp_path / "release"
    output.mkdir()
    (output / "keep.txt").write_text("user-owned existing data", encoding="utf-8")
    before = output_bytes(output)
    result = run_cli(inputs, output)
    assert result.returncode != 0
    assert output_bytes(output) == before


def test_rejected_input_does_not_publish_a_partial_directory(tmp_path):
    labels, test, groups_path = write_inputs(tmp_path / "inputs")
    groups = json.loads(groups_path.read_text(encoding="utf-8"))
    groups["groups"][0]["video_ids"].append("video_0090")
    groups_path.write_text(json.dumps(groups), encoding="utf-8")
    output = tmp_path / "release"
    result = run_cli((labels, test, groups_path), output)
    assert result.returncode != 0
    assert not output.exists()


def test_test_labels_cannot_change_the_development_score_or_assignment():
    dev = [row(f"v{i}") for i in range(6)]
    groups = [group(f"g{i}", f"v{i}") for i in range(6)]
    first_labels = labels_for(dev + [row("test")])
    second_labels = labels_for(dev + [row("test", **{
        "断裂状态": "无法确定", "断裂模式": "无法确定",
        "断裂位置": "无法确定", "标注状态": "无法判读",
        "现象_开裂": "是", "现象_伸长": "无法判断",
    })])
    first = splitter.Problem(first_labels, groups)
    second = splitter.Problem(second_labels, groups)
    assert first.score((0, 1, 2, 0, 1, 2)) == second.score((0, 1, 2, 0, 1, 2))
    assert splitter.search(first)["best_assignment"] == splitter.search(second)["best_assignment"]


@pytest.fixture
def published(tmp_path):
    inputs = write_inputs(tmp_path / "inputs")
    output = tmp_path / "release"
    result = run_cli(inputs, output)
    assert result.returncode == 0, result.stderr
    return inputs, output, json.loads(result.stdout)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_cli_preserves_test_and_rotates_whole_development_sources(published):
    inputs, output, _ = published
    test_ids = set(load_json(inputs[1])["video_ids"])
    dev_ids = {f"video_{i:04d}" for i in range(1, 90)}
    assert (output / "test.json").read_bytes() == inputs[1].read_bytes()
    validation_occurrences = {video: 0 for video in dev_ids}
    training_occurrences = {video: 0 for video in dev_ids}
    declared = load_json(inputs[2])["groups"][:3]
    for fold in range(3):
        train_ids = load_json(output / f"fold_{fold}_train.json")["video_ids"]
        val_ids = load_json(output / f"fold_{fold}_val.json")["video_ids"]
        assert train_ids == sorted(train_ids)
        assert val_ids == sorted(val_ids)
        train, val = set(train_ids), set(val_ids)
        assert len(train_ids) == len(train) and len(val_ids) == len(val)
        assert train.isdisjoint(val)
        assert (train | val) == dev_ids
        assert (train | val).isdisjoint(test_ids)
        for source in declared:
            members = set(source["video_ids"])
            assert members <= train or members <= val
        for video in train:
            training_occurrences[video] += 1
        for video in val:
            validation_occurrences[video] += 1
    assert set(validation_occurrences.values()) == {1}
    assert set(training_occurrences.values()) == {2}


def test_release_binds_input_rules_code_and_all_output_bytes(published):
    inputs, output, cli = published
    manifest_path = output / "manifest.json"
    manifest = load_json(manifest_path)
    assert cli["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    expected_inputs = {"labels.csv": inputs[0], "test.json": inputs[1], "groups.json": inputs[2],
                       "docs_label.md": PROJECT_ROOT / "docs/label.md",
                       "docs_data-split-design.md": splitter.resolve_design_document(PROJECT_ROOT),
                       "generate.py": PROJECT_ROOT / "script/data_split/generate.py"}
    for name, path in expected_inputs.items():
        content = path.read_bytes()
        assert manifest["inputs"][name]["sha256"] == hashlib.sha256(content).hexdigest()
    assert set(manifest["outputs"]) == set(output_bytes(output)) - {"manifest.json"}
    for name, identity in manifest["outputs"].items():
        assert identity["sha256"] == hashlib.sha256((output / name).read_bytes()).hexdigest()
    assert manifest["code_commit"]
    assert manifest["environment"]["python"]
    assert manifest["rule_version"]
    assert manifest["manual_exceptions"] == []
    search = manifest["search_summary"]
    assert manifest["config"]["seeds"] == list(range(42, 142))
    assert search["start_count"] == 100
    assert search["global_optimality_proven"] is False
    assert search["test_labels_used_for_objective"] is False


def test_release_contains_only_members_and_manifest_and_preserves_inputs(tmp_path):
    inputs = write_inputs(tmp_path / "inputs")
    before = {path: path.read_bytes() for path in inputs}
    output = tmp_path / "release"
    result = run_cli(inputs, output)
    assert result.returncode == 0, result.stderr
    expected = {"test.json", "manifest.json"} | {
        f"fold_{fold}_{split}.json" for fold in range(3) for split in ("train", "val")}
    assert set(output_bytes(output)) == expected
    assert all(path.read_bytes() == content for path, content in before.items())
    manifest = load_json(output / "manifest.json")
    assert manifest["counts"] == {
        name.removesuffix(".json"): len(load_json(output / name)["video_ids"])
        for name in expected - {"manifest.json"}}


def test_compact_output_preserves_pre_cleanup_synthetic_member_bytes(published):
    # Captured from the previous full-output implementation using write_inputs.
    # These are synthetic fixtures, not project annotations or real test data.
    expected = {
        "fold_0_train.json": "afb0bdd913ad006fd1f58c5d36d984b4f1f36061c319d0de5c47aec86d14f2b8",
        "fold_0_val.json": "0a3cf69c252e30b2bc4f1fbcb8f3ac64778635b8e0a187c6206116a2cd0010b1",
        "fold_1_train.json": "bfc8118c9727b352e37329359fbc5bfa67158a2e18d2a1bbd4eae76a2fe0f58a",
        "fold_1_val.json": "05fb138dca2f9f62ebc5370f219905f53acf79b009cbb5b88bd7965478c3feec",
        "fold_2_train.json": "40dcd8117bd157e1fa46814a0bcd6418941b9fc7eeb4b17e32a41b6c9b6a5eef",
        "fold_2_val.json": "8cfa1601d0f743df1e1831de631102f92fbd728fa80bb86082af9ee62a99f969",
        "test.json": "b2a923a4988562c713e66bf14e107999f33b7b9a615c5980ed8a467e956abc04",
    }
    _, output, _ = published
    assert {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in expected} == expected


def test_cli_same_inputs_are_byte_reproducible_across_hash_seeds(published, tmp_path):
    inputs, output, _ = published
    second = tmp_path / "second-release"
    result = run_cli(inputs, second, hash_seed="994")
    assert result.returncode == 0, result.stderr
    assert output_bytes(output) == output_bytes(second)


def test_cli_sorted_assignments_ignore_csv_group_and_member_order(published, tmp_path):
    _, output, _ = published
    inputs = write_inputs(tmp_path / "reordered", reverse=True)
    second = tmp_path / "reordered-release"
    result = run_cli(inputs, second)
    assert result.returncode == 0, result.stderr
    for name in [*(f"fold_{fold}_{split}.json" for fold in range(3) for split in ("train", "val")),
                 "test.json"]:
        assert (output / name).read_bytes() == (second / name).read_bytes(), name
    # Input-byte identities must still reflect the changed CSV/group order.
    assert load_json(output / "manifest.json")["inputs"]["labels.csv"] != load_json(second / "manifest.json")["inputs"]["labels.csv"]


def test_publication_failure_after_staging_leaves_no_formal_or_partial_release(tmp_path, monkeypatch):
    inputs = write_inputs(tmp_path / "inputs")
    output = tmp_path / "release"
    attempted = []

    def fail_rename(source, destination):
        assert Path(source).is_dir()
        assert (Path(source) / "manifest.json").is_file()
        attempted.append((source, destination))
        raise OSError("synthetic publication failure")

    monkeypatch.setattr(splitter, "_publish_new_directory", fail_rename)
    with pytest.raises(OSError, match="synthetic publication failure"):
        splitter.generate(*inputs, output)
    assert len(attempted) == 1
    assert not output.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["inputs"]


def test_output_appearing_at_atomic_publication_is_not_replaced(tmp_path, monkeypatch):
    inputs = write_inputs(tmp_path / "inputs")
    output = tmp_path / "release"
    publish = splitter._publish_new_directory

    def concurrent_directory(source, destination):
        # An empty existing directory is significant: POSIX rename() alone can
        # replace it even after an earlier exists() check has passed.
        Path(destination).mkdir()
        publish(source, destination)

    monkeypatch.setattr(splitter, "_publish_new_directory", concurrent_directory)
    with pytest.raises(OSError):
        splitter.generate(*inputs, output)
    assert output.is_dir()
    assert list(output.iterdir()) == []
    assert sorted(path.name for path in tmp_path.iterdir()) == ["inputs", "release"]


@pytest.mark.parametrize("relative", [
    "docs/data-split-design.md", "docs/split/data-split-design.md",
])
def test_design_document_accepts_either_single_known_location(tmp_path, relative):
    document = tmp_path / relative
    document.parent.mkdir(parents=True)
    document.write_bytes(b"confirmed split rules\n")

    assert splitter.resolve_design_document(tmp_path) == document


def test_identical_design_documents_prefer_the_current_location(tmp_path):
    old = tmp_path / "docs/data-split-design.md"
    current = tmp_path / "docs/split/data-split-design.md"
    current.parent.mkdir(parents=True)
    old.write_bytes(b"same confirmed rules\n")
    current.write_bytes(old.read_bytes())

    assert splitter.resolve_design_document(tmp_path) == current


def test_conflicting_design_documents_are_not_silently_selected(tmp_path):
    old = tmp_path / "docs/data-split-design.md"
    current = tmp_path / "docs/split/data-split-design.md"
    current.parent.mkdir(parents=True)
    old.write_bytes(b"first confirmed rules\n")
    current.write_bytes(b"different rules awaiting confirmation\n")

    with pytest.raises(splitter.SplitError):
        splitter.resolve_design_document(tmp_path)
    assert old.read_bytes() == b"first confirmed rules\n"
    assert current.read_bytes() == b"different rules awaiting confirmation\n"


def test_missing_design_documents_report_a_split_input_error(tmp_path):
    with pytest.raises(splitter.SplitError):
        splitter.resolve_design_document(tmp_path)


@pytest.mark.parametrize("invalid", [
    "docs/data-split-design.md", "docs/split/data-split-design.md",
])
def test_design_document_directory_cannot_be_ignored_for_another_valid_file(tmp_path, invalid):
    old = tmp_path / "docs/data-split-design.md"
    current = tmp_path / "docs/split/data-split-design.md"
    invalid_path = tmp_path / invalid
    valid_path = current if invalid_path == old else old
    invalid_path.mkdir(parents=True)
    valid_path.parent.mkdir(parents=True, exist_ok=True)
    valid_path.write_bytes(b"valid rules do not excuse an invalid competing path\n")

    with pytest.raises(splitter.SplitError):
        splitter.resolve_design_document(tmp_path)


def test_generation_uses_current_design_and_versioned_groups_snapshot_without_old_directories(tmp_path, monkeypatch):
    root = tmp_path / "project"
    module = root / "script/data_split/generate.py"
    module.parent.mkdir(parents=True)
    module.write_bytes(Path(splitter.__file__).read_bytes())
    design = root / "docs/split/data-split-design.md"
    design.parent.mkdir(parents=True)
    design.write_bytes(b"current confirmed design snapshot\n")
    (root / "docs/label.md").write_bytes(b"synthetic label rules snapshot\n")
    labels, test, original_groups = write_inputs(root / "synthetic-inputs")
    groups = root / "data/splits/previous/input_groups.json"
    groups.parent.mkdir(parents=True)
    groups.write_bytes(original_groups.read_bytes())
    original_groups.unlink()
    groups_before = groups.read_bytes()
    monkeypatch.setattr(splitter, "__file__", str(module))
    output = root / "data/splits/new-version"

    result = splitter.generate(labels, test, groups, output)

    assert result["inputs"]["groups.json"]["sha256"] == hashlib.sha256(groups_before).hexdigest()
    # The old manifest input key remains stable even though the document
    # now comes from docs/split. This preserves downstream evidence consumers.
    assert result["inputs"]["docs_data-split-design.md"]["sha256"] == hashlib.sha256(design.read_bytes()).hexdigest()
    assert "docs_split_data-split-design.md" not in result["inputs"]
    assert not (root / "docs/data-split-design.md").exists()
    assert not (root / "data/split-inputs").exists()
    assert groups.read_bytes() == groups_before


def test_cli_still_requires_an_explicit_groups_input(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        splitter.main(["--labels", str(tmp_path / "labels.csv"),
                       "--test-split", str(tmp_path / "test.json"),
                       "--output-dir", str(tmp_path / "new-version")])
    assert exc.value.code == 2
    assert "--groups" in capsys.readouterr().err
    assert not (tmp_path / "new-version").exists()


def test_conflicting_design_copy_appearing_during_search_prevents_publication(tmp_path, monkeypatch):
    root = tmp_path / "project"
    module = root / "script/data_split/generate.py"
    module.parent.mkdir(parents=True)
    module.write_bytes(Path(splitter.__file__).read_bytes())
    design = root / "docs/split/data-split-design.md"
    design.parent.mkdir(parents=True)
    design.write_bytes(b"current confirmed rules\n")
    (root / "docs/label.md").write_bytes(b"synthetic label rules\n")
    inputs = write_inputs(root / "inputs")
    monkeypatch.setattr(splitter, "__file__", str(module))
    search = splitter.search

    def search_while_another_tool_creates_a_conflicting_document(*args, **kwargs):
        result = search(*args, **kwargs)
        (root / "docs/data-split-design.md").write_bytes(b"different competing rules\n")
        return result

    monkeypatch.setattr(splitter, "search", search_while_another_tool_creates_a_conflicting_document)
    output = root / "release"
    with pytest.raises(splitter.SplitError):
        splitter.generate(*inputs, output)
    assert not output.exists()
    assert not list(root.glob(".release*"))
    assert design.read_bytes() == b"current confirmed rules\n"


@pytest.mark.parametrize("change", ["competing_design", "groups"])
def test_input_changes_after_staging_creation_prevent_publication(tmp_path, monkeypatch, change):
    root = tmp_path / "project"
    module = root / "script/data_split/generate.py"
    module.parent.mkdir(parents=True)
    module.write_bytes(Path(splitter.__file__).read_bytes())
    design = root / "docs/split/data-split-design.md"
    design.parent.mkdir(parents=True)
    design.write_bytes(b"current confirmed rules\n")
    (root / "docs/label.md").write_bytes(b"synthetic label rules\n")
    inputs = write_inputs(root / "inputs")
    monkeypatch.setattr(splitter, "__file__", str(module))
    create_staging = splitter.tempfile.mkdtemp
    staged = []

    def create_staging_then_change_an_input(*args, **kwargs):
        path = create_staging(*args, **kwargs)
        staged.append(Path(path))
        if change == "competing_design":
            (root / "docs/data-split-design.md").write_bytes(b"competing rules after staging\n")
        else:
            # Semantically valid but different bytes must also invalidate the
            # release, whose groups snapshot was captured before staging.
            inputs[2].write_bytes(inputs[2].read_bytes() + b"\n")
        return path

    monkeypatch.setattr(splitter.tempfile, "mkdtemp", create_staging_then_change_an_input)
    output = root / "release"
    with pytest.raises(splitter.SplitError):
        splitter.generate(*inputs, output)

    assert len(staged) == 1, "exercise the late staging window, not early validation"
    assert not output.exists()
    assert not staged[0].exists()
    assert not (root / ".release.publish-lock").exists()
    assert design.read_bytes() == b"current confirmed rules\n"
