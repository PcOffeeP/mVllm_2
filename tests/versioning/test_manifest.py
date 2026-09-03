"""B7b — 四段聚合 manifest：data/prompt/train/eval 单向导出证据文件与发布门。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md（任务卡
引用 §7.3 四段 manifest / §5.7 单向导出 / §11.2 manifest 是证据文件+发布门；
现行设计文档无 §7.3/§5.7 编号，按内容对应实体为）：
§2.6（manifest 是由 MLflow 单向导出的只读快照，经 Git 跨设备同步；事实字段
封存后不得原地改写；允许的重导只限三类更正策略——导出器错误可同语义幂等
重导；record_validity 权威位置是 MLflow tags；invalid 必须被下游拒绝）、
§2.12 + D029（记录流向固定为 Git/YAML + DVC 定义输入 → 训练机实际运行 →
MLflow 完整记录 → 导出只读 manifest → Git 跨设备同步，不反向写回、不建立
双向同步）、§11.2（训练/模型/测评只有在 MLflow 中满足各自完成条件后才可
导出正式 manifest；部分移动、缺文件或不完整 Run 不能被活动入口读取——
manifest 是证据文件 + 发布门）、§13.1（MLflow → manifest 导出包含最小
字段、结果可重复生成、同名冲突阻断、非完成 Run 不导出、人工修改被检测）、
§3.1/§3.3（五类可读完整 ID、显式引用不自动猜测）、§5.1（data
release.yaml 身份/purpose/training_allowed/status）、§5.2（正式 prompt
文件只增不改）、§5.3 + §2.7（train workflow_state 与 fold0-2 三折）、§5.5
（eval scope=single_fold/cross_validation/full 与 outcome）、§8（正式对象
只增不改、payload 只读验证）、§10（invalid 被下游拒绝、superseded 保留
历史证据、train 行下游门 valid + completed|archived 且子 Run 完整）；
实施台账 B7（versioning/manifest.py：train/eval manifest 最小字段、只能从
MLflow 单向导出、幂等重导；B7b 任务契约四段聚合）。

预期 production API（供 writer 对照实现，模块 ``versioning.manifest``）::

    # ——— 常量 ———
    MANIFEST_VERSION: str = "1"
        # 输出 JSON 顶层 manifest_version 字段的固定值（字符串）。

    # ——— 异常（基类 ManifestError(ValueError)）———
    class ManifestError(ValueError)
        # manifest 域异常基类
    class ManifestReferenceError(ManifestError)
        # fail-closed 引用门：引用的已冻结记录不存在 / 未封存 / train 未完成
        # / record_validity=invalid / 状态不允许 / 链路不一致 / eval 冻结视图
        # 值域非法。上游域异常（ReleaseNotFound、ReleaseSchemaError、
        # ImmutableReleaseError、PromptNotFound、PromptSchemaError、
        # TrainRecordNotFound、IncompleteTrainRecord、InvalidTrainRecord 等）
        # 一律包装为本异常（异常链保留）。
    class ManifestSchemaError(ManifestError)
        # 校验函数拒绝：非 str 或非法 JSON 文本、顶层/段键集合不符、缺字段、
        # 未知字段、值域或跨段一致性非法（§13.1 人工修改被检测）；不得让
        # json/类型异常泄漏。
    class ManifestConflict(ManifestError)
        # export_manifest 目标已存在且字节不同于本次 payload（§2.6 事实
        # 字段封存后不得原地改写；字节相同视为幂等重导，正常放行）。

    # ——— 四段已冻结记录引用输入（frozen dataclass）———
    @dataclass(frozen=True)
    class DataRecordRef
        root: Path        # 项目根：root/releases/<version>/release.yaml
        version: str      # data-v<协议>-r<N> 完整 ID（§3.3 显式引用）
    @dataclass(frozen=True)
    class PromptRecordRef
        root: Path        # 项目根：root/records/prompts/<version>.yaml
        version: str
    @dataclass(frozen=True)
    class TrainRecordRef
        store: TrainRecordStore    # versioning.mlflow_train 的 store 句柄
        train_id: str
    @dataclass(frozen=True)
    class EvalRecordRef
        # 正式 eval 记录的已冻结视图（值对象）。B7 并行模块
        # versioning.mlflow_eval 持有 eval Run 权威（fold 绑定、holdout 鉴权）；
        # 本模块不 import 它，只接收其冻结结果并做值域与链路 fail-closed。
        eval_id: str               # eval-v<协议>-r<N>
        model_version: str         # 被测模型 model-v<协议>-r<N>
        source_train: str          # 来源训练 train-v<协议>-r<N>
        data_version: str          # 测评数据 data-v<协议>-r<N>
        scope: str                 # "single_fold" | "cross_validation" | "full"
        folds: tuple[int, ...]     # 与 scope 匹配的 fold 集合（bool/字符串/
                                   # 越界/重复一律拒绝）
        outcome: str               # "passed" | "failed"
        result_refs: Mapping[str, str]   # 结果引用（角色→路径），非空
        record_validity: str       # "valid" | "invalid"（invalid 拒绝，§10）

    # ——— 聚合与单向导出 ———
    def build_manifest(*, data: DataRecordRef, prompt: PromptRecordRef,
                       train: TrainRecordRef, eval: EvalRecordRef) -> str
        # 四段聚合并确定性序列化为 JSON 文本（§13.1"结果可重复生成"：字段
        # 排序、无时间戳，同一组输入字节级可复现；输入容器顺序不得影响
        # 字节）。四个参数均必填（keyword-only）。
        # fail-closed 校验顺序钉死：(1) 全部 ref 的全部 ID 字段先经
        # versioning.ids 对应 parse_* 显式解析（非法 ->
        # versioning.ids.InvalidIdentifier，且先于任何 store/文件系统访问——
        # 纯输入校验先行）；随后按清单顺序执行引用门：
        # (2) data 引用：versioning.data_release.load_release_metadata 解析
        #     （不存在 / 未封存 / schema 非法 -> ManifestReferenceError）；
        #     purpose 必须为 "development" 且 training_allowed 为真（§5.1
        #     训练链数据源语义）；status ∈ {active, superseded}（invalid
        #     拒绝；superseded 仍是历史训练证据，§10 data 行）；
        #     assert_payload_sealed 通过（payload 只读，§8）；
        # (3) prompt 引用：versioning.prompts.load_prompt 解析（不存在 /
        #     schema 非法 -> ManifestReferenceError）；
        # (4) train 引用：versioning.mlflow_train.get_train_run 解析（不
        #     存在 -> ManifestReferenceError）；record_validity == "valid"
        #     且 workflow_state ∈ {completed, archived}（非完成 Run 不导出，
        #     §11.2/§13.1；§10 train 行下游门）；
        # (5) 链路一致性：train.data_version == data.version 且
        #     train.prompt_version == prompt.version（MLflow tags 权威）；
        # (6) eval 视图：record_validity == "valid"；scope ∈ 三值；folds 元素
        #     为 {0,1,2} 内真 int、无重复，集合与 scope 匹配
        #     （cross_validation 恰为 {0,1,2}；single_fold 恰单元素；full
        #     空集）；outcome ∈ {passed, failed}；result_refs 为非空
        #     Mapping 且键、值均为非空字符串；eval.source_train ==
        #     train.train_id；任一不符 -> ManifestReferenceError。
        # 输出 JSON 顶层键集合恰为 {"manifest_version", "data", "prompt",
        # "train", "eval"}（manifest_version == MANIFEST_VERSION），各段键
        # 集合恰为：
        #   data:  {"version", "source_batches", "release_digest",
        #           "seal_evidence"}
        #     source_batches = release.yaml 的来源批次（顺序保留）；
        #     release_digest = 封存证据文件 release.yaml 字节的 SHA-256
        #                      十六进制（小写 64 位）；
        #     seal_evidence  = "release.yaml"（封存证据文件指针）。
        #   prompt: {"version", "source_hash", "variables"}
        #     source_hash = 正式 prompt 文件字节的 SHA-256 十六进制；
        #     variables   = output_fields（顺序保留、唯一、非空）。
        #   train: {"train_id", "folds", "state", "run_id"}
        #     folds = 升序 [0, 1, 2]（completed 门保证三折完整）；
        #     state = workflow_state 值；run_id = MLflow 父 Run ID
        #     （§2.6"完整记录在哪里"）。
        #   eval:  {"eval_id", "model_version", "source_train", "data_version",
        #           "scope", "folds", "outcome", "result_refs"}
        #     folds = 升序整数列表；result_refs = 角色→路径映射。
        # 序列化钉死 canonical：json.dumps(obj, sort_keys=True,
        # separators=(",", ":"))，无尾随换行，无时间戳等动态字段。

    def validate_manifest(payload: str) -> dict
        # 校验函数（§13.1 人工修改被检测）：重解析输出 JSON 文本，校验字段
        # 完整与值域，通过则返回解析后的 mapping。
        # - payload 非 str（None/bytes/其他）或非法 JSON 文本、顶层非
        #   object -> ManifestSchemaError（不泄漏 json/类型异常）；
        # - 顶层与各段键集合必须恰为钉死集合（缺键拒绝、未知键拒绝）；
        # - manifest_version 必须为字符串 "1"；
        # - 五类 ID 字段逐一经 versioning.ids 对应 parse 校验（data.version /
        #   prompt.version / train.train_id / eval.eval_id /
        #   eval.model_version / eval.source_train / eval.data_version）；
        # - 值域：source_batches 非空且元素为非空字符串；release_digest /
        #   source_hash 为小写 64 位十六进制；seal_evidence ==
        #   "release.yaml"；variables 非空、无重复、元素非空字符串；
        #   train.folds == [0, 1, 2]；train.state ∈ {completed, archived}；
        #   run_id 非空字符串；eval.scope ∈ {single_fold, cross_validation,
        #   full} 且 folds 升序、无重复、元素 ∈ {0,1,2}、集合与 scope 匹配；
        #   outcome ∈ {passed, failed}；result_refs 非空 object 且键、值均
        #   为非空字符串；
        # - 跨段一致性：eval.source_train == train.train_id；
        # - 校验是语义级：字节布局（键序/空白）不在校验范围，语义相同的重排
        #   JSON 应通过。

    def export_manifest(target: Path, *, data: DataRecordRef,
                        prompt: PromptRecordRef, train: TrainRecordRef,
                        eval: EvalRecordRef) -> Path
        # 单向导出落盘（§2.12 单向记录流；不反向写回任何 store）：
        # - 以 build_manifest 同参数产出 payload 并写入 target（缺失父目录
        #   自动创建；文件字节 == payload）；
        # - target 已存在且字节 == 本次 payload：幂等重导，正常返回（§2.6
        #   更正策略允许的导出器幂等重导）；
        # - target 已存在且字节不同：抛 ManifestConflict，target 原样不动
        #   （§2.6 事实字段封存后不得原地改写）；
        # - 返回 target 路径。
        # 生成与校验不得反向修改任何 versioning 对象（任务卡 §5.7 单向导出）：
        # data release.yaml 字节与 payload 权限位、prompt 文件、MLflow Run
        # tags/params/metrics/状态与 Run 数量一律不变。

语义决策点（测试侧钉定，供实现对照）：
    1. 四段 = 一次完整训练血缘的证据文件：data（训练数据 release）+ prompt
       （训练 prompt）+ train（MLflow 训练父 Run）+ eval（对由该 train 产出
       的模型的一次正式测评的冻结视图）。设计 §2.6 的按对象 manifest
       （train/model/eval）由四段分工承担；model manifest 本身属 B8，不在
       本批。
    2. eval 段输入是值对象（不接 store）：与并行模块 versioning.mlflow_eval
       解耦（避免 import 循环与并行耦合）；eval Run 的权威校验（fold 绑定、
       holdout 鉴权）属 test_mlflow_eval.py 范围，本模块只做值域与链路门。
    3. 五类 ID 非法 -> 直接传播 versioning.ids.InvalidIdentifier（与
       data_release / prompts / mlflow_train 现有风格一致）；存在性/封存/
       完成/有效性与一致性失败 -> ManifestReferenceError（包装上游域异常）。
       全部 ID 字段的解析先于任何 store 访问（纯输入校验先行）。
    4. data 段 hash/digest 取封存证据文件 release.yaml 字节的 SHA-256：
       payload 完整性归 DVC 内部能力（§2.1），manifest 是轻量证据文件、不
       复制大型产物（§2.6"不包含"列）；封存证据 gate 为 release.yaml 的
       sealed schema 加 assert_payload_sealed 只读验证（§8）。
    5. data 发布门收窄为训练链数据源：purpose 必须 development 且
       training_allowed 为真（§5.1）；status 允许 active|superseded
       （superseded 仍可作历史训练证据，§10 data 行），invalid 拒绝。
    6. train 段输出保持任务契约最小字段（train_id/folds/state/run_id）；
       train→data/prompt 绑定在 build 时以 MLflow tags 为权威校验（不重复
       写入输出）；validator 只能复核 JSON 内可见的 eval.source_train ==
       train.train_id。
    7. eval.data_version 是测评自身数据（可与训练数据不同，例如 holdout
       验收数据），不做与 data 段相等的跨段校验；model_version 仅做 ID
       显式解析（模型注册表属 B8，本批无法验证存在性）；record_validity
       只接受 "valid"（§10 invalid 被下游拒绝）。
    8. 输出不含 record_validity 与时间戳字段：build 门只放行 valid 记录，
       manifest 即导出时有效性的断言；§2.6 invalid 更正重导路径属后续
       批次（实施台账 B7 三类更正路径由 mlflow_eval 与后续批次分担）。
    9. 输出 schema 严格（顶层与各段键集合钉死、未知键拒绝）：证据文件的
       防篡改边界；validator 语义级放行同义重排 JSON，字节 canonical 形态
       只约束 build_manifest 输出。
   10. result_refs 只做非空与键/值非空字符串的结构校验：逐 fold 绑定
       （模型 artifact ↔ 数据 split ↔ 结果路径）的强校验属 mlflow_eval
       权威范围，本模块不重复。

测试环境：真实文件系统 + 真实 MLflow 集成（非 mock）；全部目录与 store
在 pytest ``tmp_path`` / ``tmp_path_factory`` 会话临时目录内（只读共享链也是
pytest 临时目录；SQLite + 本地 artifact store），不启动服务、不连接任何正式
store、无网络访问。

当前 ``versioning/manifest.py`` 尚不存在，本文件全部用例应为 RED
（collection error：ModuleNotFoundError / ImportError）。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest
from mlflow.tracking import MlflowClient

from versioning.manifest import (
    MANIFEST_VERSION,
    DataRecordRef,
    EvalRecordRef,
    ManifestConflict,
    ManifestError,
    ManifestReferenceError,
    ManifestSchemaError,
    PromptRecordRef,
    TrainRecordRef,
    build_manifest,
    export_manifest,
    validate_manifest,
)

from versioning.data_release import seal_release, stage_release, update_release_status
from versioning.ids import InvalidIdentifier
from versioning.mlflow_train import (
    DATA_VERSION_TAG,
    REQUIRED_FOLDS,
    TrainRecordStore,
    TrainRunRecord,
    WORKFLOW_STATE_TAG,
    create_fold_run,
    create_train_run,
    end_fold_run,
    get_train_run,
    log_fold_metrics,
    log_train_summary,
    mark_train_invalid,
    open_train_store,
    transition_train_state,
)
from versioning.prompts import create_prompt, prompt_path
from versioning.state import IllegalStateCombination

PROTOCOL = "v4.1"
PROTOCOL_LABEL = f"tensile-vlm/{PROTOCOL}"

DATA_VERSION = "data-v4.1-r1"
DATA_VERSION_ALT = "data-v4.1-r2"
DATA_VERSION_UNKNOWN = "data-v4.1-r9"
PROMPT_VERSION = "prompt-v4.1-r1"
PROMPT_VERSION_ALT = "prompt-v4.1-r2"
PROMPT_VERSION_UNKNOWN = "prompt-v4.1-r9"
TRAIN_ID = "train-v4.1-r1"
TRAIN_ID_ALT = "train-v4.1-r2"
TRAIN_ID_UNKNOWN = "train-v4.1-r9"
EVAL_ID = "eval-v4.1-r1"
EVAL_ID_ALT = "eval-v4.1-r2"
MODEL_VERSION = "model-v4.1-r1"
MODEL_VERSION_ALT = "model-v4.1-r2"

GIT_COMMIT = "a1b2c3d"
BASE_MODEL = "MiniCPM-V-4.5"
SOURCE_BATCHES = ("batch-2026-07",)
SOURCE_BATCHES_ALT = ("batch-2026-08",)
OUTPUT_FIELDS = ("clip_state", "fracture_mechanism", "fracture_site", "special_case")
SPLITS = {
    "fold0": {"train": 1253, "validation": 425},
    "fold1": {"train": 1014, "validation": 664},
    "fold2": {"train": 1186, "validation": 492},
}
TRAIN_CONFIG = {"epochs": 3, "lora_rank": 16, "seed": 42}
FOLD_METRICS = {
    0: {"fold_f1": 0.81, "fold_loss": 0.42},
    1: {"fold_f1": 0.79, "fold_loss": 0.45},
    2: {"fold_f1": 0.80, "fold_loss": 0.44},
}
SUMMARY_METRICS = {"cv_f1_mean": 0.8, "cv_f1_std": 0.01}
RESULT_REFS = {
    "aggregate": "aggregate/summary.json",
    "fold0": "folds/fold0/records.jsonl",
    "fold1": "folds/fold1/records.jsonl",
    "fold2": "folds/fold2/records.jsonl",
}
EVAL_SCOPE = "cross_validation"
EVAL_OUTCOME = "passed"
RECORD_VALIDITY_VALID = "valid"

EXPECTED_TOP_KEYS = {"manifest_version", "data", "prompt", "train", "eval"}
EXPECTED_SEGMENT_KEYS = {
    "data": {"version", "source_batches", "release_digest", "seal_evidence"},
    "prompt": {"version", "source_hash", "variables"},
    "train": {"train_id", "folds", "state", "run_id"},
    "eval": {
        "eval_id",
        "model_version",
        "source_train",
        "data_version",
        "scope",
        "folds",
        "outcome",
        "result_refs",
    },
}

# 五类 ID 的非法样本（对每个 kind 都非法）：latest / 缺 rN / r0 / 前导零 /
# 空串 / 非字符串。
BAD_IDS = ["latest", "data-v4.1", "data-v4.1-r0", "data-v4.1-r01", "", None, 41]

# (字段路径, ref 元组下标, dataclass 属性名)——七个 ID 字段覆盖五类 ID。
_ID_FIELD_SPECS = (
    ("data.version", 0, "version"),
    ("prompt.version", 1, "version"),
    ("train.train_id", 2, "train_id"),
    ("eval.eval_id", 3, "eval_id"),
    ("eval.model_version", 3, "model_version"),
    ("eval.source_train", 3, "source_train"),
    ("eval.data_version", 3, "data_version"),
)

# 合法但跨类别的 ID：kind 解析器必须拒绝。
_WRONG_KIND_IDS = (
    ("data.version", 0, "version", "train-v4.1-r1"),
    ("prompt.version", 1, "version", "data-v4.1-r1"),
    ("train.train_id", 2, "train_id", "eval-v4.1-r1"),
    ("eval.eval_id", 3, "eval_id", "model-v4.1-r1"),
    ("eval.model_version", 3, "model_version", "eval-v4.1-r1"),
    ("eval.source_train", 3, "source_train", "prompt-v4.1-r1"),
    ("eval.data_version", 3, "data_version", "train-v4.1-r1"),
)

# (段, 字段) 全枚举：validator 缺字段负向用例。
_ALL_SEGMENT_FIELDS = (
    ("data", "version"),
    ("data", "source_batches"),
    ("data", "release_digest"),
    ("data", "seal_evidence"),
    ("prompt", "version"),
    ("prompt", "source_hash"),
    ("prompt", "variables"),
    ("train", "train_id"),
    ("train", "folds"),
    ("train", "state"),
    ("train", "run_id"),
    ("eval", "eval_id"),
    ("eval", "model_version"),
    ("eval", "source_train"),
    ("eval", "data_version"),
    ("eval", "scope"),
    ("eval", "folds"),
    ("eval", "outcome"),
    ("eval", "result_refs"),
)

# 非法 eval 冻结视图样本（字段 -> 替换值）。
_EVAL_REF_OVERRIDES = (
    ("record_validity_invalid", {"record_validity": "invalid"}),
    ("record_validity_bogus", {"record_validity": "bogus"}),
    ("scope_bogus", {"scope": "bogus"}),
    ("scope_none", {"scope": None}),
    ("outcome_bogus", {"outcome": "maybe"}),
    ("outcome_empty", {"outcome": ""}),
    ("folds_none", {"folds": None}),
    ("folds_subset_for_cross_validation", {"folds": (0, 1)}),
    ("folds_extra_out_of_domain", {"folds": (0, 1, 2, 3)}),
    ("folds_duplicate", {"folds": (0, 1, 1, 2)}),
    ("folds_string_element", {"folds": ("0", 1, 2)}),
    ("folds_bool_element", {"folds": (True, 1, 2)}),
    ("single_fold_with_two_folds", {"scope": "single_fold", "folds": (0, 1)}),
    ("single_fold_out_of_domain", {"scope": "single_fold", "folds": (5,)}),
    ("full_with_folds", {"scope": "full", "folds": (0,)}),
    ("result_refs_empty", {"result_refs": {}}),
    ("result_refs_none", {"result_refs": None}),
    ("result_refs_empty_key", {"result_refs": {"": "aggregate/summary.json"}}),
    ("result_refs_empty_value", {"result_refs": {"aggregate": ""}}),
    ("result_refs_non_str_value", {"result_refs": {"aggregate": 1}}),
)

# manifest_version 非法变体（validator 篡改负向）。
_BAD_MANIFEST_VERSIONS = (
    ("missing", lambda obj: obj.pop("manifest_version")),
    ("string_2", lambda obj: obj.__setitem__("manifest_version", "2")),
    ("int_1", lambda obj: obj.__setitem__("manifest_version", 1)),
    ("version_1_0", lambda obj: obj.__setitem__("manifest_version", "1.0")),
    ("none", lambda obj: obj.__setitem__("manifest_version", None)),
)

# 段内字段值域篡改样本（validator 负向；构造同义 canonical 文本后送校验）。
_DOMAIN_TAMPERS = (
    ("data_version_illegal_id", lambda o: o["data"].__setitem__("version", "data-latest")),
    ("data_version_wrong_kind", lambda o: o["data"].__setitem__("version", "train-v4.1-r1")),
    ("data_source_batches_empty", lambda o: o["data"].__setitem__("source_batches", [])),
    ("data_source_batches_non_str", lambda o: o["data"].__setitem__("source_batches", ["ok", 41])),
    ("data_source_batches_empty_item", lambda o: o["data"].__setitem__("source_batches", [""])),
    ("data_release_digest_not_hex", lambda o: o["data"].__setitem__("release_digest", "zz" * 32)),
    ("data_release_digest_uppercase", lambda o: o["data"].__setitem__("release_digest", "A" * 64)),
    ("data_release_digest_short", lambda o: o["data"].__setitem__("release_digest", "abc")),
    ("data_seal_evidence_other_file", lambda o: o["data"].__setitem__("seal_evidence", "README.md")),
    ("prompt_version_wrong_kind", lambda o: o["prompt"].__setitem__("version", "data-v4.1-r1")),
    ("prompt_source_hash_not_hex", lambda o: o["prompt"].__setitem__("source_hash", "not-a-digest")),
    ("prompt_variables_empty", lambda o: o["prompt"].__setitem__("variables", [])),
    ("prompt_variables_duplicate", lambda o: o["prompt"].__setitem__("variables", ["clip_state", "clip_state"])),
    ("prompt_variables_empty_item", lambda o: o["prompt"].__setitem__("variables", [""])),
    ("train_id_illegal", lambda o: o["train"].__setitem__("train_id", "train-v4.1-r0")),
    ("train_folds_missing_fold", lambda o: o["train"].__setitem__("folds", [0, 1])),
    ("train_folds_extra_fold", lambda o: o["train"].__setitem__("folds", [0, 1, 2, 3])),
    ("train_state_incomplete", lambda o: o["train"].__setitem__("state", "running")),
    ("train_run_id_empty", lambda o: o["train"].__setitem__("run_id", "")),
    ("eval_id_illegal", lambda o: o["eval"].__setitem__("eval_id", "eval-v4.1")),
    ("eval_model_version_wrong_kind", lambda o: o["eval"].__setitem__("model_version", "eval-v4.1-r1")),
    ("eval_source_train_illegal", lambda o: o["eval"].__setitem__("source_train", "latest")),
    ("eval_data_version_leading_zero", lambda o: o["eval"].__setitem__("data_version", "data-v4.1-r01")),
    ("eval_scope_unknown", lambda o: o["eval"].__setitem__("scope", "bogus")),
    ("eval_scope_full_with_folds", lambda o: o["eval"].__setitem__("scope", "full")),
    ("eval_scope_single_with_three_folds", lambda o: o["eval"].__setitem__("scope", "single_fold")),
    ("eval_folds_missing_fold", lambda o: o["eval"].__setitem__("folds", [0, 1])),
    ("eval_folds_unsorted", lambda o: o["eval"].__setitem__("folds", [2, 1, 0])),
    ("eval_folds_out_of_domain", lambda o: o["eval"].__setitem__("folds", [0, 1, 3])),
    ("eval_folds_bool_element", lambda o: o["eval"].__setitem__("folds", [True, 1, 2])),
    ("eval_folds_empty_for_cross_validation", lambda o: o["eval"].__setitem__("folds", [])),
    ("eval_outcome_unknown", lambda o: o["eval"].__setitem__("outcome", "maybe")),
    ("eval_result_refs_empty", lambda o: o["eval"].__setitem__("result_refs", {})),
    ("eval_result_refs_empty_key", lambda o: o["eval"].__setitem__("result_refs", {"": "folds/fold0/records.jsonl"})),
    ("eval_result_refs_empty_value", lambda o: o["eval"].__setitem__("result_refs", {"aggregate": ""})),
    ("eval_result_refs_non_str_value", lambda o: o["eval"].__setitem__("result_refs", {"aggregate": 1})),
    ("eval_result_refs_list", lambda o: o["eval"].__setitem__("result_refs", ["aggregate/summary.json"])),
)

# raw 篡改 workflow_state 的取值（B7b 修复回归）：均为合法 WorkflowState 值，
# 但与已 completed 父 Run 的原生 FINISHED 构成 §5.3 固定组合表外的非法组合；
# "archived"/"completed" 与 FINISHED 组合合法，不得混入。
_RAW_ILLEGAL_COMBINATION_STATES = ("running", "partial", "failed", "prepared")

# 伪摘要样本（B7b 修复回归，_is_lowercase_hex 严格整串匹配）：长度恰为 64、
# 可骗过宽松实现（int(x,16) 接受 0x 前缀/负号/下划线分隔）但字符级非法。
_LEN64_HEX_LOOKALIKES = (
    ("hex_0x_prefix", "0x" + "a" * 62),
    ("minus_sign_prefix", "-" + "a" * 63),
    ("underscore_separator", "a" * 32 + "_" + "a" * 31),
)

# 64 位小写十六进制字段的 (段, 字段) 定位表：data.release_digest 与
# prompt.source_hash。
_HEX_DIGEST_FIELDS = (
    ("data", "release_digest"),
    ("prompt", "source_hash"),
)


# —————————————————— helpers 与 fixtures ——————————————————


@dataclass(frozen=True)
class _Chain:
    """测试侧组装的一条完整血缘链（非模块契约）。"""

    root: Path
    store: TrainRecordStore
    release_dir: Path
    prompt_path: Path
    data_ref: DataRecordRef
    prompt_ref: PromptRecordRef
    train_ref: TrainRecordRef
    eval_ref: EvalRecordRef


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_working(root: Path, name: str) -> Path:
    """构造带 payload 文件的 working 目录（与 test_data_release 同形）。"""
    working = root / "working" / name
    (working / "datasets").mkdir(parents=True)
    (working / "datasets" / "labels.jsonl").write_text(
        '{"id": 1}\n', encoding="utf-8"
    )
    (working / "media").mkdir()
    (working / "media" / "clip.mp4").write_bytes(b"\x00\x01")
    return working


def _seal_data(root: Path, version: str = DATA_VERSION, **overrides: object) -> Path:
    """working → release_staging → sealed（显式版本纪律）；返回正式 release 目录。"""
    working_name = f"round-{version}"
    _make_working(root, working_name)
    kwargs: dict = {
        "purpose": "development",
        "description": "sealed development training data",
        "sample_count": 2,
        "source_batches": list(SOURCE_BATCHES),
        "splits": {fold: dict(parts) for fold, parts in SPLITS.items()},
    }
    kwargs.update(overrides)
    stage_release(root, working_name, PROTOCOL, version=version)
    return seal_release(root, version, **kwargs)


def _register_prompt(
    root: Path,
    version: str = PROMPT_VERSION,
    *,
    system_prompt: str = "You are a tensile test video analysis assistant.",
    user_prompt: str = "Report the clip state and fracture evidence.",
) -> Path:
    create_prompt(
        root,
        PROTOCOL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        output_fields=list(OUTPUT_FIELDS),
        protocol_label=PROTOCOL_LABEL,
        version=version,
    )
    return prompt_path(root, version)


def _complete_training(
    store: TrainRecordStore,
    train_id: str = TRAIN_ID,
    *,
    data_version: str = DATA_VERSION,
    prompt_version: str = PROMPT_VERSION,
) -> TrainRunRecord:
    """合法完成路径：父 Run + 三折 FINISHED + 汇总 + completed。"""
    create_train_run(
        store,
        train_id,
        data_version=data_version,
        prompt_version=prompt_version,
        git_commit=GIT_COMMIT,
        base_model=BASE_MODEL,
        config=dict(TRAIN_CONFIG),
    )
    for fold in REQUIRED_FOLDS:
        create_fold_run(store, train_id, fold)
        log_fold_metrics(store, train_id, fold, dict(FOLD_METRICS[fold]))
        end_fold_run(store, train_id, fold, "FINISHED")
    log_train_summary(store, train_id, dict(SUMMARY_METRICS))
    return transition_train_state(store, train_id, "completed")


def _eval_ref(**overrides: object) -> EvalRecordRef:
    """默认合法的 eval 冻结视图；overrides 供负向用例逐字段替换。"""
    fields: dict = {
        "eval_id": EVAL_ID,
        "model_version": MODEL_VERSION,
        "source_train": TRAIN_ID,
        "data_version": DATA_VERSION,
        "scope": EVAL_SCOPE,
        "folds": (0, 1, 2),
        "outcome": EVAL_OUTCOME,
        "result_refs": dict(RESULT_REFS),
        "record_validity": RECORD_VALIDITY_VALID,
    }
    fields.update(overrides)
    return EvalRecordRef(**fields)


def _make_chain(base: Path) -> _Chain:
    """在 base 下组装完整血缘链：sealed data + 正式 prompt + completed train。"""
    root = base / "proj"
    root.mkdir(parents=True, exist_ok=True)
    release_dir = _seal_data(root, DATA_VERSION)
    prompt_file = _register_prompt(root, PROMPT_VERSION)
    store = open_train_store(base / "mlflow")
    _complete_training(store, TRAIN_ID)
    return _Chain(
        root=root,
        store=store,
        release_dir=release_dir,
        prompt_path=prompt_file,
        data_ref=DataRecordRef(root=root, version=DATA_VERSION),
        prompt_ref=PromptRecordRef(root=root, version=PROMPT_VERSION),
        train_ref=TrainRecordRef(store=store, train_id=TRAIN_ID),
        eval_ref=_eval_ref(),
    )


def _build(
    chain: _Chain,
    *,
    data_ref: DataRecordRef | None = None,
    prompt_ref: PromptRecordRef | None = None,
    train_ref: TrainRecordRef | None = None,
    eval_ref: EvalRecordRef | None = None,
) -> str:
    return build_manifest(
        data=data_ref or chain.data_ref,
        prompt=prompt_ref or chain.prompt_ref,
        train=train_ref or chain.train_ref,
        eval=eval_ref or chain.eval_ref,
    )


def _export(target: Path, chain: _Chain, *, eval_ref: EvalRecordRef | None = None) -> Path:
    return export_manifest(
        target,
        data=chain.data_ref,
        prompt=chain.prompt_ref,
        train=chain.train_ref,
        eval=eval_ref or chain.eval_ref,
    )


def _bare_refs(
    tmp_path: Path,
) -> tuple[DataRecordRef, PromptRecordRef, TrainRecordRef, EvalRecordRef]:
    """T2 专用轻量引用组：空项目根 + 空 store（ID 解析门是纯输入校验）。"""
    store = open_train_store(tmp_path / "store")
    return (
        DataRecordRef(root=tmp_path / "proj", version=DATA_VERSION),
        PromptRecordRef(root=tmp_path / "proj", version=PROMPT_VERSION),
        TrainRecordRef(store=store, train_id=TRAIN_ID),
        _eval_ref(),
    )


def _build_refs(
    refs: tuple[DataRecordRef, PromptRecordRef, TrainRecordRef, EvalRecordRef],
) -> str:
    data_ref, prompt_ref, train_ref, eval_ref = refs
    return build_manifest(
        data=data_ref, prompt=prompt_ref, train=train_ref, eval=eval_ref
    )


def _release_snapshot(release_dir: Path) -> tuple:
    """data release 只读快照：release.yaml 字节 + 全目录权限位。"""
    yaml_bytes = (release_dir / "release.yaml").read_bytes()
    root_mode = release_dir.stat().st_mode
    entries = tuple(
        sorted(
            (entry.relative_to(release_dir).as_posix(), entry.stat().st_mode)
            for entry in release_dir.rglob("*")
        )
    )
    return (yaml_bytes, root_mode, entries)


def _store_snapshot(store: TrainRecordStore) -> tuple:
    """MLflow store 逻辑快照（raw 客户端读回：Run 数、状态、tags、参数、指标）。"""
    client = MlflowClient(tracking_uri=store.tracking_uri)
    runs = list(client.search_runs([store.experiment_id], max_results=100))
    return tuple(
        sorted(
            (
                run.info.run_id,
                run.info.status,
                tuple(sorted(run.data.tags.items())),
                tuple(sorted(run.data.params.items())),
                tuple(sorted(run.data.metrics.items())),
            )
            for run in runs
        )
    )


def _tampered(payload: str, mutate: Callable[[dict], None]) -> str:
    """重解析 payload、施加篡改、再以 canonical 形态回写文本。"""
    obj = json.loads(payload)
    mutate(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _second_chain(chain: _Chain) -> _Chain:
    """同一 tmp 环境内的第二条完整链（不同版本与内容；冲突用例用）。"""
    _seal_data(chain.root, DATA_VERSION_ALT, source_batches=list(SOURCE_BATCHES_ALT))
    _register_prompt(
        chain.root,
        PROMPT_VERSION_ALT,
        system_prompt="Alternate assistant system prompt.",
        user_prompt="Alternate user prompt.",
    )
    _complete_training(
        chain.store,
        TRAIN_ID_ALT,
        data_version=DATA_VERSION_ALT,
        prompt_version=PROMPT_VERSION_ALT,
    )
    return _Chain(
        root=chain.root,
        store=chain.store,
        release_dir=chain.root / "releases" / DATA_VERSION_ALT,
        prompt_path=prompt_path(chain.root, PROMPT_VERSION_ALT),
        data_ref=DataRecordRef(root=chain.root, version=DATA_VERSION_ALT),
        prompt_ref=PromptRecordRef(root=chain.root, version=PROMPT_VERSION_ALT),
        train_ref=TrainRecordRef(store=chain.store, train_id=TRAIN_ID_ALT),
        eval_ref=_eval_ref(
            eval_id=EVAL_ID_ALT,
            model_version=MODEL_VERSION_ALT,
            source_train=TRAIN_ID_ALT,
            data_version=DATA_VERSION_ALT,
            result_refs={"aggregate": "aggregate/summary.json"},
        ),
    )


@pytest.fixture()
def chain(tmp_path: Path) -> _Chain:
    """每用例独立 tmp 环境的完整血缘链。"""
    return _make_chain(tmp_path)


@pytest.fixture(scope="module")
def shared(tmp_path_factory: pytest.TempPathFactory) -> tuple[_Chain, str]:
    """模块级只读共享链及其 manifest（仍是 pytest 会话临时目录；T1/T5/T6 复用）。"""
    shared_chain = _make_chain(tmp_path_factory.mktemp("manifest-shared"))
    return shared_chain, _build(shared_chain)


# —————————————————— T1 聚合与字段正确性 ——————————————————


class TestBuildAggregation:
    """正向：四段聚合、顶层 manifest_version、各段字段与冻结记录一致。"""

    def test_exception_hierarchy_pins_domain_errors(self) -> None:
        # 契约钉定：域异常基类与三个子类（供 fail-closed 捕获面稳定）。
        for exc in (ManifestReferenceError, ManifestSchemaError, ManifestConflict):
            assert issubclass(exc, ManifestError)
        assert issubclass(ManifestError, ValueError)

    def test_build_requires_all_four_refs_keyword_only(self, shared) -> None:
        chain, _payload = shared
        with pytest.raises(TypeError):
            build_manifest(
                data=chain.data_ref, prompt=chain.prompt_ref, train=chain.train_ref
            )
        with pytest.raises(TypeError):
            build_manifest(
                chain.data_ref, chain.prompt_ref, chain.train_ref, chain.eval_ref
            )

    def test_output_top_level_is_manifest_version_plus_four_segments(
        self, shared
    ) -> None:
        _chain, payload = shared
        parsed = json.loads(payload)
        assert parsed["manifest_version"] == MANIFEST_VERSION == "1"
        assert set(parsed) == EXPECTED_TOP_KEYS
        for segment, keys in EXPECTED_SEGMENT_KEYS.items():
            assert set(parsed[segment]) == keys, segment

    def test_data_segment_reflects_sealed_release(self, shared) -> None:
        chain, payload = shared
        parsed = json.loads(payload)
        assert parsed["data"] == {
            "version": DATA_VERSION,
            "source_batches": list(SOURCE_BATCHES),
            "release_digest": _sha256(chain.release_dir / "release.yaml"),
            "seal_evidence": "release.yaml",
        }

    def test_prompt_segment_reflects_formal_prompt(self, shared) -> None:
        chain, payload = shared
        parsed = json.loads(payload)
        assert parsed["prompt"] == {
            "version": PROMPT_VERSION,
            "source_hash": _sha256(chain.prompt_path),
            "variables": list(OUTPUT_FIELDS),
        }

    def test_train_segment_reflects_completed_run(self, shared) -> None:
        chain, payload = shared
        record = get_train_run(chain.store, TRAIN_ID)
        parsed = json.loads(payload)
        assert parsed["train"] == {
            "train_id": TRAIN_ID,
            "folds": [0, 1, 2],
            "state": "completed",
            "run_id": record.run_id,
        }

    def test_eval_segment_reflects_frozen_view(self, shared) -> None:
        _chain, payload = shared
        parsed = json.loads(payload)
        assert parsed["eval"] == {
            "eval_id": EVAL_ID,
            "model_version": MODEL_VERSION,
            "source_train": TRAIN_ID,
            "data_version": DATA_VERSION,
            "scope": EVAL_SCOPE,
            "folds": [0, 1, 2],
            "outcome": EVAL_OUTCOME,
            "result_refs": dict(RESULT_REFS),
        }


# —————————————————— T2 五类 ID 显式解析（build 入口） ——————————————————


class TestBuildIdValidation:
    """负向：七处 ID 字段的非法/跨类别输入一律 InvalidIdentifier，且先于任何解析。"""

    @pytest.mark.parametrize("bad_id", BAD_IDS)
    @pytest.mark.parametrize(("field", "index", "attr"), _ID_FIELD_SPECS)
    def test_build_rejects_malformed_ids_before_any_resolution(
        self, tmp_path: Path, field: str, index: int, attr: str, bad_id: object
    ) -> None:
        # 空根/空 store 也能触发：ID 解析必须先于任何 store/文件系统访问。
        refs = _bare_refs(tmp_path)
        mutated = dataclasses.replace(refs[index], **{attr: bad_id})
        basket = list(refs)
        basket[index] = mutated
        with pytest.raises(InvalidIdentifier):
            _build_refs(tuple(basket))

    @pytest.mark.parametrize(
        ("field", "index", "attr", "wrong_kind_id"), _WRONG_KIND_IDS
    )
    def test_build_rejects_wrong_kind_ids(
        self, tmp_path: Path, field: str, index: int, attr: str, wrong_kind_id: str
    ) -> None:
        refs = _bare_refs(tmp_path)
        mutated = dataclasses.replace(refs[index], **{attr: wrong_kind_id})
        basket = list(refs)
        basket[index] = mutated
        with pytest.raises(InvalidIdentifier):
            _build_refs(tuple(basket))


# —————————————————— T3 引用门（fail-closed） ——————————————————


class TestBuildReferenceGate:
    """引用存在性/封存/状态/完成门；非法引用一律 ManifestReferenceError。"""

    def test_build_rejects_missing_data_release(self, chain: _Chain) -> None:
        with pytest.raises(ManifestReferenceError):
            _build(
                chain,
                data_ref=DataRecordRef(root=chain.root, version=DATA_VERSION_UNKNOWN),
            )

    def test_build_rejects_staged_not_sealed_data(self, chain: _Chain) -> None:
        # 只 stage 未 seal：releases/ 下不存在该版本（引用未封存）。
        _make_working(chain.root, "round-staged")
        stage_release(chain.root, "round-staged", PROTOCOL, version=DATA_VERSION_UNKNOWN)
        with pytest.raises(ManifestReferenceError):
            _build(
                chain,
                data_ref=DataRecordRef(root=chain.root, version=DATA_VERSION_UNKNOWN),
            )

    def test_build_rejects_data_payload_with_write_bit_restored(
        self, chain: _Chain
    ) -> None:
        # 封存证据门：payload 只读被破坏（人工解除权限）时拒绝。
        tampered = chain.release_dir / "datasets" / "labels.jsonl"
        os.chmod(tampered, tampered.stat().st_mode | 0o200)
        with pytest.raises(ManifestReferenceError):
            _build(chain)

    def test_build_rejects_holdout_data_as_training_source(
        self, chain: _Chain, tmp_path: Path
    ) -> None:
        # holdout 不是训练链数据源（§5.1 训练入口语义）。
        holdout_root = tmp_path / "holdout-proj"
        _seal_data(holdout_root, DATA_VERSION, purpose="holdout")
        with pytest.raises(ManifestReferenceError):
            _build(
                chain,
                data_ref=DataRecordRef(root=holdout_root, version=DATA_VERSION),
            )

    def test_build_rejects_invalid_status_data(self, chain: _Chain) -> None:
        update_release_status(chain.root, DATA_VERSION, "invalid")
        with pytest.raises(ManifestReferenceError):
            _build(chain)

    def test_build_accepts_superseded_data(self, chain: _Chain) -> None:
        # 边界正向：superseded 仍是历史训练证据（§10 data 行）。
        update_release_status(
            chain.root, DATA_VERSION, "superseded", replacement=DATA_VERSION_ALT
        )
        payload = _build(chain)
        parsed = json.loads(payload)
        assert parsed["data"]["release_digest"] == _sha256(
            chain.release_dir / "release.yaml"
        )
        validate_manifest(payload)

    def test_build_rejects_missing_prompt(self, chain: _Chain) -> None:
        with pytest.raises(ManifestReferenceError):
            _build(
                chain,
                prompt_ref=PromptRecordRef(
                    root=chain.root, version=PROMPT_VERSION_UNKNOWN
                ),
            )

    def test_build_rejects_missing_train_run(self, chain: _Chain) -> None:
        with pytest.raises(ManifestReferenceError):
            _build(
                chain,
                train_ref=TrainRecordRef(store=chain.store, train_id=TRAIN_ID_UNKNOWN),
                eval_ref=_eval_ref(source_train=TRAIN_ID_UNKNOWN),
            )

    @pytest.mark.parametrize(
        ("state", "run_status"),
        [("running", None), ("partial", "KILLED"), ("failed", "FAILED")],
    )
    def test_build_rejects_incomplete_train_states(
        self, chain: _Chain, state: str, run_status: str | None
    ) -> None:
        # 非完成 Run 不导出（§11.2/§13.1）。
        create_train_run(
            chain.store,
            TRAIN_ID_UNKNOWN,
            data_version=DATA_VERSION,
            prompt_version=PROMPT_VERSION,
            git_commit=GIT_COMMIT,
            base_model=BASE_MODEL,
            config=dict(TRAIN_CONFIG),
        )
        if state != "running":
            create_fold_run(chain.store, TRAIN_ID_UNKNOWN, 0)
            end_fold_run(chain.store, TRAIN_ID_UNKNOWN, 0, "FAILED")
            transition_train_state(
                chain.store, TRAIN_ID_UNKNOWN, state, run_status=run_status
            )
        with pytest.raises(ManifestReferenceError):
            _build(
                chain,
                train_ref=TrainRecordRef(store=chain.store, train_id=TRAIN_ID_UNKNOWN),
                eval_ref=_eval_ref(source_train=TRAIN_ID_UNKNOWN),
            )

    def test_build_accepts_archived_train(self, chain: _Chain) -> None:
        # 边界正向：archived 与 completed 均放行（§10 train 行）。
        transition_train_state(chain.store, TRAIN_ID, "archived")
        payload = _build(chain)
        assert json.loads(payload)["train"]["state"] == "archived"
        validate_manifest(payload)

    def test_build_rejects_invalid_train_record(self, chain: _Chain) -> None:
        mark_train_invalid(chain.store, TRAIN_ID)
        with pytest.raises(ManifestReferenceError):
            _build(chain)

    @pytest.mark.parametrize("tampered_state", _RAW_ILLEGAL_COMBINATION_STATES)
    def test_build_wraps_raw_workflow_state_illegal_combination(
        self, chain: _Chain, tampered_state: str
    ) -> None:
        # B7b 修复回归：绕过 transition_train_state 直接改 store（raw 篡改
        # workflow_state tag）后，get_train_run 抛出的原始 IllegalStateCombination
        # 不得泄漏：_train_gate 必须包装为 ManifestReferenceError 且 __cause__ 链
        # 保留（StateMachineError 属上游域异常，同样在包装面内）。
        record = get_train_run(chain.store, TRAIN_ID)
        assert record.run_status == "FINISHED"
        client = MlflowClient(tracking_uri=chain.store.tracking_uri)
        client.set_tag(record.run_id, WORKFLOW_STATE_TAG, tampered_state)
        with pytest.raises(ManifestReferenceError) as exc_info:
            _build(chain)
        exc = exc_info.value
        assert not isinstance(exc, IllegalStateCombination)
        assert isinstance(exc.__cause__, IllegalStateCombination)

    def test_build_wraps_missing_data_version_tag_keyerror(
        self, chain: _Chain
    ) -> None:
        # B7b 修复回归：raw 删除父 Run data_version tag 后，get_train_run 内
        # tags[data_version] 的原生 KeyError 不得泄漏：同样必须包装为
        # ManifestReferenceError 且 __cause__ 链保留。
        record = get_train_run(chain.store, TRAIN_ID)
        client = MlflowClient(tracking_uri=chain.store.tracking_uri)
        client.delete_tag(record.run_id, DATA_VERSION_TAG)
        with pytest.raises(ManifestReferenceError) as exc_info:
            _build(chain)
        exc = exc_info.value
        assert not isinstance(exc, KeyError)
        assert isinstance(exc.__cause__, KeyError)

    @pytest.mark.parametrize(("label", "overrides"), _EVAL_REF_OVERRIDES)
    def test_build_rejects_illegal_eval_view_values(
        self, chain: _Chain, label: str, overrides: dict
    ) -> None:
        with pytest.raises(ManifestReferenceError):
            _build(chain, eval_ref=_eval_ref(**overrides))

    @pytest.mark.parametrize(
        ("scope", "folds"),
        [("cross_validation", (0, 1, 2)), ("single_fold", (1,)), ("full", ())],
    )
    def test_build_accepts_all_eval_scopes(
        self, chain: _Chain, scope: str, folds: tuple[int, ...]
    ) -> None:
        # §5.5 三种 scope 的正向边界：集合语义匹配、输出升序。
        payload = _build(chain, eval_ref=_eval_ref(scope=scope, folds=folds))
        parsed = json.loads(payload)
        assert parsed["eval"]["scope"] == scope
        assert parsed["eval"]["folds"] == sorted(folds)
        validate_manifest(payload)


# —————————————————— T4 链路一致性 ——————————————————


class TestBuildChainCoherence:
    """跨段血缘一致性：MLflow tags 权威（§6 关系规则），不一致 fail-closed。"""

    def test_build_rejects_train_data_version_mismatch(self, chain: _Chain) -> None:
        # train 引用 data-v4.1-r2，而 data 段是 r1：血缘断裂。
        _complete_training(chain.store, TRAIN_ID_UNKNOWN, data_version=DATA_VERSION_ALT)
        with pytest.raises(ManifestReferenceError):
            _build(
                chain,
                train_ref=TrainRecordRef(store=chain.store, train_id=TRAIN_ID_UNKNOWN),
                eval_ref=_eval_ref(source_train=TRAIN_ID_UNKNOWN),
            )

    def test_build_rejects_train_prompt_version_mismatch(self, chain: _Chain) -> None:
        _complete_training(
            chain.store, TRAIN_ID_UNKNOWN, prompt_version=PROMPT_VERSION_ALT
        )
        with pytest.raises(ManifestReferenceError):
            _build(
                chain,
                train_ref=TrainRecordRef(store=chain.store, train_id=TRAIN_ID_UNKNOWN),
                eval_ref=_eval_ref(source_train=TRAIN_ID_UNKNOWN),
            )

    def test_build_rejects_eval_source_train_mismatch(self, chain: _Chain) -> None:
        # eval 声称的来源训练与 train 段不是同一版本（合法 ID 但不一致）。
        with pytest.raises(ManifestReferenceError):
            _build(chain, eval_ref=_eval_ref(source_train=TRAIN_ID_ALT))


# —————————————————— T5 确定性序列化 ——————————————————


class TestDeterministicSerialization:
    """同一组输入字节级可复现（§13.1）：排序、canonical 形态、输入顺序无关。"""

    def test_build_is_byte_reproducible(self, shared) -> None:
        chain, payload = shared
        assert _build(chain) == payload
        assert _build(chain) == payload

    def test_build_ignores_input_container_ordering(self, shared) -> None:
        # folds 乱序 + result_refs 插入序反转：语义相同 -> 字节相同。
        chain, payload = shared
        shuffled_eval = _eval_ref(
            folds=(2, 1, 0),
            result_refs={
                key: value for key, value in reversed(list(RESULT_REFS.items()))
            },
        )
        assert _build(chain, eval_ref=shuffled_eval) == payload

    def test_output_is_canonical_json(self, shared) -> None:
        # 字段排序 + 紧凑分隔符 + 无尾随换行：canonical 形态钉死。
        _chain, payload = shared
        assert payload == json.dumps(
            json.loads(payload), sort_keys=True, separators=(",", ":")
        )


# —————————————————— T6 校验函数与篡改拒绝 ——————————————————


class TestValidateManifest:
    """重解析输出 JSON、字段完整与值域校验；人工修改被检测（§13.1）。"""

    def test_validate_returns_parsed_mapping(self, shared) -> None:
        _chain, payload = shared
        assert validate_manifest(payload) == json.loads(payload)

    def test_validate_accepts_semantically_identical_redump(self, shared) -> None:
        # validator 是语义级校验：同义重排（键序/空白）应通过。
        _chain, payload = shared
        redumped = json.dumps(json.loads(payload), indent=2, sort_keys=False)
        assert validate_manifest(redumped) == json.loads(payload)

    @pytest.mark.parametrize(
        "bad_payload", ["", "{oops", "null", "[]", '"a-string"', "42", None, b"{}"]
    )
    def test_validate_rejects_non_json_or_non_str_payload(
        self, shared, bad_payload: object
    ) -> None:
        _chain, _payload = shared
        with pytest.raises(ManifestSchemaError):
            validate_manifest(bad_payload)

    @pytest.mark.parametrize(("label", "mutator"), _BAD_MANIFEST_VERSIONS)
    def test_validate_rejects_bad_manifest_version(
        self, shared, label: str, mutator: Callable[[dict], None]
    ) -> None:
        _chain, payload = shared
        with pytest.raises(ManifestSchemaError):
            validate_manifest(_tampered(payload, mutator))

    @pytest.mark.parametrize("segment", ["data", "prompt", "train", "eval"])
    def test_validate_rejects_missing_segment(
        self, shared, segment: str
    ) -> None:
        _chain, payload = shared

        def mutate(obj: dict) -> None:
            del obj[segment]

        with pytest.raises(ManifestSchemaError):
            validate_manifest(_tampered(payload, mutate))

    def test_validate_rejects_unknown_top_level_key(self, shared) -> None:
        _chain, payload = shared

        def mutate(obj: dict) -> None:
            obj["exported_by"] = "someone"

        with pytest.raises(ManifestSchemaError):
            validate_manifest(_tampered(payload, mutate))

    @pytest.mark.parametrize("segment", ["data", "prompt", "train", "eval"])
    def test_validate_rejects_unknown_segment_field(
        self, shared, segment: str
    ) -> None:
        _chain, payload = shared

        def mutate(obj: dict) -> None:
            obj[segment]["extra_field"] = 1

        with pytest.raises(ManifestSchemaError):
            validate_manifest(_tampered(payload, mutate))

    @pytest.mark.parametrize(("segment", "field"), _ALL_SEGMENT_FIELDS)
    def test_validate_rejects_missing_segment_field(
        self, shared, segment: str, field: str
    ) -> None:
        _chain, payload = shared

        def mutate(obj: dict) -> None:
            obj[segment].pop(field)

        with pytest.raises(ManifestSchemaError):
            validate_manifest(_tampered(payload, mutate))

    @pytest.mark.parametrize(("label", "mutator"), _DOMAIN_TAMPERS)
    def test_validate_rejects_value_domain_violations(
        self, shared, label: str, mutator: Callable[[dict], None]
    ) -> None:
        _chain, payload = shared
        with pytest.raises(ManifestSchemaError):
            validate_manifest(_tampered(payload, mutator))

    @pytest.mark.parametrize(("segment", "field"), _HEX_DIGEST_FIELDS)
    @pytest.mark.parametrize(("label", "bad_value"), _LEN64_HEX_LOOKALIKES)
    def test_validate_rejects_len64_hex_lookalikes(
        self, shared, segment: str, field: str, label: str, bad_value: str
    ) -> None:
        # B7b 修复回归（_is_lowercase_hex 严格整串匹配）：样本长度恰为 64——
        # 长度门放行，但 0x 前缀/负号/下划线等非十六进制字符必须拒绝；
        # 宽松实现（如 int(x,16)，接受 0x 前缀/符号/下划线分隔）会误放行。
        assert len(bad_value) == 64
        _chain, payload = shared

        def mutate(obj: dict) -> None:
            obj[segment][field] = bad_value

        with pytest.raises(ManifestSchemaError):
            validate_manifest(_tampered(payload, mutate))

    def test_validate_rejects_cross_segment_source_train_mismatch(
        self, shared
    ) -> None:
        # 合法但与 train 段不一致的 source_train：语义级篡改被检测。
        _chain, payload = shared

        def mutate(obj: dict) -> None:
            obj["eval"]["source_train"] = TRAIN_ID_ALT

        with pytest.raises(ManifestSchemaError):
            validate_manifest(_tampered(payload, mutate))


# —————————————————— T7 单向导出 ——————————————————


class TestOneWayExport:
    """单向导出（任务卡 §5.7）：生成/校验/落盘不反向修改任何 versioning 对象。"""

    def test_build_validate_export_leave_sources_untouched(
        self, chain: _Chain, tmp_path: Path
    ) -> None:
        before = (
            _release_snapshot(chain.release_dir),
            chain.prompt_path.read_bytes(),
            _store_snapshot(chain.store),
        )
        payload = _build(chain)
        validate_manifest(payload)
        target = tmp_path / "records" / "evaluations" / EVAL_ID / "manifest.json"
        result = _export(target, chain)
        after = (
            _release_snapshot(chain.release_dir),
            chain.prompt_path.read_bytes(),
            _store_snapshot(chain.store),
        )
        assert after == before
        assert result == target
        assert target.read_text(encoding="utf-8") == payload
        assert [entry.name for entry in target.parent.iterdir()] == ["manifest.json"]

    def test_export_is_idempotent_for_identical_manifest(
        self, chain: _Chain, tmp_path: Path
    ) -> None:
        # 同字节幂等重导（§2.6 更正策略：导出器错误可同语义重导）。
        target = tmp_path / "out" / "manifest.json"
        _export(target, chain)
        first = target.read_bytes()
        _export(target, chain)
        assert target.read_bytes() == first

    def test_export_conflicts_on_different_manifest_content(
        self, chain: _Chain, tmp_path: Path
    ) -> None:
        # 不同语义内容写入已有目标：拒绝（事实字段封存后不得原地改写）。
        target = tmp_path / "out" / "manifest.json"
        _export(target, chain)
        original = target.read_bytes()
        second = _second_chain(chain)
        with pytest.raises(ManifestConflict):
            _export(target, second)
        assert target.read_bytes() == original
