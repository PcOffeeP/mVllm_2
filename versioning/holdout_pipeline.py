"""Explicit test data branch; legacy wire values remain holdout/test_audit.

No command starts model inference or issues a test-use authorization.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from versioning import data_pipeline as dp
from versioning.data_release import (load_release_metadata, stage_release, seal_release,
                                     assert_payload_sealed, ReleaseConflict)
from versioning.ids import parse_data_id


def _ordinary_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise dp.StageInputError('test 分支路径不得经过符号链接')
    return path


def _private_dir(path):
    path = _ordinary_path(path)
    if path.exists():
        if not path.is_dir() or path.stat().st_mode & 0o077:
            raise dp.StageInputError('test 工作区必须为 owner-only 普通目录')
    else:
        path.mkdir(parents=True, mode=0o700)
    return path


def _json(path):
    return dp._read_pinned_document(dp._external_document_pin(_ordinary_path(path)))


def _sources(value):
    if not isinstance(value, dict) or not value:
        raise dp.StageInputError('source 身份清单必须完整且非空')
    for key, digest in value.items():
        if (not isinstance(key, str) or re.fullmatch(r'video_\d{4}', key) is None
                or not isinstance(digest, str) or re.fullmatch(r'[0-9a-f]{64}', digest) is None):
            raise dp.StageInputError('source 身份或内容摘要非法')
    return value


def load_config(root, inputs_path, batch, config_path):
    """Read pinned non-semantic isolation evidence; never read old test truth."""
    root = _ordinary_path(root)
    inputs = dp.load_data_inputs(inputs_path, batch=batch)
    pin = dp._external_document_pin(_ordinary_path(config_path))
    config = dp._input_mapping(dp._read_pinned_document(pin), {
        'schema', 'batch', 'inputs_sha256', 'development_data_version',
        'development_release_sha256', 'development_sources', 'used_test_sources',
    }, 'test-config')
    if (config['schema'] != 'tensile-data/holdout-build/v1' or config['batch'] != batch
            or config['inputs_sha256'] != inputs.config_sha256):
        raise dp.StageInputError('test config schema/batch/inputs 不一致')
    version = str(parse_data_id(config['development_data_version']))
    release = root / 'data/releases' / version
    _ordinary_path(release / 'release.yaml')
    meta = load_release_metadata(root / 'data', version)
    if meta.purpose != 'development' or not meta.training_allowed:
        raise dp.StageInputError('test 必须绑定 train 数据版本')
    if dp._sha256_file(release / 'release.yaml') != config['development_release_sha256']:
        raise dp.StageInputError('train release 身份漂移')
    inventories = []
    for field in ('development_sources', 'used_test_sources'):
        ref = dp._pin_input_file(config[field], inputs.project_root, field)
        doc = dp._input_mapping(dp._read_pinned_document(ref), {
            'schema', 'sources', 'reviewer_id', 'reviewed_at', 'scope', 'reference'}, field)
        if doc['schema'] != 'tensile-data/source-isolation/v1' or doc['scope'] != field:
            raise dp.StageInputError('隔离清单 scope/schema 不一致')
        for name in ('reviewer_id', 'reviewed_at', 'reference'):
            dp._input_text(doc[name], name)
        from datetime import datetime
        if datetime.fromisoformat(doc['reviewed_at'].replace('Z', '+00:00')).tzinfo is None:
            raise dp.StageInputError('隔离审查时间必须含时区')
        inventories.append(_sources(doc['sources']))
    train, used = inventories
    candidates = _json(release / 'payload/metadata/training_candidates.json')
    if candidates.get('version') != version or {r['source_video'] for r in candidates['candidates']} != set(train):
        raise dp.StageInputError('train source 清单与已发布候选覆盖不一致')
    splits = dp._load_input_splits(inputs)
    selected = {v.video_id: v.file.sha256 for v in inputs.videos if v.video_id in splits['test']}
    if not selected:
        raise dp.StageInputError('test source 为空')
    if len(set(selected.values())) != len(selected):
        raise dp.StageInputError('test source 内容重复')
    if set(selected) & (set(train) | set(used)) or set(selected.values()) & (set(train.values()) | set(used.values())):
        raise dp.StageInputError('test source 与 train/已使用测试身份或内容重叠')
    # This branch operates on a dedicated test batch, never processes train labels.
    if set(selected) != {v.video_id for v in inputs.videos}:
        raise dp.StageInputError('test 分支输入必须为独立的全 test source 批次')
    values, *_ = dp._load_media_inputs(inputs)
    if values['test_reference']['records'] or values['development_reference']['records']:
        raise dp.StageInputError('新 test 分支不得携入历史参考语义记录')
    return inputs, config, {'config_sha256': pin.sha256, 'inputs_sha256': inputs.config_sha256,
                            'development_data_version': version,
                            'development_release_sha256': config['development_release_sha256'],
                            'source_sha256': selected}


def _workspace(root, batch):
    parent = _private_dir(Path(root) / 'data/test_working')
    return _private_dir(parent / batch)


def _review_rows(work, inputs):
    subdir, _ = dp._load_input_stage(work, inputs, 'subvideo')
    exportdir, _ = dp._load_input_stage(work, inputs, 'review_export')
    reviewdir, _ = dp._load_input_stage(work, inputs, 'review_import')
    sub = dp._stage_json(subdir, 'subvideo_manifest.json')
    queue = dp._stage_json(exportdir, 'review_queue.json')
    review = dp._validate_input_review_return(dp._stage_json(reviewdir, 'review_return.json'),
                                             queue, dp._sha256_file(exportdir / 'stage_manifest.json'))
    candidates = sub['candidates']
    if (not candidates or any(r['scope'] != 'test_audit' for r in candidates)
            or {r['candidate_id'] for r in candidates} != {r['candidate_id'] for r in queue['candidates']}):
        raise dp.ReviewGateError('test 审查必须覆盖全部候选')
    decisions = {r['clip_id']: r for r in review['review']['decisions']}
    rows = [(r, decisions[r['candidate_id']]['effective_labels']) for r in candidates
            if decisions[r['candidate_id']]['review_status'] not in {'dropped', 'needs_regenerate'}]
    if not rows:
        raise dp.ReviewGateError('test 审查后没有可发布候选')
    return subdir, rows, review, dp._sha256_file(reviewdir / 'stage_manifest.json')


def _inventory(release):
    return {name: dp._stage_inventory(release / name, exclude_manifest=False)
            for name in ('media', 'evaluation_inputs', 'sealed_ground_truth', 'payload')}


def _validate_release(root, version, binding):
    final = Path(root) / 'data/releases' / version
    meta = load_release_metadata(Path(root) / 'data', version)
    if meta.purpose != 'holdout' or meta.training_allowed:
        raise dp.StageInputError('发布对象不是 test 分支')
    assert_payload_sealed(final)
    receipt = _json(final / 'build_receipt.json')
    if receipt['binding'] != binding or receipt['version'] != version or receipt['inventory'] != _inventory(final):
        raise dp.StageInputError('test 发布内容或绑定漂移')
    for path in (final / 'sealed_ground_truth', *(final / 'sealed_ground_truth').rglob('*')):
        if path.stat().st_mode & 0o077:
            raise dp.StageInputError('test 真值证据权限越界')
    manifest = _json(final / 'evaluation_inputs/manifest.json')
    truth = _json(final / 'sealed_ground_truth/labels.json')
    if (meta.sample_count != len(manifest['samples']) or len(truth['labels']) != meta.sample_count
            or set(truth['labels']) != {r['candidate_id'] for r in manifest['samples']}):
        raise dp.StageInputError('test 发布样本覆盖不一致')
    return dp.StageResult('release_validate', (final,), {'version': version, 'passed': True})


def _release(root, work, inputs, config, binding, version):
    parsed = parse_data_id(version)
    from pipeline.v4_1_training_release import _contract_identity
    contract, _ = _contract_identity(inputs.contract.path)
    if parsed.protocol != str(contract['contract_version']).removeprefix('tensile-vlm/'):
        raise dp.StageInputError('test release 协议与契约不一致')
    subdir, rows, review, review_sha = _review_rows(work, inputs)
    data = Path(root) / 'data'
    dp._check_input_release_paths(Path(root), version)
    final = data / 'releases' / version
    if final.exists():
        committed = _json(final / 'build_receipt.json')
        if committed['binding'] != binding or committed['inventory'] != _inventory(final):
            raise ReleaseConflict('test 已发布内容或操作身份冲突')
        if committed['review_sha256'] != review_sha:
            raise ReleaseConflict('test 已发布审查身份冲突')
        if final.stat().st_mode & 0o222:
            for child in final.rglob('*'):
                if child.relative_to(final).parts[0] not in {'release.yaml', 'README.md', 'authorization'} and child.stat().st_mode & 0o222:
                    raise ReleaseConflict('test 封存尾步之外的权限漂移')
            final.chmod(final.stat().st_mode & ~0o222)
        return _validate_release(root, version, binding)
    if (data / 'release_staging' / version).exists():
        # Resume only the sealed intent belonging to exactly this operation.
        staged = data / 'release_staging' / version
        receipt = _json(staged / 'build_receipt.json')
        if (receipt['binding'] != binding or receipt['version'] != version
                or receipt['review_sha256'] != review_sha or receipt['inventory'] != _inventory(staged)):
            raise ReleaseConflict('test staging 不是同一完整操作')
    else:
        (data / 'working').mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.test-release-', dir=data / 'working') as temp:
            build = Path(temp) / 'build'; build.mkdir(mode=0o700)
            for name in ('media', 'evaluation_inputs', 'sealed_ground_truth', 'payload', 'authorization'):
                (build / name).mkdir(mode=0o700)
            samples, labels = [], {}
            for row, target in rows:
                cid = row['candidate_id']; pin = dp._candidate_media_pin(subdir, row, video=True)
                name = f'{cid}.mp4'
                dp._copy_input_pin(pin, build / 'media' / name)
                samples.append({'candidate_id': cid, 'source_video': row['source_video'], 'video_path': name})
                labels[cid] = target
            dp._write_json(build / 'evaluation_inputs/manifest.json', {
                'schema_version': 'tensile-holdout-media/v1', 'data_version': version, 'split': 'holdout',
                'development_data_version': config['development_data_version'],
                'development_source_isolation_verified': True, 'test_split_binding_verified': True, 'samples': samples})
            dp._write_json(build / 'sealed_ground_truth/labels.json', {
                'schema_version': 'tensile-holdout-truth/v1', 'data_version': version, 'split': 'holdout', 'labels': labels})
            dp._write_json(build / 'sealed_ground_truth/review.json', review)
            dp._write_json(build / 'sealed_ground_truth/isolation.json', config)
            for name in ('development_sources', 'used_test_sources'):
                dp._copy_input_pin(dp._pin_input_file(config[name], inputs.project_root, name),
                                   build / 'sealed_ground_truth' / f'{name}.json')
            exportdir, _ = dp._load_input_stage(work, inputs, 'review_export')
            dp._write_json(build / 'sealed_ground_truth/review_queue.json', dp._stage_json(exportdir, 'review_queue.json'))
            dp._write_json(build / 'sealed_ground_truth/stage_manifests.json', {name: dp._load_input_stage(work, inputs, name)[1]
                for name in ('source', 'roi', 'subvideo', 'review_export', 'review_import')})
            dp._write_json(build / 'payload/quality_report.json', {'schema': 'tensile-data/holdout-quality/v1',
                'passed': True, 'review_complete': True, 'source_isolation_verified': True})
            for path in (build / 'sealed_ground_truth').rglob('*'):
                path.chmod(0o600 if path.is_file() else 0o700)
            dp._write_json(build / 'build_receipt.json', {'schema': 'tensile-data/holdout-build-receipt/v1',
                'version': version, 'binding': binding, 'review_sha256': review_sha, 'inventory': _inventory(build)})
            stage_release(data, build.relative_to(data / 'working').as_posix(), parsed.protocol, version=version)
    seal_release(data, version, purpose='holdout', description=f'{inputs.batch} test 数据分支',
                 sample_count=len(rows), source_batches=[inputs.batch],
                 splits={'holdout': {'train': 0, 'validation': len(rows)}})
    return _validate_release(root, version, binding)


def run_holdout_stage(root, stage, *, inputs_path, batch, config_path, version=None, results_path=None):
    """Seven-stage test branch under an owner-only, config-bound workspace."""
    if stage not in dp.STAGES:
        raise dp.UnknownStageError(stage)
    if stage in {'release', 'release_validate'}:
        parse_data_id(version)
    inputs, config, binding = load_config(root, inputs_path, batch, config_path)
    if stage == 'release_validate':
        return _validate_release(root, version, binding)
    work = _workspace(root, batch)
    with os.fdopen(os.open(work / '.branch.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if load_config(root, inputs_path, batch, config_path)[2] != binding:
            raise dp.StageInputError('test 配置在锁等待期间漂移')
        marker = work / 'binding.json'
        if marker.exists():
            if _json(marker) != binding:
                raise dp.StageInputError('test 工作区已绑定另一输入或隔离配置')
        else:
            with tempfile.NamedTemporaryFile(dir=work, prefix='.binding-', mode='w', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(binding, stream, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
            try:
                os.link(temporary, marker)
            finally:
                temporary.unlink()
        kwargs = dict(inputs_path=inputs_path, batch=batch)
        if stage == 'review_export':
            result = dp.run_input_review_export(work, **kwargs, scope='test_audit')
            result.outputs[0].chmod(0o700)
        elif stage == 'review_import':
            if results_path is None or _ordinary_path(results_path).stat().st_mode & 0o077:
                raise dp.ReviewGateError('test 回收文件必须为 owner-only')
            result = dp.run_input_review_import(work, **kwargs, results_path=results_path)
        elif stage in {'release', 'release_validate'}:
            data = Path(root) / 'data'
            with os.fdopen(os.open(data / f'.{version}.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'a+') as release_lock:
                fcntl.flock(release_lock.fileno(), fcntl.LOCK_EX)
                if load_config(root, inputs_path, batch, config_path)[2] != binding:
                    raise dp.StageInputError('test 发布等待期间配置漂移')
                result = (_release(root, work, inputs, config, binding, version) if stage == 'release'
                          else _validate_release(root, version, binding))
        else:
            result = dp.run_stage(work, stage, **kwargs)
        if load_config(root, inputs_path, batch, config_path)[2] != binding:
            raise dp.StageInputError('test 执行期间配置漂移，停止后续阶段')
        # Never emit candidate labels/distributions through the public CLI report.
        return dp.StageResult(stage, result.outputs, {'stage': stage, 'passed': True})


def validate_public_build(release):
    """Verify test-builder public commitment without opening restricted truth."""
    release = _ordinary_path(release)
    receipt = _json(release / 'build_receipt.json')
    if (receipt.get('schema') != 'tensile-data/holdout-build-receipt/v1'
            or receipt.get('version') != release.name):
        raise dp.StageInputError('test 构建凭证缺失或身份不符')
    for name in ('media', 'evaluation_inputs', 'payload'):
        if receipt['inventory'][name] != dp._stage_inventory(release / name, exclude_manifest=False):
            raise dp.StageInputError('test 公开媒体或证据漂移')
    manifest = _json(release / 'evaluation_inputs/manifest.json')
    binding = receipt['binding']
    if (manifest['development_data_version'] != binding['development_data_version']
            or not {r['source_video'] for r in manifest['samples']} <= set(binding['source_sha256'])):
        raise dp.StageInputError('test manifest 未绑定构建 source')
    return dp._sha256_file(release / 'build_receipt.json')
