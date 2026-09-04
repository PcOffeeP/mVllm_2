"""B7a — MLflow 测评记录：eval-v 独立父 Run + 三种 scope + fold 绑定 + holdout 鉴权。

对应权威设计 docs/plans/2026-09-01-readable-version-control-design.md：
§2.8 + D023（训练过程诊断保存在训练 Run 内、不获得正式 eval 版本；每个形成
长期项目结论的 ``eval-v<协议>-r<N>`` 对应**独立** MLflow 父 Run，不附着或
覆盖原训练 Run；正式测评父 Run 显式引用被测 ``model-v...``、测评
``data-v...``、测评配置与 Git commit；包含三折时 fold0/1/2 作为子 Run，
汇总指标与通过/失败结论保存在父 Run；更换测评数据、评价规则或指标口径
必须新建 ``eval-v...``，不得覆盖旧 Run）、§5.5（三种 scope：单折
``single_fold`` 只允许一个 fold 绑定；``cross_validation`` 严格绑定
fold0–fold2 子 Run，每 fold 记录模型 artifact 引用、数据 split、样本数、
records/failures 路径，封存前 fold 集合与 artifacts/splits 一一对应、无
缺失无重复，聚合结果只能由这三个 fold 结果产生；``full`` 引用明确独立
验收 split）、§5.6（holdout 正式测评：首次模型调用前 staging 保存
pre_registration.yaml 并在 data 版本自己的 authorization/ 原子创建全局
一次性 claim，绑定 eval/model/data/split 四元组与一次执行身份；已消费
不得再用；新进程必须携带并验证原执行身份）、§2.6（record_validity 权威
位置在父 Run tag，合法值仅 ``valid|invalid``，invalid 被下游拒绝、不得
复活；MLflow 用 SQLite 单文件 + 本地 artifact store；不得启动服务、不得
连接正式 store）、§5.3 + D038（workflow_state ↔ MLflow 原生 RunStatus
固定组合表与状态机纪律；拒绝人工或异常操作产生的非法组合）、§10（eval
行下游规则：只有执行完整且 ``record_validity: valid`` 的正式测评可形成
当前结论；``outcome: failed`` 仍是有效质量证据）、§9/§11.6（显式版本
纪律：eval_id 必须显式给出，缺失/非法/同名冲突一律拒绝，不自动分配）、
§8（只增不改；正式事实错误走 invalid + 新建版本，不原地改写）、§7
（正式测评必须显式传入完整版本名；引用不存在 fail-closed）。

预期 production API（供 viber 对照实现，模块 ``versioning.mlflow_eval``）::

    # ——— 模块常量（tag 键名钉死；raw MLflow 读回按字面量断言）———
    DEFAULT_EVAL_EXPERIMENT: str = "mVllm2-evaluation"
    REQUIRED_FOLDS: tuple[int, ...] = (0, 1, 2)
    SCOPES: tuple[str, ...] = ("single_fold", "cross_validation", "full")
    OUTCOMES: tuple[str, ...] = ("passed", "failed")
    EVAL_ID_TAG: str = "eval_id"
    WORKFLOW_STATE_TAG: str = "workflow_state"
    RECORD_VALIDITY_TAG: str = "record_validity"
    MODEL_ID_TAG: str = "model_id"
    MODEL_VERSION_NUMBER_TAG: str = "model_version_number"
    DATA_VERSION_TAG: str = "data_version"
    CONFIG_TAG: str = "config"
    GIT_COMMIT_TAG: str = "git_commit"
    SCOPE_TAG: str = "scope"
    SPLIT_TAG: str = "split"
    OUTCOME_TAG: str = "outcome"
    SUMMARY_COMPLETE_TAG: str = "summary_complete"
    AGGREGATE_FOLDS_TAG: str = "aggregate_folds"   # 值如 "fold0,fold1,fold2"
    FOLD_TAG: str = "fold"                          # 子 Run tag 值 "fold<N>"
    MODEL_ARTIFACT_TAG: str = "model_artifact"
    DATA_SPLIT_TAG: str = "data_split"
    SAMPLE_COUNT_TAG: str = "sample_count"
    RECORDS_TAG: str = "records"
    FAILURES_TAG: str = "failures"

    # ——— 异常（基类 MLflowEvalError(ValueError)；状态机异常委托
    #     versioning.state，直接传播或以其为基类的子类均可）———
    class MLflowEvalError(ValueError)
        # 测评记录域异常基类
    class EvalRecordNotFound(MLflowEvalError)
        # 指定 eval 记录或其 fold 子 Run 在本 store 中不存在
    class EvalRunConflict(MLflowEvalError)
        # 同一 eval-v... 已存在父 Run（含已删除 Run，ViewType.ALL 语义；
        # §8 只增不改 / §11.6 同名冲突），或同父 Run 下同 fold 子 Run
        # 已存在；冲突拒绝，原 Run 一律不动
    class IllegalEvalRecord(MLflowEvalError)
        # 记录构造/操作输入非法或结构违规：共同引用缺失/非法、scope 非法、
        # fold 编号/绑定非法、scope 违规的 fold 集合、aggregate 输入集合
        # 与观测 fold 集合不一致、summary/aggregate 的 scope 互斥违规、
        # 被引 data release 缺失或不可解析、读取 fail-closed（篡改 tag、
        # 非法子 Run 观测）等
    class IncompleteEvalRecord(MLflowEvalError)
        # completed / 结论门拒绝：必需 fold 缺失或未 FINISHED、fold 集合
        # 与 scope 要求不一致、缺三折汇总（summary_complete）、缺
        # aggregate 或 aggregate 输入集合与 fold 集合不一致、缺 outcome、
        # 或 workflow_state 未达 completed|archived
    class InvalidEvalRecord(MLflowEvalError)
        # record_validity=invalid 的测评记录被下游校验拒绝（§2.6/§10，
        # 不得通过改回 valid 复活旧事实）
    class HoldoutAuthorizationError(MLflowEvalError)
        # holdout 鉴权 fail-closed：被引 data 为 purpose=holdout 但无
        # 有效 claim / 无 pre_registration / 四元组或 executor 不一致 /
        # claim 已消费 / 缺 split（claim 四元组需要单一 split）

    # ——— store 句柄（真实 MLflow：SQLite 单文件 + 本地 artifact store）———
    @dataclass(frozen=True)
    class EvalRecordStore
        root: Path                  # store 根目录
        tracking_uri: str           # sqlite:///<root>/mlflow.db
        experiment_id: str          # 测评实验 ID（字符串）
        artifact_location: str     # <root>/artifacts（本地目录）

    def open_eval_store(root: Path, *,
                        experiment_name: str = DEFAULT_EVAL_EXPERIMENT
                        ) -> EvalRecordStore
        # 与 versioning.mlflow_train.open_train_store 同构：创建（缺失时）
        # root 与 root/artifacts；tracking 指向 sqlite:///<root>/mlflow.db；
        # 创建或按名复用实验并绑定本地 artifact_location；绝不启动服务、
        # 绝不连接 root 之外的任何 store；一切后续函数必须按 store 句柄
        # 寻址（不依赖全局 ambient tracking 状态，双 store 互不可见）。
        # 与训练实验同根共存时共用同一 SQLite 文件、experiment_id 不同。

    # ——— 记录快照（只读视图）———
    @dataclass(frozen=True)
    class EvalFoldRecord
        eval_id: str
        fold: int
        run_id: str
        parent_run_id: str           # 父 Run MLflow ID（嵌套关联）
        run_name: str                # "fold<N>"
        status: str                 # 原生 RunStatus：RUNNING/FINISHED/FAILED/KILLED
        model_artifact: str          # 模型 artifact 引用（如 artifacts/fold0/merged）
        data_split: str              # 数据 split（如 validation/fold0）
        sample_count: int            # 样本数（tag 字符串还原 int）
        records: str                 # records.jsonl 路径
        failures: str                # failures.jsonl 路径
        metrics: Mapping[str, float] # 该 fold 指标最新值

    @dataclass(frozen=True)
    class EvalRunRecord
        eval_id: str
        run_id: str
        experiment_id: str
        run_name: str                # == eval_id
        workflow_state: str          # 项目工作流状态值（versioning.state）
        run_status: str              # 原生 RunStatus 字符串
        record_validity: str         # "valid" | "invalid"
        model_id: str                # 被测 model-v...（完整可读 ID）
        model_version_number: int    # 数值 Model Version（tag 字符串还原 int）
        data_version: str            # 测评 data-v...（完整可读 ID）
        config: str                  # 冻结测评配置引用（非空字符串）
        git_commit: str
        scope: str                   # single_fold | cross_validation | full
        split: str | None            # single_fold/full 必填；cross_validation 可缺省
        outcome: str | None          # passed | failed；completed 转换时写入
        metrics: Mapping[str, float] # 父 Run 指标（汇总/聚合）最新值
        folds: Mapping[int, EvalFoldRecord]  # 既有 fold 子 Run，按编号索引

    # ——— 父 Run（独立父 Run，D023/§2.8）———
    def create_eval_run(store, eval_id: str, *, model_id: str,
                        model_version_number: int, data_version: str,
                        config: str, git_commit: str, scope: str,
                        split: str | None = None, data_root: Path,
                        pre_registration: Path | None = None,
                        executor: str | None = None) -> EvalRunRecord
        # - eval_id 必须显式给出并经 versioning.ids.parse_eval_id 校验
        #   （缺省/None/latest/短前缀/跨类别/r0/前导零/非字符串 ->
        #   InvalidIdentifier）；模块不存在任何自动分配下一版本号的分支；
        # - model_id / data_version 必须分别是经 parse_model_id /
        #   parse_data_id 校验通过的完整 ID（§3.3 显式记录）；
        # - model_version_number 必须是不小于 1 的真 int（bool/str/float/
        #   0/负数 -> IllegalEvalRecord）；config / git_commit 必须是
        #   非空字符串；scope 必须在 SCOPES 内；
        # - split：scope 为 single_fold/full 时必填非空字符串；
        #   cross_validation 可缺省（None）；
        # - data_root 必填：模块经 versioning.data_release.load_release_
        #   metadata 读取被引 data 的 release.yaml 以判定 purpose（§7
        #   引用不存在 fail-closed：release 缺失/不可解析 ->
        #   IllegalEvalRecord）；
        # - 被引 data purpose=holdout 时（§5.6）：split 必填；
        #   pre_registration 必须存在、可解析（holdout.load_pre_registration
        #   语义）且四元组 eval_version/model_version/data_version/split
        #   与本次创建完全一致；authorization/claim.yaml 必须已存在
        #   （holdout.load_claim 语义，模块不创建 claim）且四元组与
        #   executor 均一致；已消费（consumed.yaml 存在）拒绝——任一
        #   不满足 -> HoldoutAuthorizationError；
        # - 同名 eval-v... 已存在（含已删除 Run）-> EvalRunConflict，
        #   原 Run 不动；
        # - 一切校验通过才创建 Run：独立父 Run（不写 mlflow.parentRunId），
        #   原生 RUNNING、workflow_state=running、record_validity=valid；
        #   父 Run tags：eval_id / workflow_state / record_validity /
        #   model_id / model_version_number（str 化）/ data_version /
        #   config / git_commit / scope，split 提供时写 split tag；
        #   run_name == eval_id。

    def get_eval_run(store, eval_id: str) -> EvalRunRecord
        # 按 eval_id tag 检索父 Run；不存在 -> EvalRecordNotFound；
        # 读取 fail-closed（D038）：入口先 parse_eval_id（畸形 ->
        # InvalidIdentifier，绝不泄漏 MLflow 查询异常、不与 NotFound 混淆）；
        # 快照构建强校验：workflow_state/run_status 组合经
        # versioning.state.validate_workflow_run_status（非法 ->
        # IllegalStateCombination）；record_validity ∈ {valid, invalid}、
        # scope ∈ SCOPES、model_id/data_version 可解析、
        # model_version_number tag 可解析为 ≥1 int、config/git_commit
        # 非空、outcome tag 存在时值 ∈ OUTCOMES、aggregate_folds tag 仅
        # 允许出现在 cross_validation 且每项为 fold<N>（N ∈
        # REQUIRED_FOLDS）（违规 -> IllegalEvalRecord）；single_fold/full 缺 split tag ->
        # IllegalEvalRecord；子 Run 观测 well-formedness：fold tag 可解析
        # 为 REQUIRED_FOLDS 内编号、无重复、数量不超过 scope 上限
        # （cross_validation ≤ 3、single_fold ≤ 1、full == 0）、绑定
        # tags（model_artifact/data_split/records/failures 非空、
        # sample_count 可解析为 ≥0 int）齐全（违规 -> IllegalEvalRecord）。
        # 缺 fold（数量未达 scope 要求）不属读取错误，由 completed 门拒绝。

    def list_eval_fold_runs(store, eval_id: str) -> tuple[EvalFoldRecord, ...]
        # 该 eval 的全部子 Run，按 fold 编号升序；eval 不存在 ->
        # EvalRecordNotFound；观测校验同 get_eval_run。

    # ——— fold 子 Run（cross_validation/single_fold 的逐 fold 绑定）———
    def create_eval_fold_run(store, eval_id: str, fold: int, *,
                             model_artifact: str, data_split: str,
                             sample_count: int, records: str,
                             failures: str) -> EvalFoldRecord
        # eval 不存在 -> EvalRecordNotFound；父 Run workflow_state 非
        # running -> IllegalEvalRecord（completed/archived 不得原地重跑）；
        # fold 必须是 REQUIRED_FOLDS 内的真 int（bool/字符串/float/越界 ->
        # IllegalEvalRecord）；scope=full -> 一律 IllegalEvalRecord（无
        # fold 绑定）；scope=single_fold 且已有另一编号 fold 子 Run ->
        # IllegalEvalRecord（只允许一个 fold 绑定）；同父 Run 下同 fold
        # 已存在 -> EvalRunConflict（原 Run 不动）；绑定字段：非空字符串
        # model_artifact/data_split/records/failures + sample_count 为
        # ≥0 真 int（bool/负数/字符串 -> IllegalEvalRecord）；
        # 子 Run 原生 RUNNING；tags：fold="fold<N>"、mlflow.runName=
        # "fold<N>"、系统 tag mlflow.parentRunId=父 Run ID、五个绑定
        # 字段（sample_count str 化）；子 Run 不写 workflow_state /
        # record_validity（权威在父 Run）。

    def log_eval_fold_metrics(store, eval_id: str, fold: int,
                             metrics: Mapping[str, float]) -> EvalFoldRecord
        # 指标写该 fold 子 Run：非空 Mapping，键非空字符串，值 int/float
        # （bool/None/容器 -> IllegalEvalRecord）；eval 或 fold 子 Run
        # 不存在 -> EvalRecordNotFound；返回最新快照（多批取最新值）；
        # 指标只落子 Run，不落父 Run。

    def end_eval_fold_run(store, eval_id: str, fold: int, run_status: str, *,
                          metrics: Mapping[str, float] | None = None
                          ) -> EvalFoldRecord
        # run_status 必须显式为 "FINISHED"/"FAILED"/"KILLED"（其他 ->
        # IllegalEvalRecord）；仅 RUNNING 子 Run 可终转（已终态 ->
        # IllegalEvalRecord）；可选 metrics 先写后终；eval 或 fold 子
        # Run 不存在 -> EvalRecordNotFound。

    def resume_eval_fold_run(store, eval_id: str, fold: int) -> EvalFoldRecord
        # 受控恢复（§5.6 恢复规则）：仅 FAILED/KILLED 子 Run 经原 Run ID
        # 恢复 RUNNING，不新建子 Run；FINISHED 不得恢复、RUNNING 无需
        # 恢复 -> IllegalEvalRecord。

    # ——— 父 Run 汇总（scope 互斥）———
    def log_eval_summary(store, eval_id: str,
                         metrics: Mapping[str, float]) -> EvalRunRecord
        # 仅 single_fold / full：逐项写父 Run metrics 并置
        # summary_complete="true"；cross_validation -> IllegalEvalRecord
        # （三折口径只能经 log_eval_aggregate）；父 Run workflow_state
        # 非 running -> IllegalEvalRecord；eval 不存在 ->
        # EvalRecordNotFound。

    def log_eval_aggregate(store, eval_id: str,
                           metrics: Mapping[str, float], *,
                           folds) -> EvalRunRecord
        # 仅 cross_validation：聚合输入 fold 集合必须与既有子 Run fold
        # 集合完全一致（§5.5 聚合结果只能由声明的 fold 产生；多报/少报/
        # 重复报 -> IllegalEvalRecord）；写父 Run metrics、tag
        # aggregate_folds="fold0,fold1,fold2"（升序逗号连接）并置
        # summary_complete="true"；完成前可重记（覆盖 tag 与指标最新值）；
        # single_fold/full -> IllegalEvalRecord；父 Run 非 running ->
        # IllegalEvalRecord；eval 不存在 -> EvalRecordNotFound。

    # ——— 父 Run 状态转换（workflow_state 与原生状态一起转换）———
    def transition_eval_state(store, eval_id: str,
                              target: WorkflowState | str, *,
                              run_status: str | None = None,
                              outcome: str | None = None) -> EvalRunRecord
        # 与 mlflow_train.transition_train_state 同构，另加 outcome：
        # 1) 读取并校验当前组合（篡改 -> IllegalStateCombination）；
        # 2) versioning.state.transition_workflow_state(current, target)：
        #    非法转换（含自环、partial/failed->completed、目标 prepared、
        #    completed->running、archived->* 等）-> IllegalTransition；
        # 3) 目标原生状态按 §5.3 固定表：running->RUNNING、
        #    completed/archived->FINISHED（run_status 缺省取默认，显式给
        #    其他值 -> IllegalStateCombination）；partial/failed 必须显式
        #    run_status="FAILED"|"KILLED"（缺省或其他值 ->
        #    IllegalStateCombination）；
        # 4) target=completed 时执行 completed 门（先决于写回）：
        #    - outcome 必填且 ∈ OUTCOMES（缺省/非法 -> IllegalEvalRecord）；
        #    - scope 完整性：cross_validation 恰有 fold0/1/2 子 Run 且
        #      全部 FINISHED、summary_complete 且 aggregate_folds 集合
        #      == 观测 fold 集合 == {0,1,2}；single_fold 恰一个子 Run 且
        #      FINISHED、summary_complete；full 无子 Run、summary_complete
        #      ——任一不满足 -> IncompleteEvalRecord；
        # 5) 原生状态与 tags 一起写回（partial/failed -> FAILED/KILLED
        #    终转；completed/archived -> FINISHED；受控恢复 -> RUNNING，
        #    原 Run ID 不变）；completed 另写 outcome tag；
        # 6) target != completed 时 outcome 必须为 None（否则
        #    IllegalEvalRecord——结论只在封存时冻结一次）。

    def mark_eval_invalid(store, eval_id: str) -> EvalRunRecord
        # 更正策略（§2.6/§8）：父 Run tag record_validity -> invalid，经
        # versioning.state.transition_record_validity（valid->invalid 允许、
        # 同值幂等、invalid->valid 拒绝）；模块不提供任何改回 valid 的
        # 入口；eval 不存在 -> EvalRecordNotFound。

    def validate_eval_for_conclusion(store, eval_id: str) -> EvalRunRecord
        # §10 eval 行下游门（只校验、不实现结论消费）：
        # 1) eval 不存在 -> EvalRecordNotFound；
        # 2) record_validity=invalid -> InvalidEvalRecord（先于组合与
        #    完整性校验，§10 优先级）；
        # 3) 当前组合非法 -> IllegalStateCombination；
        # 4) workflow_state 非 completed|archived -> IncompleteEvalRecord；
        # 5) scope 完整性同 completed 门（fold 集合/终态/summary 或
        #    aggregate）-> IncompleteEvalRecord；
        # 6) outcome tag 缺失 -> IncompleteEvalRecord（outcome 值域已在
        #    读取层校验）；全部通过返回 EvalRunRecord（completed 与
        #    archived 均放行；outcome=failed 同样放行，§10 failed 仍是
        #    有效质量证据）。

语义决策点（测试侧钉定，供实现对照）：
    1. eval 使用独立实验 "mVllm2-evaluation"（与训练实验同根时共用同一
       SQLite 文件、experiment_id 不同）；D023"独立父 Run"落地为：eval 父
       Run 不携带 mlflow.parentRunId、不经训练 Run 挂靠、与训练 Run 互不
       可见（按 experiment + eval_id tag 寻址）。
    2. data_root 为 create_eval_run 必填引用：模块必须读到被引 data 的
       release.yaml 才能判定 purpose（缺 -> fail-closed），否则"引用
       holdout 数据而无鉴权"存在被省略的旁路；数据生命周期状态门
       （active/superseded/invalid）与训练入口 fail-closed 属 B9 接线，
       本批不 pin。
    3. holdout 鉴权是 load/verify 语义、不是 acquire：claim 必须已由
       staging 在首次模型调用前建立（模块绝不创建/改写 claim）；模块只
       验证四元组 + executor + 未消费。pre_registration 由调用方显式给
       路径（staging 布局归 manifest/封存批次），必须存在、可解析且四
       元组一致。一次性消费登记（mark_claim_consumed）属执行管线/B9，
       不在本模块 pin（completed 不消费 claim）。
    4. config 是单一非空字符串 tag（冻结测评配置引用），不是 params
       Mapping——B6 的完整训练配置写 params，eval 引用的是"测评配置"这
       一单一事实（§2.6 manifest："测评数据与配置"）。
    5. model_version_number 是 mVllm2 Registry 数值 Model Version（≥1
       int）；B7 不连 Registry（B8 职责），只记录并强校验可解析性，不
       校验其存在性。
    6. fold 绑定五字段全部记为子 Run tags（与父 Run 引用 tags 对称、
       可被 search 过滤、篡改可被读取层强校验捕获）；sample_count 快照
       还原 int。
    7. scope↔fold 集合规则：cross_validation 恰 {0,1,2}；single_fold
       恰 1 个（∈{0,1,2}）；full 恰 0 个。读取层校验"不超上限且
       well-formed"（缺 fold 属运行中合法状态），completed/结论门校验
       "恰好 + 全 FINISHED"。
    8. split 声明：single_fold/full 必填非空字符串；cross_validation
       可缺省。holdout 的 claim 四元组需要单一 split，故 holdout eval
       必带 split（缺 -> HoldoutAuthorizationError）。
    9. aggregate 纪律：log_eval_aggregate 输入 fold 集合必须 == 既有子
       Run fold 集合（双向不一致均拒绝，包括"多报未建 fold"与"少报已建
       fold"）；completed 门再校验 aggregate_folds tag == 观测集合 ==
       {0,1,2}；完成前可重记（中途补折后必须重聚合），completed 后禁止
       改写；summary 与 aggregate 按 scope 互斥。
    10. outcome 只在 running->completed 转换写入（passed|failed），状态
        机不可逆（completed 无自环、无回退）保证结论不可改写；
        outcome=failed 完整执行后同样是有效证据（门放行）。读取层对
        outcome tag 存在即校验值域（篡改 -> IllegalEvalRecord）。
    11. 源 train-v... 引用不在本批契约（任务契约五引用 tag 之外）；
        model->train 血缘由 B8 model manifest 承接，eval 只经 model_id
        引用被测模型。
    12. fold 子 Run 不携带 workflow_state/record_validity（项目状态与
        有效性权威在父 Run，镜像 B6 纪律）。
    13. 读路径 fail-closed：入口先 parse_eval_id（含引号注入/尾随换行/
        非字符串一律 InvalidIdentifier，绝不 MlflowException、绝不与
        NotFound 混淆）；快照构建校验组合、值域、可解析性与子 Run 观测
        well-formedness；已删除 Run 仍占名（ViewType.ALL 语义）。
    14. 指标落点：fold 指标只落子 Run；汇总（single/full）与聚合
        （cross_validation）只落父 Run；completed 后父 Run 指标与结论
        不可再改写（log_eval_summary/log_eval_aggregate 要求 running）。

测试环境：真实 MLflow 集成（非 mock）；全部 store 在 pytest ``tmp_path``
内（SQLite + 本地 artifact store），holdout/development data release 用
versioning.data_release 真实封存于 ``tmp_path``，不启动服务、不连接任何
正式 store、不触碰 workspace/ 真实数据与真实真值。

当前 ``versioning/mlflow_eval.py`` 尚不存在，本文件全部用例应为 RED
（collection error：ModuleNotFoundError / ImportError）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from versioning.data_release import seal_release, stage_release
from versioning.holdout import ClaimIdentity, acquire_claim, mark_claim_consumed
from versioning.ids import InvalidIdentifier
from versioning.mlflow_eval import (
    AGGREGATE_FOLDS_TAG,
    CONFIG_TAG,
    DATA_SPLIT_TAG,
    DATA_VERSION_TAG,
    DEFAULT_EVAL_EXPERIMENT,
    EVAL_ID_TAG,
    FAILURES_TAG,
    FOLD_TAG,
    GIT_COMMIT_TAG,
    MODEL_ARTIFACT_TAG,
    MODEL_ID_TAG,
    MODEL_VERSION_NUMBER_TAG,
    OUTCOME_TAG,
    OUTCOMES,
    RECORD_VALIDITY_TAG,
    RECORDS_TAG,
    REQUIRED_FOLDS,
    SAMPLE_COUNT_TAG,
    SCOPES,
    SCOPE_TAG,
    SPLIT_TAG,
    SUMMARY_COMPLETE_TAG,
    WORKFLOW_STATE_TAG,
    EvalFoldRecord,
    EvalRecordNotFound,
    EvalRecordStore,
    EvalRunConflict,
    EvalRunRecord,
    HoldoutAuthorizationError,
    IllegalEvalRecord,
    IncompleteEvalRecord,
    InvalidEvalRecord,
    MLflowEvalError,
    create_eval_fold_run,
    create_eval_run,
    end_eval_fold_run,
    get_eval_run,
    list_eval_fold_runs,
    log_eval_aggregate,
    log_eval_fold_metrics,
    log_eval_summary,
    mark_eval_invalid,
    open_eval_store,
    resume_eval_fold_run,
    transition_eval_state,
    validate_eval_for_conclusion,
)
from versioning.mlflow_train import (
    create_fold_run as create_train_fold_run,
    create_train_run,
    end_fold_run as end_train_fold_run,
    log_fold_metrics as log_train_fold_metrics,
    log_train_summary,
    open_train_store,
    transition_train_state,
)
from versioning.state import (
    ALLOWED_RUN_STATUSES,
    IllegalStateCombination,
    IllegalTransition,
    RecordValidity,
    WorkflowState,
)

EVAL_ID = "eval-v4.1-r1"
OTHER_EVAL_ID = "eval-v4.1-r2"
UNKNOWN_EVAL_ID = "eval-v4.1-r9"
MODEL_ID = "model-v4.1-r1"
OTHER_MODEL_ID = "model-v4.1-r2"
DATA_VERSION = "data-v4.1-r1"  # development 正式 release
MISSING_DATA_VERSION = "data-v4.1-r7"  # 合法 ID、但 data_root 中无封存 release
HOLDOUT_DATA_VERSION = "data-v4.1-r9"  # purpose=holdout 正式 release
SPLIT = "validation"
HOLDOUT_SPLIT = "test"
GIT_COMMIT = "a1b2c3d"
CONFIG = "records/evaluations/config/eval-v4.1-contract.yaml"
EXECUTOR = "runner-A"
MODEL_VERSION_NUMBER = 1

# §5.5 示例口径的 fold 绑定（数量仅示例）。
FOLD_BINDINGS: dict[int, dict] = {
    0: {
        "model_artifact": "artifacts/fold0/merged",
        "data_split": "validation/fold0",
        "sample_count": 425,
        "records": "folds/fold0/records.jsonl",
        "failures": "folds/fold0/failures.jsonl",
    },
    1: {
        "model_artifact": "artifacts/fold1/merged",
        "data_split": "validation/fold1",
        "sample_count": 664,
        "records": "folds/fold1/records.jsonl",
        "failures": "folds/fold1/failures.jsonl",
    },
    2: {
        "model_artifact": "artifacts/fold2/merged",
        "data_split": "validation/fold2",
        "sample_count": 492,
        "records": "folds/fold2/records.jsonl",
        "failures": "folds/fold2/failures.jsonl",
    },
}

FOLD_METRICS: dict[int, dict] = {
    0: {"fold_f1": 0.81, "fold_loss": 0.42},
    1: {"fold_f1": 0.79, "fold_loss": 0.45},
    2: {"fold_f1": 0.80, "fold_loss": 0.44},
}
AGGREGATE_METRICS: dict = {"cv_f1_mean": 0.8, "cv_f1_std": 0.01}
SUMMARY_METRICS: dict = {"f1": 0.83, "loss": 0.4}

# 非法 eval_id：缺省/None、latest、短前缀、跨类别、r0、前导零、非字符串、空串。
BAD_EVAL_IDS = [
    None,
    "latest",
    "eval-latest",
    "eval-v4.1",
    "model-v4.1-r1",
    "data-v4.1-r1",
    "train-v4.1-r1",
    "eval-v4.1-r0",
    "eval-v4.1-r01",
    41,
    "",
]

BAD_MODEL_IDS = [
    None,
    "latest",
    "model-v4.1",
    "data-v4.1-r1",
    "model-v4.1-r0",
    7,
]

BAD_DATA_VERSIONS = [
    None,
    "latest",
    "data-v4.1",
    "prompt-v4.1-r1",
    "data-v4.1-r0",
    9,
]

# 非法 fold 编号：越界、负数、字符串、bool（True 是 int 子类，须显式拒绝）、
# None、float。
BAD_FOLDS = [3, -1, "0", True, False, None, 2.0]

# 非法 model_version_number：非 int、bool、零、负数、float、字符串。
BAD_MODEL_VERSION_NUMBERS = [None, "3", True, 0, -1, 2.5]

# 典型单引号布尔注入串（P3 回归的代表性畸形输入）。
INJECTION_EVAL_ID = "eval-v4.1-r1' OR '1'='1"

# P3 回归（B6 复审同型）：含引号/注入样式的畸形 eval_id。修复前读路径
# 入口若不校验 eval_id 即拼 MLflow filter_string：单引号族在 MLflow 查询
# 解析器抛 MlflowException（域校验泄漏为底层异常）；双引号/尾随换行族被
# 静默当作"不存在"；非字符串同理。修复后读路径入口先 parse_eval_id，
# 一律 InvalidIdentifier。
MALFORMED_QUOTED_EVAL_IDS = [
    INJECTION_EVAL_ID,      # 单引号布尔注入（修复前 -> MlflowException）
    "eval-v4.1-r1'; --",    # 单引号 + SQL 注释（修复前 -> MlflowException）
    "eval-v'4.1'-r1",       # 协议段内嵌单引号（修复前 -> MlflowException）
    'eval-v4.1-r1"',        # 双引号（修复前 -> 静默 EvalRecordNotFound）
    "eval-v4.1-r1\n",       # 尾随换行（修复前 -> 静默 EvalRecordNotFound）
    None,                   # 非字符串（修复前 -> EvalRecordNotFound）
    41,                     # 非字符串（修复前 -> EvalRecordNotFound）
]


# —————————————————— fixtures 与 helpers ——————————————————


@pytest.fixture()
def store(tmp_path: Path) -> EvalRecordStore:
    """每个用例独立 tmp_path store（SQLite + 本地 artifacts，真实 MLflow）。"""
    return open_eval_store(tmp_path / "mlflow")


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    """已封存 development data-v4.1-r1 的 release 根（真实 data_release）。"""
    root = _make_data_base(tmp_path)
    _seal_data(root, DATA_VERSION, purpose="development")
    return root


@pytest.fixture()
def holdout_root(tmp_path: Path) -> Path:
    """已封存 purpose=holdout data-v4.1-r9 的 release 根（含隔离子目录）。"""
    root = _make_data_base(tmp_path)
    _seal_data(root, DATA_VERSION, purpose="development")
    _seal_data(root, HOLDOUT_DATA_VERSION, purpose="holdout")
    return root


def _make_data_base(tmp_path: Path) -> Path:
    base = tmp_path / "data"
    (base / "working").mkdir(parents=True)
    (base / "release_staging").mkdir()
    (base / "releases").mkdir()
    return base


def _make_working(root: Path, name: str) -> Path:
    working = root / "working" / name
    (working / "media").mkdir(parents=True)
    (working / "media" / "clip.mp4").write_bytes(b"\x00\x01")
    return working


def _seal_data(root: Path, version: str, *, purpose: str) -> tuple[str, Path]:
    """working -> staging -> releases，真实封存一个 data 版本。"""
    working_name = f"round-{purpose}"
    _make_working(root, working_name)
    version = stage_release(root, working_name, "v4.1", version=version)
    if purpose == "holdout":
        splits: dict = {"test": {"train": 0, "validation": 2}}
    else:
        splits = {"fold0": {"train": 1, "validation": 1}}
    release_dir = seal_release(
        root,
        version,
        purpose=purpose,
        description=f"{purpose} 正式测评数据",
        sample_count=2,
        source_batches=["batch-2026-07"],
        splits=splits,
    )
    return version, release_dir


def _create(
    store: EvalRecordStore,
    data_root: Path,
    eval_id: str = EVAL_ID,
    **overrides: object,
) -> EvalRunRecord:
    inputs: dict = {
        "model_id": MODEL_ID,
        "model_version_number": MODEL_VERSION_NUMBER,
        "data_version": DATA_VERSION,
        "config": CONFIG,
        "git_commit": GIT_COMMIT,
        "scope": "cross_validation",
        "split": None,
        "data_root": data_root,
        "pre_registration": None,
        "executor": None,
    }
    inputs.update(overrides)
    _ensure_registry_model(
        store,
        data_root,
        inputs["model_id"],
        inputs["model_version_number"],
    )
    return create_eval_run(store, eval_id, **inputs)


def _ensure_registry_model(
    store: EvalRecordStore,
    data_root: Path,
    model_id: str,
    model_version_number: int,
) -> None:
    """低层 eval 用例显式准备其所引用的 Registry 数值版本。"""
    if (
        not isinstance(model_id, str)
        or not isinstance(model_version_number, int)
        or isinstance(model_version_number, bool)
        or model_version_number < 1
    ):
        return
    client = _client(store)
    try:
        client.get_registered_model("mVllm2")
    except Exception:
        client.create_registered_model("mVllm2")
    existing = list(client.search_model_versions("name='mVllm2'"))
    by_number = {int(item.version): item for item in existing}
    while model_version_number not in by_number:
        next_number = len(by_number) + 1
        next_model_id = model_id if next_number == model_version_number else f"model-v4.1-r{900 + next_number}"
        train_id = f"train-v4.1-r{800 + next_number}"
        train_store = open_train_store(store.root)
        train = create_train_run(
            train_store,
            train_id,
            data_version=DATA_VERSION,
            prompt_version="prompt-v4.1-r1",
            git_commit=GIT_COMMIT,
            base_model="base/model",
            config={"epochs": 1},
        )
        for fold in REQUIRED_FOLDS:
            create_train_fold_run(train_store, train_id, fold)
            log_train_fold_metrics(train_store, train_id, fold, {"loss": 0.1})
            end_train_fold_run(train_store, train_id, fold, "FINISHED")
        log_train_summary(train_store, train_id, {"mean_loss": 0.1})
        train = transition_train_state(train_store, train_id, "completed")
        created = client.create_model_version(
            name="mVllm2",
            source=train_store.artifact_location,
            run_id=train.run_id,
            tags={
                "model_id": next_model_id,
                "train_id": train_id,
                "data_version": DATA_VERSION,
                "prompt_version": "prompt-v4.1-r1",
                "git_commit": GIT_COMMIT,
                "record_validity": "valid",
            },
        )
        by_number[int(created.version)] = created


def _create_fold(
    store: EvalRecordStore,
    eval_id: str = EVAL_ID,
    fold: int = 0,
    **overrides: object,
) -> EvalFoldRecord:
    bindings: dict = dict(FOLD_BINDINGS[fold])
    bindings.update(overrides)
    return create_eval_fold_run(store, eval_id, fold, **bindings)


def _finish_folds(
    store: EvalRecordStore,
    eval_id: str = EVAL_ID,
    folds: tuple[int, ...] = REQUIRED_FOLDS,
) -> None:
    for fold in folds:
        _create_fold(store, eval_id, fold)
        log_eval_fold_metrics(store, eval_id, fold, FOLD_METRICS[fold])
        end_eval_fold_run(store, eval_id, fold, "FINISHED")


def _aggregate(
    store: EvalRecordStore,
    eval_id: str = EVAL_ID,
    folds: tuple[int, ...] = REQUIRED_FOLDS,
    metrics: dict | None = None,
) -> EvalRunRecord:
    return log_eval_aggregate(
        store, eval_id, metrics or AGGREGATE_METRICS, folds=folds
    )


def _complete_cv(
    store: EvalRecordStore,
    data_root: Path,
    eval_id: str = EVAL_ID,
    outcome: str = "passed",
) -> EvalRunRecord:
    _create(store, data_root, eval_id)
    _finish_folds(store, eval_id)
    _aggregate(store, eval_id)
    return transition_eval_state(store, eval_id, "completed", outcome=outcome)


def _complete_single(
    store: EvalRecordStore,
    data_root: Path,
    eval_id: str = EVAL_ID,
    fold: int = 0,
    outcome: str = "passed",
) -> EvalRunRecord:
    _create(store, data_root, eval_id, scope="single_fold", split=SPLIT)
    _create_fold(store, eval_id, fold)
    log_eval_fold_metrics(store, eval_id, fold, FOLD_METRICS[fold])
    end_eval_fold_run(store, eval_id, fold, "FINISHED")
    log_eval_summary(store, eval_id, SUMMARY_METRICS)
    return transition_eval_state(store, eval_id, "completed", outcome=outcome)


def _complete_full(
    store: EvalRecordStore,
    data_root: Path,
    eval_id: str = EVAL_ID,
    outcome: str = "passed",
) -> EvalRunRecord:
    _create(store, data_root, eval_id, scope="full", split=HOLDOUT_SPLIT)
    log_eval_summary(store, eval_id, SUMMARY_METRICS)
    return transition_eval_state(store, eval_id, "completed", outcome=outcome)


def _prepare_eval_state(
    store: EvalRecordStore, data_root: Path, state: str
) -> EvalRunRecord:
    """把 eval-v4.1-r1 经合法路径置于指定 workflow_state。"""
    if state in ("completed", "archived"):
        completed = _complete_cv(store, data_root)
        if state == "archived":
            return transition_eval_state(store, EVAL_ID, "archived")
        return completed
    record = _create(store, data_root)
    if state == "running":
        return record
    return transition_eval_state(
        store,
        EVAL_ID,
        state,
        run_status="FAILED" if state == "failed" else "KILLED",
    )


def _client(store: EvalRecordStore) -> MlflowClient:
    """raw MLflow 读回通道（真实集成断言；篡改模拟"人工或异常操作"）。"""
    return MlflowClient(tracking_uri=store.tracking_uri)


def _raw_run(store: EvalRecordStore, run_id: str):
    return _client(store).get_run(run_id)


def _children(store: EvalRecordStore, parent_run_id: str) -> list:
    """按 §2.7/§2.8 的嵌套子 Run 查询方式（parentRunId tag filter）。"""
    return list(
        _client(store).search_runs(
            [store.experiment_id],
            filter_string=f"tags.mlflow.parentRunId = '{parent_run_id}'",
            max_results=100,
        )
    )


def _evals(store: EvalRecordStore, eval_id: str) -> list:
    return list(
        _client(store).search_runs(
            [store.experiment_id],
            filter_string=f"tags.eval_id = '{eval_id}'",
            max_results=100,
        )
    )


def _all_runs(store: EvalRecordStore) -> list:
    """store 实验内全部活动 Run（“无 Run 产生”断言用）。"""
    return list(_client(store).search_runs([store.experiment_id], max_results=100))


def _inject_child(
    store: EvalRecordStore, parent_run_id: str, **tags: str
) -> str:
    """raw 直建子 Run（模拟篡改/异常操作），返回 run_id。"""
    merged = {"mlflow.parentRunId": parent_run_id, **tags}
    run = _client(store).create_run(
        experiment_id=store.experiment_id,
        run_name=merged.get("mlflow.runName", "injected"),
        tags=merged,
    )
    return run.info.run_id


def _write_pre_registration(path: Path, **overrides: object) -> Path:
    """写一份合法 pre_registration.yaml（§5.6 必填字段齐全）。"""
    data: dict = {
        "eval_version": EVAL_ID,
        "model_version": MODEL_ID,
        "data_version": HOLDOUT_DATA_VERSION,
        "split": HOLDOUT_SPLIT,
        "rules": "docs/eval-rules.md 冻结文本",
        "thresholds": {"accuracy": 0.9},
        "one_time": True,
        "tuning_use": "forbidden",
        "recovery": {"resume_requires": ["identity", "executor"]},
    }
    data.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _holdout_release_dir(holdout_root: Path) -> Path:
    return holdout_root / "releases" / HOLDOUT_DATA_VERSION


def _acquire_holdout_claim(
    holdout_root: Path,
    *,
    pre_registration: Path | None = None,
    eval_id: str = EVAL_ID,
    model_id: str = MODEL_ID,
    data_version: str = HOLDOUT_DATA_VERSION,
    split: str = HOLDOUT_SPLIT,
    executor: str = EXECUTOR,
):
    """staging 语义：首次模型调用前建立全局一次性 claim（holdout.acquire）。"""
    authorization = _holdout_release_dir(holdout_root) / "authorization"
    return acquire_claim(
        authorization,
        ClaimIdentity(
            eval_version=eval_id,
            model_version=model_id,
            data_version=data_version,
            split=split,
        ),
        executor,
        pre_registration_sha256=(
            hashlib.sha256(pre_registration.read_bytes()).hexdigest()
            if pre_registration is not None and pre_registration.is_file()
            else "0" * 64
        ),
    )


def _assert_combo_legal(record: EvalRunRecord) -> None:
    """快照组合必须落在 §5.3 固定表内（委托 versioning.state 的表）。"""
    allowed = ALLOWED_RUN_STATUSES[WorkflowState(record.workflow_state)]
    assert record.run_status in allowed

# —————————————————— T1 store 句柄与 D023 独立性 ——————————————————


class TestEvalRecordStore:
    def test_open_store_uses_local_sqlite_and_artifacts(self, tmp_path: Path) -> None:
        root = tmp_path / "mlflow"
        store = open_eval_store(root)
        assert isinstance(store, EvalRecordStore)
        assert store.root.resolve() == root.resolve()
        assert store.tracking_uri.startswith("sqlite:///")
        assert store.tracking_uri.endswith("mlflow.db")
        assert str(root) in store.tracking_uri
        assert (root / "mlflow.db").is_file()
        assert (root / "artifacts").is_dir()
        assert (
            Path(store.artifact_location).resolve()
            == (root / "artifacts").resolve()
        )

        experiment = _client(store).get_experiment(store.experiment_id)
        assert experiment.name == DEFAULT_EVAL_EXPERIMENT
        assert (
            Path(experiment.artifact_location).resolve()
            == (root / "artifacts").resolve()
        )

    def test_experiment_reused_by_name_and_new_name_creates_new(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "mlflow"
        first = open_eval_store(root)
        again = open_eval_store(root)
        assert again.experiment_id == first.experiment_id

        other = open_eval_store(root, experiment_name="other-evaluation")
        assert other.experiment_id != first.experiment_id

    def test_stores_are_isolated(self, tmp_path: Path, data_root: Path) -> None:
        # §2.6 不连正式 store；模块必须按 store 句柄寻址，双 store 互不可见
        store_a = open_eval_store(tmp_path / "a")
        store_b = open_eval_store(tmp_path / "b")
        assert (tmp_path / "a" / "mlflow.db").is_file()
        assert (tmp_path / "b" / "mlflow.db").is_file()

        _create(store_a, data_root)
        with pytest.raises(EvalRecordNotFound):
            get_eval_run(store_b, EVAL_ID)
        # B 中创建同 ID 不受 A 影响（不同 store，各自唯一）
        _create(store_b, data_root)

    def test_module_constants_pinned(self) -> None:
        assert DEFAULT_EVAL_EXPERIMENT == "mVllm2-evaluation"
        assert REQUIRED_FOLDS == (0, 1, 2)
        assert SCOPES == ("single_fold", "cross_validation", "full")
        assert OUTCOMES == ("passed", "failed")
        assert EVAL_ID_TAG == "eval_id"
        assert WORKFLOW_STATE_TAG == "workflow_state"
        assert RECORD_VALIDITY_TAG == "record_validity"
        assert MODEL_ID_TAG == "model_id"
        assert MODEL_VERSION_NUMBER_TAG == "model_version_number"
        assert DATA_VERSION_TAG == "data_version"
        assert CONFIG_TAG == "config"
        assert GIT_COMMIT_TAG == "git_commit"
        assert SCOPE_TAG == "scope"
        assert SPLIT_TAG == "split"
        assert OUTCOME_TAG == "outcome"
        assert SUMMARY_COMPLETE_TAG == "summary_complete"
        assert AGGREGATE_FOLDS_TAG == "aggregate_folds"
        assert FOLD_TAG == "fold"
        assert MODEL_ARTIFACT_TAG == "model_artifact"
        assert DATA_SPLIT_TAG == "data_split"
        assert SAMPLE_COUNT_TAG == "sample_count"
        assert RECORDS_TAG == "records"
        assert FAILURES_TAG == "failures"

    def test_eval_store_coexists_with_train_store_in_one_sqlite(
        self, tmp_path: Path, data_root: Path
    ) -> None:
        # D023/§2.8：eval 是独立父 Run——与训练实验同根共用同一 SQLite 文件，
        # 但 experiment_id 不同、按各自 ID tag 寻址互不可见、互不挂靠
        from versioning.mlflow_train import (
            create_train_run,
            get_train_run,
            open_train_store,
        )

        root = tmp_path / "mlflow"
        train_store = open_train_store(root)
        eval_store = open_eval_store(root)
        assert eval_store.experiment_id != train_store.experiment_id
        assert eval_store.tracking_uri == train_store.tracking_uri

        train = create_train_run(
            train_store,
            "train-v4.1-r1",
            data_version=DATA_VERSION,
            prompt_version="prompt-v4.1-r1",
            git_commit=GIT_COMMIT,
            base_model="MiniCPM-V-4.5",
            config={"epochs": 3},
        )
        record = _create(eval_store, data_root)

        # eval 父 Run 不嵌套在任何 Run 之下（不附着训练 Run）
        raw_eval = _raw_run(eval_store, record.run_id)
        assert "mlflow.parentRunId" not in raw_eval.data.tags
        # 训练父 Run 也未被动过
        raw_train = _raw_run(eval_store, train.run_id)
        assert raw_train.info.status == "RUNNING"
        assert "eval_id" not in raw_train.data.tags

        # 两实验按 tag 互不可见（eval_id 出现在训练实验查询为空，反之亦然）
        client = _client(eval_store)
        assert (
            list(
                client.search_runs(
                    [train_store.experiment_id],
                    filter_string=f"tags.{EVAL_ID_TAG} = '{EVAL_ID}'",
                    max_results=10,
                )
            )
            == []
        )
        assert (
            list(
                client.search_runs(
                    [eval_store.experiment_id],
                    filter_string="tags.train_id = 'train-v4.1-r1'",
                    max_results=10,
                )
            )
            == []
        )

        # 各自入口均可独立检索
        assert get_train_run(train_store, "train-v4.1-r1").run_id == train.run_id
        assert get_eval_run(eval_store, EVAL_ID).run_id == record.run_id


# —————————————————— T2 父 Run 创建（显式 ID + 引用 tags）——————————————————


class TestCreateEvalRun:
    def test_direct_api_rejects_missing_registry_model(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        with pytest.raises(IllegalEvalRecord, match="Registry"):
            create_eval_run(
                store,
                EVAL_ID,
                model_id=MODEL_ID,
                model_version_number=MODEL_VERSION_NUMBER,
                data_version=DATA_VERSION,
                config=CONFIG,
                git_commit=GIT_COMMIT,
                scope="cross_validation",
                data_root=data_root,
            )
        assert _all_runs(store) == []

    def test_create_records_explicit_id_references_and_tags(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)

        # 返回快照：显式 ID + 五类显式引用 + 初始 running/RUNNING/valid
        assert isinstance(record, EvalRunRecord)
        assert record.eval_id == EVAL_ID
        assert record.run_name == EVAL_ID
        assert record.experiment_id == store.experiment_id
        assert record.workflow_state == "running"
        assert record.run_status == "RUNNING"
        assert record.record_validity == "valid"
        assert record.model_id == MODEL_ID
        assert record.model_version_number == MODEL_VERSION_NUMBER
        assert record.data_version == DATA_VERSION
        assert record.config == CONFIG
        assert record.git_commit == GIT_COMMIT
        assert record.scope == "cross_validation"
        assert record.split is None
        assert record.outcome is None
        assert record.folds == {}
        assert dict(record.metrics) == {}
        _assert_combo_legal(record)

        # raw MLflow 读回：引用 tags / 原生状态 / run_name（§2.8 显式引用）
        raw = _raw_run(store, record.run_id)
        assert raw.info.status == "RUNNING"
        assert raw.info.experiment_id == store.experiment_id
        assert raw.data.tags["eval_id"] == EVAL_ID
        assert raw.data.tags["workflow_state"] == "running"
        assert raw.data.tags["record_validity"] == "valid"
        assert raw.data.tags["model_id"] == MODEL_ID
        assert raw.data.tags["model_version_number"] == "1"
        assert raw.data.tags["data_version"] == DATA_VERSION
        assert raw.data.tags["config"] == CONFIG
        assert raw.data.tags["git_commit"] == GIT_COMMIT
        assert raw.data.tags["scope"] == "cross_validation"
        assert raw.data.tags["mlflow.runName"] == EVAL_ID
        # split/outcome 未声明不写 tag；独立父 Run 不携带 parentRunId（D023）
        assert "split" not in raw.data.tags
        assert "outcome" not in raw.data.tags
        assert "mlflow.parentRunId" not in raw.data.tags
        assert dict(raw.data.metrics) == {}
        assert dict(raw.data.params) == {}

    def test_split_recorded_when_provided(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root, scope="single_fold", split=SPLIT)
        assert record.split == SPLIT
        assert _raw_run(store, record.run_id).data.tags["split"] == SPLIT

        # cross_validation 允许携带整体 split 声明（不强制）
        other = _create(store, data_root, OTHER_EVAL_ID, split="validation")
        assert other.split == "validation"
        assert _raw_run(store, other.run_id).data.tags["split"] == "validation"

    def test_multiple_eval_ids_coexist_in_one_store(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _create(store, data_root, EVAL_ID)
        _create(store, data_root, OTHER_EVAL_ID)

        assert get_eval_run(store, EVAL_ID).eval_id == EVAL_ID
        assert get_eval_run(store, OTHER_EVAL_ID).eval_id == OTHER_EVAL_ID
        assert len(_evals(store, EVAL_ID)) == 1
        assert len(_evals(store, OTHER_EVAL_ID)) == 1

    @pytest.mark.parametrize("bad_eval_id", BAD_EVAL_IDS)
    def test_missing_or_illegal_eval_id_rejected(
        self, store: EvalRecordStore, data_root: Path, bad_eval_id: object
    ) -> None:
        # 显式版本纪律（§9/§11.6）：缺省/None 与非法一律 InvalidIdentifier，
        # 不自动分配、不静默纠正；无 Run 产生
        with pytest.raises(InvalidIdentifier):
            _create(store, data_root, bad_eval_id)
        assert _all_runs(store) == []

    @pytest.mark.parametrize("bad_model_id", BAD_MODEL_IDS)
    def test_illegal_model_id_rejected(
        self, store: EvalRecordStore, data_root: Path, bad_model_id: object
    ) -> None:
        # 非法引用 fail-closed（契约要点 2）：model_id 必须经 parse_model_id
        with pytest.raises(InvalidIdentifier):
            _create(store, data_root, model_id=bad_model_id)
        assert _all_runs(store) == []

    @pytest.mark.parametrize("bad_data_version", BAD_DATA_VERSIONS)
    def test_illegal_data_version_rejected(
        self, store: EvalRecordStore, data_root: Path, bad_data_version: object
    ) -> None:
        with pytest.raises(InvalidIdentifier):
            _create(store, data_root, data_version=bad_data_version)
        assert _all_runs(store) == []

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("model_version_number", None),
            ("model_version_number", "3"),
            ("model_version_number", True),
            ("model_version_number", 0),
            ("model_version_number", -1),
            ("model_version_number", 2.5),
            ("config", None),
            ("config", ""),
            ("config", 42),
            ("git_commit", None),
            ("git_commit", ""),
            ("scope", None),
            ("scope", ""),
            ("scope", "bogus"),
            ("scope", "crossvalidation"),
            ("scope", "full_data"),
            ("scope", 41),
        ],
    )
    def test_illegal_scalar_references_rejected(
        self,
        store: EvalRecordStore,
        data_root: Path,
        field: str,
        bad_value: object,
    ) -> None:
        # 数值 Model Version / 配置引用 / Git commit / scope 全部 fail-closed
        with pytest.raises(IllegalEvalRecord):
            _create(store, data_root, **{field: bad_value})
        assert _all_runs(store) == []

    @pytest.mark.parametrize(
        ("scope", "bad_split"),
        [
            ("single_fold", None),
            ("single_fold", ""),
            ("single_fold", 3),
            ("full", None),
            ("full", ""),
        ],
    )
    def test_split_required_for_single_and_full_scopes(
        self, store: EvalRecordStore, data_root: Path, scope: str, bad_split: object
    ) -> None:
        # §5.5：single_fold/full 必须声明明确 split（full 为独立验收 split）
        with pytest.raises(IllegalEvalRecord):
            _create(store, data_root, scope=scope, split=bad_split)
        assert _all_runs(store) == []

    def test_data_release_reference_must_exist_fail_closed(
        self, store: EvalRecordStore, tmp_path: Path
    ) -> None:
        # §7：正式测评引用的 data 版本必须已封存；缺失/staging-only 一律
        # fail-closed（模块无 release 无法判定 purpose，见语义决策点 2）
        empty_root = _make_data_base(tmp_path)
        with pytest.raises(IllegalEvalRecord):
            _create(store, empty_root, data_version=DATA_VERSION)
        with pytest.raises(IllegalEvalRecord):
            _create(store, empty_root, data_version=MISSING_DATA_VERSION)
        assert _all_runs(store) == []

        # 仅 staging 未封存同样不算存在
        _make_working(empty_root, "round-staged")
        stage_release(empty_root, "round-staged", "v4.1", version=MISSING_DATA_VERSION)
        with pytest.raises(IllegalEvalRecord):
            _create(store, empty_root, data_version=MISSING_DATA_VERSION)
        assert _all_runs(store) == []

    def test_duplicate_eval_id_conflict_and_original_untouched(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        first = _create(store, data_root)

        # §8/§11.6：同名冲突拒绝；即使第二次输入不同也以 ID 唯一性优先
        with pytest.raises(EvalRunConflict):
            _create(store, data_root, split="validation")

        # 原 Run 唯一且内容不动（包括未获得第二次调用的 split 声明）
        assert len(_evals(store, EVAL_ID)) == 1
        raw = _raw_run(store, first.run_id)
        assert raw.info.status == "RUNNING"
        assert raw.data.tags["workflow_state"] == "running"
        assert "split" not in raw.data.tags
        assert get_eval_run(store, EVAL_ID).run_id == first.run_id

    def test_deleted_eval_run_still_conflicts(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # ViewType.ALL 语义：已删除 Run 仍占名，不得借删除后重建同 ID
        first = _create(store, data_root)
        _client(store).delete_run(first.run_id)
        with pytest.raises(EvalRunConflict):
            _create(store, data_root)

    def test_domain_errors_share_base_class(self) -> None:
        # 域异常统一挂 MLflowEvalError(ValueError)，便于上游兜底
        for exc in (
            EvalRecordNotFound,
            EvalRunConflict,
            IllegalEvalRecord,
            IncompleteEvalRecord,
            InvalidEvalRecord,
            HoldoutAuthorizationError,
        ):
            assert issubclass(exc, MLflowEvalError)
            assert issubclass(exc, ValueError)


# —————————————————— T3 fold 子 Run（绑定/指标/终态/恢复）——————————————————


class TestEvalFoldRuns:
    def test_three_folds_are_nested_children_with_bindings(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §5.5/D023：cross_validation 的 fold0–2 为嵌套子 Run，每 fold 记录
        # 模型 artifact、数据 split、样本数、records/failures 路径
        record = _create(store, data_root)
        fold_records = [_create_fold(store, fold=fold) for fold in REQUIRED_FOLDS]

        assert [f.fold for f in fold_records] == [0, 1, 2]
        assert set(record.folds) == set()
        assert set(get_eval_run(store, EVAL_ID).folds) == {0, 1, 2}

        for fold_record in fold_records:
            bindings = FOLD_BINDINGS[fold_record.fold]
            assert isinstance(fold_record, EvalFoldRecord)
            assert fold_record.eval_id == EVAL_ID
            assert fold_record.parent_run_id == record.run_id
            assert fold_record.run_name == f"fold{fold_record.fold}"
            assert fold_record.status == "RUNNING"
            assert fold_record.model_artifact == bindings["model_artifact"]
            assert fold_record.data_split == bindings["data_split"]
            assert fold_record.sample_count == bindings["sample_count"]
            assert fold_record.records == bindings["records"]
            assert fold_record.failures == bindings["failures"]
            assert dict(fold_record.metrics) == {}

            # raw 读回：嵌套关联、fold 标识、五个绑定 tags（sample_count str 化）
            raw = _raw_run(store, fold_record.run_id)
            assert raw.info.status == "RUNNING"
            assert raw.data.tags["mlflow.parentRunId"] == record.run_id
            assert raw.data.tags["fold"] == f"fold{fold_record.fold}"
            assert raw.data.tags["mlflow.runName"] == f"fold{fold_record.fold}"
            assert raw.data.tags["model_artifact"] == bindings["model_artifact"]
            assert raw.data.tags["data_split"] == bindings["data_split"]
            assert raw.data.tags["sample_count"] == str(bindings["sample_count"])
            assert raw.data.tags["records"] == bindings["records"]
            assert raw.data.tags["failures"] == bindings["failures"]
            # 权威在父 Run：子 Run 不携带 workflow_state / record_validity
            assert "workflow_state" not in raw.data.tags
            assert "record_validity" not in raw.data.tags

        # 按 parentRunId filter 应恰好命中三折
        children = _children(store, record.run_id)
        assert {child.data.tags["fold"] for child in children} == {
            "fold0",
            "fold1",
            "fold2",
        }
        assert len(children) == 3

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("model_artifact", None),
            ("model_artifact", ""),
            ("data_split", None),
            ("data_split", ""),
            ("records", None),
            ("records", ""),
            ("failures", None),
            ("failures", ""),
            ("sample_count", None),
            ("sample_count", -1),
            ("sample_count", True),
            ("sample_count", "425"),
            ("sample_count", 2.5),
        ],
    )
    def test_illegal_fold_bindings_rejected(
        self,
        store: EvalRecordStore,
        data_root: Path,
        field: str,
        bad_value: object,
    ) -> None:
        # 绑定五字段 fail-closed：缺失/空串/类型非法一律拒绝，无子 Run 产生
        _create(store, data_root)
        with pytest.raises(IllegalEvalRecord):
            _create_fold(store, **{field: bad_value})
        assert get_eval_run(store, EVAL_ID).folds == {}

    @pytest.mark.parametrize("bad_fold", BAD_FOLDS)
    def test_illegal_fold_number_rejected(
        self, store: EvalRecordStore, data_root: Path, bad_fold: object
    ) -> None:
        _create(store, data_root)
        with pytest.raises(IllegalEvalRecord):
            create_eval_fold_run(store, EVAL_ID, bad_fold, **FOLD_BINDINGS[0])
        assert get_eval_run(store, EVAL_ID).folds == {}

    def test_duplicate_fold_rejected_and_original_untouched(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _create(store, data_root)
        first = _create_fold(store, fold=0)

        with pytest.raises(EvalRunConflict):
            _create_fold(store, fold=0)

        # 标识无重复：fold0 子 Run 仍唯一、原绑定与状态不动
        fold0_children = [
            child
            for child in _children(store, first.parent_run_id)
            if child.data.tags.get("fold") == "fold0"
        ]
        assert len(fold0_children) == 1
        assert fold0_children[0].info.run_id == first.run_id
        raw = _raw_run(store, first.run_id)
        assert raw.info.status == "RUNNING"
        assert raw.data.tags["model_artifact"] == FOLD_BINDINGS[0]["model_artifact"]

    def test_full_scope_rejects_any_fold(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §5.5：full-data 引用独立验收 split，不设 fold 绑定
        _create(store, data_root, scope="full", split=HOLDOUT_SPLIT)
        with pytest.raises(IllegalEvalRecord):
            _create_fold(store, fold=0)
        assert get_eval_run(store, EVAL_ID).folds == {}

    def test_single_fold_allows_exactly_one_binding(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §5.5：single_fold 只允许一个 fold 绑定
        _create(store, data_root, scope="single_fold", split=SPLIT)
        first = _create_fold(store, fold=0)

        # 同 fold 重复 -> EvalRunConflict（标识无重复）
        with pytest.raises(EvalRunConflict):
            _create_fold(store, fold=0)
        # 另一编号 fold -> 违反"只允许一个 fold 绑定"
        with pytest.raises(IllegalEvalRecord):
            _create_fold(store, fold=1)

        folds = get_eval_run(store, EVAL_ID).folds
        assert set(folds) == {0}
        assert folds[0].run_id == first.run_id

    def test_missing_folds_observed_in_snapshot(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 缺 fold 检测：只建 fold0/fold2，快照如实反映缺口（运行中合法；
        # 完整性由 completed 门拒绝，见 T4）
        _create(store, data_root)
        _create_fold(store, fold=0)
        _create_fold(store, fold=2)

        folds = get_eval_run(store, EVAL_ID).folds
        assert set(folds) == {0, 2}
        ordered = list_eval_fold_runs(store, EVAL_ID)
        assert [f.fold for f in ordered] == [0, 2]

        with pytest.raises(EvalRecordNotFound):
            # fold1 子 Run 不存在（不是 fold 集合的一部分）
            log_eval_fold_metrics(store, EVAL_ID, 1, FOLD_METRICS[1])

    def test_fold_metrics_recorded_on_child_run(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _create(store, data_root)
        _create_fold(store, fold=0)
        log_eval_fold_metrics(store, EVAL_ID, 0, FOLD_METRICS[0])

        fold_record = list_eval_fold_runs(store, EVAL_ID)[0]
        assert dict(fold_record.metrics) == FOLD_METRICS[0]
        assert _raw_run(store, fold_record.run_id).data.metrics == FOLD_METRICS[0]

        # 多批指标取最新值（MLflow 语义），且不落在父 Run 上
        log_eval_fold_metrics(store, EVAL_ID, 0, {"fold_f1": 0.83})
        fold_record = list_eval_fold_runs(store, EVAL_ID)[0]
        assert fold_record.metrics["fold_f1"] == 0.83
        assert fold_record.metrics["fold_loss"] == FOLD_METRICS[0]["fold_loss"]
        assert dict(get_eval_run(store, EVAL_ID).metrics) == {}

    @pytest.mark.parametrize(
        "bad_metrics",
        [{}, {"": 0.5}, {"f1": None}, {"f1": True}, {"f1": "0.9"}, {"f1": [0.9]}],
    )
    def test_illegal_fold_metrics_rejected(
        self, store: EvalRecordStore, data_root: Path, bad_metrics: dict
    ) -> None:
        _create(store, data_root)
        _create_fold(store, fold=0)
        with pytest.raises(IllegalEvalRecord):
            log_eval_fold_metrics(store, EVAL_ID, 0, bad_metrics)

    def test_end_fold_run_explicit_status(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _create(store, data_root)
        _create_fold(store, fold=0)
        ended = end_eval_fold_run(store, EVAL_ID, 0, "FINISHED", metrics={"final_f1": 0.9})

        assert ended.status == "FINISHED"
        assert dict(ended.metrics) == {"final_f1": 0.9}
        assert _raw_run(store, ended.run_id).info.status == "FINISHED"
        assert _raw_run(store, ended.run_id).data.metrics["final_f1"] == 0.9

    def test_end_fold_run_rejects_illegal_status_and_terminal_rerun(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _create(store, data_root)
        _create_fold(store, fold=0)

        for bad_status in ("RUNNING", "SCHEDULED", "bogus", ""):
            with pytest.raises(IllegalEvalRecord):
                end_eval_fold_run(store, EVAL_ID, 0, bad_status)

        end_eval_fold_run(store, EVAL_ID, 0, "FINISHED")
        # 已终态子 Run 不得重复终转（含换终态）
        with pytest.raises(IllegalEvalRecord):
            end_eval_fold_run(store, EVAL_ID, 0, "FINISHED")
        with pytest.raises(IllegalEvalRecord):
            end_eval_fold_run(store, EVAL_ID, 0, "FAILED")
        assert (
            _raw_run(store, list_eval_fold_runs(store, EVAL_ID)[0].run_id).info.status
            == "FINISHED"
        )

    def test_end_fold_run_failed_and_killed(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _create(store, data_root)
        _create_fold(store, fold=0)
        _create_fold(store, fold=1)

        failed = end_eval_fold_run(store, EVAL_ID, 0, "FAILED")
        killed = end_eval_fold_run(store, EVAL_ID, 1, "KILLED")
        assert failed.status == "FAILED"
        assert killed.status == "KILLED"
        assert _raw_run(store, failed.run_id).info.status == "FAILED"
        assert _raw_run(store, killed.run_id).info.status == "KILLED"

    def test_resume_fold_run_controlled_recovery(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §5.6 恢复规则：FAILED/KILLED 子 Run 经原 Run ID 恢复 RUNNING
        _create(store, data_root)
        crashed = _create_fold(store, fold=0)
        end_eval_fold_run(store, EVAL_ID, 0, "FAILED")
        killed = _create_fold(store, fold=1)
        end_eval_fold_run(store, EVAL_ID, 1, "KILLED")
        fresh = _create_fold(store, fold=2)

        resumed = resume_eval_fold_run(store, EVAL_ID, 0)
        assert resumed.run_id == crashed.run_id
        assert resumed.status == "RUNNING"
        assert _raw_run(store, crashed.run_id).info.status == "RUNNING"
        assert resumed.fold == 0

        resumed_killed = resume_eval_fold_run(store, EVAL_ID, 1)
        assert resumed_killed.run_id == killed.run_id
        assert resumed_killed.status == "RUNNING"

        # FINISHED 不得恢复；RUNNING 无需恢复
        end_eval_fold_run(store, EVAL_ID, 0, "FINISHED")
        with pytest.raises(IllegalEvalRecord):
            resume_eval_fold_run(store, EVAL_ID, 0)
        with pytest.raises(IllegalEvalRecord):
            resume_eval_fold_run(store, EVAL_ID, 2)
        assert _raw_run(store, fresh.run_id).info.status == "RUNNING"

    def test_fold_operations_require_running_parent(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        transition_eval_state(store, EVAL_ID, "partial", run_status="KILLED")
        with pytest.raises(IllegalEvalRecord):
            _create_fold(store, fold=0)
        assert get_eval_run(store, EVAL_ID).folds == {}

        # 受控恢复后可建；completed 后不得原地重跑（§5.3 纪律同样适用 eval）
        transition_eval_state(store, EVAL_ID, "running")
        _finish_folds(store)
        _aggregate(store)
        transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        with pytest.raises(IllegalEvalRecord):
            _create_fold(store, fold=0)
        assert set(get_eval_run(store, EVAL_ID).folds) == {0, 1, 2}
        assert record.run_id == get_eval_run(store, EVAL_ID).run_id

    @pytest.mark.parametrize(
        "operation",
        [
            lambda store: get_eval_run(store, UNKNOWN_EVAL_ID),
            lambda store: list_eval_fold_runs(store, UNKNOWN_EVAL_ID),
            lambda store: create_eval_fold_run(
                store, UNKNOWN_EVAL_ID, 0, **FOLD_BINDINGS[0]
            ),
            lambda store: log_eval_fold_metrics(
                store, UNKNOWN_EVAL_ID, 0, FOLD_METRICS[0]
            ),
            lambda store: end_eval_fold_run(store, UNKNOWN_EVAL_ID, 0, "FINISHED"),
            lambda store: resume_eval_fold_run(store, UNKNOWN_EVAL_ID, 0),
            lambda store: log_eval_summary(store, UNKNOWN_EVAL_ID, SUMMARY_METRICS),
            lambda store: log_eval_aggregate(
                store, UNKNOWN_EVAL_ID, AGGREGATE_METRICS, folds=REQUIRED_FOLDS
            ),
            lambda store: transition_eval_state(
                store, UNKNOWN_EVAL_ID, "completed", outcome="passed"
            ),
            lambda store: mark_eval_invalid(store, UNKNOWN_EVAL_ID),
            lambda store: validate_eval_for_conclusion(store, UNKNOWN_EVAL_ID),
        ],
    )
    def test_unknown_eval_operations_raise_not_found(
        self, store: EvalRecordStore, data_root: Path, operation
    ) -> None:
        _create(store, data_root)  # store 可用但目标 eval 不存在
        with pytest.raises(EvalRecordNotFound):
            operation(store)


# —————————————————— T4 三种 scope 与 completed/结论门 ——————————————————


class TestScopesAndCompletionGate:
    def test_cross_validation_completes_with_three_folds_and_aggregate(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        fold_run_ids: dict[int, str] = {}
        for fold in REQUIRED_FOLDS:
            fold_record = _create_fold(store, fold=fold)
            fold_run_ids[fold] = fold_record.run_id
            log_eval_fold_metrics(store, EVAL_ID, fold, FOLD_METRICS[fold])
            end_eval_fold_run(store, EVAL_ID, fold, "FINISHED")
        _aggregate(store)
        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")

        assert completed.workflow_state == "completed"
        assert completed.run_status == "FINISHED"
        assert completed.outcome == "passed"
        assert completed.run_id == record.run_id
        assert dict(completed.metrics) == AGGREGATE_METRICS
        _assert_combo_legal(completed)

        raw = _raw_run(store, record.run_id)
        assert raw.info.status == "FINISHED"
        assert raw.data.tags["workflow_state"] == "completed"
        assert raw.data.tags["outcome"] == "passed"
        assert raw.data.tags["summary_complete"] == "true"
        assert raw.data.tags["aggregate_folds"] == "fold0,fold1,fold2"
        assert dict(raw.data.metrics) == AGGREGATE_METRICS

        children = _children(store, record.run_id)
        assert len(children) == 3
        for child in children:
            fold = int(child.data.tags["fold"].removeprefix("fold"))
            assert child.info.run_id == fold_run_ids[fold]
            assert child.info.status == "FINISHED"
            assert dict(child.data.metrics) == FOLD_METRICS[fold]

        assert validate_eval_for_conclusion(store, EVAL_ID).run_id == record.run_id

    def test_single_fold_completes_with_one_fold_and_summary(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §5.5：单折模型正式测评记录一个 fold 绑定，汇总在父 Run
        completed = _complete_single(store, data_root)

        assert completed.workflow_state == "completed"
        assert completed.outcome == "passed"
        assert completed.scope == "single_fold"
        assert completed.split == SPLIT
        assert set(completed.folds) == {0}
        assert completed.folds[0].status == "FINISHED"
        assert dict(completed.metrics) == SUMMARY_METRICS
        # 单折口径无聚合
        assert "aggregate_folds" not in _raw_run(store, completed.run_id).data.tags

        validated = validate_eval_for_conclusion(store, EVAL_ID)
        assert validated.run_id == completed.run_id

    def test_full_scope_completes_without_folds_and_failed_outcome_is_valid_evidence(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §5.5：full 引用明确独立验收 split；§10：outcome=failed 仍是有效证据
        completed = _complete_full(store, data_root, outcome="failed")

        assert completed.scope == "full"
        assert completed.split == HOLDOUT_SPLIT
        assert completed.folds == {}
        assert completed.outcome == "failed"
        assert completed.workflow_state == "completed"
        assert completed.run_status == "FINISHED"

        raw = _raw_run(store, completed.run_id)
        assert raw.data.tags["outcome"] == "failed"
        assert raw.data.tags["summary_complete"] == "true"
        assert raw.data.tags["split"] == HOLDOUT_SPLIT

        validated = validate_eval_for_conclusion(store, EVAL_ID)
        assert validated.outcome == "failed"
        assert validated.run_id == completed.run_id

    def test_cv_missing_fold_blocks_completion_then_recovers_after_reaggregate(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 契约要点 3：cross-validation 缺 fold 拒绝；补折后聚合输入集合与
        # 观测集合不一致仍拒绝，须重聚合
        _create(store, data_root)
        _finish_folds(store, folds=(0, 1))

        # fold2 缺失：中途对已有两折聚合可行（输入集合 == 观测集合），
        # 但 completed 门因缺 fold2 拒绝
        _aggregate(store, folds=(0, 1))
        with pytest.raises(IncompleteEvalRecord):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        with pytest.raises(IncompleteEvalRecord):
            validate_eval_for_conclusion(store, EVAL_ID)
        assert get_eval_run(store, EVAL_ID).workflow_state == "running"

        # 补齐 fold2：aggregate_folds（fold0,fold1）与观测集合不一致，仍拒绝
        _create_fold(store, fold=2)
        log_eval_fold_metrics(store, EVAL_ID, 2, FOLD_METRICS[2])
        end_eval_fold_run(store, EVAL_ID, 2, "FINISHED")
        with pytest.raises(IncompleteEvalRecord):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")

        # 重新聚合（覆盖 aggregate_folds）后通过
        _aggregate(store, folds=REQUIRED_FOLDS)
        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        assert completed.workflow_state == "completed"
        assert validate_eval_for_conclusion(store, EVAL_ID).run_id == completed.run_id

    def test_cv_aggregate_input_set_must_match_observed_folds(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §5.5：聚合输入集合必须与声明的 fold 集合完全一致（多报/少报均拒绝）
        _create(store, data_root)
        _finish_folds(store, folds=(0, 1))

        with pytest.raises(IllegalEvalRecord):
            _aggregate(store, folds=REQUIRED_FOLDS)  # 多报未建 fold2
        with pytest.raises(IllegalEvalRecord):
            _aggregate(store, folds=(0,))  # 少报已建 fold1

        _create_fold(store, fold=2)
        end_eval_fold_run(store, EVAL_ID, 2, "FINISHED")
        _aggregate(store, folds=REQUIRED_FOLDS)
        raw = _raw_run(store, get_eval_run(store, EVAL_ID).run_id)
        assert raw.data.tags[AGGREGATE_FOLDS_TAG] == "fold0,fold1,fold2"

    @pytest.mark.parametrize("bad_status", ["RUNNING", "FAILED", "KILLED"])
    def test_cv_unfinished_fold_blocks_completion(
        self, store: EvalRecordStore, data_root: Path, bad_status: str
    ) -> None:
        # fold 未 FINISHED（RUNNING/FAILED/KILLED）均不完整
        _create(store, data_root)
        for fold in REQUIRED_FOLDS:
            _create_fold(store, fold=fold)
            if fold == 1 and bad_status == "RUNNING":
                continue
            end_eval_fold_run(
                store, EVAL_ID, fold, bad_status if fold == 1 else "FINISHED"
            )
        _aggregate(store)

        with pytest.raises(IncompleteEvalRecord):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        with pytest.raises(IncompleteEvalRecord):
            validate_eval_for_conclusion(store, EVAL_ID)
        assert get_eval_run(store, EVAL_ID).workflow_state == "running"

    def test_cv_missing_aggregate_blocks_completion(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 三折全 FINISHED 但无三折聚合：不得 completed，也不得形成结论
        _create(store, data_root)
        _finish_folds(store)

        with pytest.raises(IncompleteEvalRecord):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        with pytest.raises(IncompleteEvalRecord):
            validate_eval_for_conclusion(store, EVAL_ID)

        # 篡改 summary_complete tag 不能替代聚合（aggregate_folds 缺失仍拒绝）
        _client(store).set_tag(
            get_eval_run(store, EVAL_ID).run_id, SUMMARY_COMPLETE_TAG, "true"
        )
        with pytest.raises(IncompleteEvalRecord):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")

        _aggregate(store)
        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        assert completed.workflow_state == "completed"

    def test_cv_tampered_stale_aggregate_tag_blocks_gate_then_reaggregate_fixes(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _create(store, data_root)
        _finish_folds(store)
        _aggregate(store)

        # 篡改：聚合输入集改写为 fold0,fold1（不再是三折全量）
        _client(store).set_tag(
            get_eval_run(store, EVAL_ID).run_id, AGGREGATE_FOLDS_TAG, "fold0,fold1"
        )
        with pytest.raises(IncompleteEvalRecord):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        with pytest.raises(IncompleteEvalRecord):
            validate_eval_for_conclusion(store, EVAL_ID)

        # 完成前重记聚合（覆盖 tag）恢复；completed 后该口径不可再改
        _aggregate(store)
        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        assert completed.workflow_state == "completed"
        assert (
            _raw_run(store, completed.run_id).data.tags[AGGREGATE_FOLDS_TAG]
            == "fold0,fold1,fold2"
        )

    def test_summary_and_aggregate_are_scope_exclusive(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # cross_validation 只能聚合（三折口径），不收独立 summary
        _create(store, data_root)
        with pytest.raises(IllegalEvalRecord):
            log_eval_summary(store, EVAL_ID, SUMMARY_METRICS)

        # single_fold / full 只收 summary，不收聚合
        _create(store, data_root, OTHER_EVAL_ID, scope="single_fold", split=SPLIT)
        with pytest.raises(IllegalEvalRecord):
            log_eval_aggregate(store, OTHER_EVAL_ID, AGGREGATE_METRICS, folds=(0,))

        _create(store, data_root, "eval-v4.1-r3", scope="full", split=HOLDOUT_SPLIT)
        with pytest.raises(IllegalEvalRecord):
            log_eval_aggregate(
                store, "eval-v4.1-r3", AGGREGATE_METRICS, folds=REQUIRED_FOLDS
            )

    def test_outcome_required_and_validated_at_completion(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _create(store, data_root)
        _finish_folds(store)
        _aggregate(store)

        # completed 必须显式 outcome ∈ OUTCOMES（缺省/空/垃圾/非字符串拒绝）
        for bad_outcome in (None, "", "bogus", "PASS", 1):
            with pytest.raises(IllegalEvalRecord):
                transition_eval_state(store, EVAL_ID, "completed", outcome=bad_outcome)
        assert get_eval_run(store, EVAL_ID).workflow_state == "running"
        assert "outcome" not in _raw_run(store, get_eval_run(store, EVAL_ID).run_id).data.tags

        # 非 completed 目标不得携带 outcome（结论只在封存时冻结一次）
        with pytest.raises(IllegalEvalRecord):
            transition_eval_state(
                store, EVAL_ID, "partial", run_status="KILLED", outcome="passed"
            )

        # 合法 outcome 两个值均可完成
        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="failed")
        assert completed.outcome == "failed"

    def test_single_fold_zero_folds_or_missing_summary_blocks(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _create(store, data_root, scope="single_fold", split=SPLIT)

        # 零 fold：拒绝完成
        with pytest.raises(IncompleteEvalRecord):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")

        # 有 fold 且 FINISHED 但缺 summary：仍拒绝
        _create_fold(store, fold=0)
        end_eval_fold_run(store, EVAL_ID, 0, "FINISHED")
        with pytest.raises(IncompleteEvalRecord):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        with pytest.raises(IncompleteEvalRecord):
            validate_eval_for_conclusion(store, EVAL_ID)

        # 补 summary 后通过
        log_eval_summary(store, EVAL_ID, SUMMARY_METRICS)
        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        assert completed.workflow_state == "completed"

    def test_full_missing_summary_blocks(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _create(store, data_root, scope="full", split=HOLDOUT_SPLIT)
        with pytest.raises(IncompleteEvalRecord):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")

        log_eval_summary(store, EVAL_ID, SUMMARY_METRICS)
        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        assert completed.folds == {}
        assert completed.workflow_state == "completed"

    def test_gate_rejects_non_completed_states(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §10：workflow_state 非 completed|archived 一律拒绝（即使三折齐全）
        _create(store, data_root)
        _finish_folds(store)
        _aggregate(store)
        with pytest.raises(IncompleteEvalRecord):
            validate_eval_for_conclusion(store, EVAL_ID)

        transition_eval_state(store, EVAL_ID, "partial", run_status="FAILED")
        with pytest.raises(IncompleteEvalRecord):
            validate_eval_for_conclusion(store, EVAL_ID)
        # partial 父 Run 不可写汇总/聚合（须先受控恢复 running）
        with pytest.raises(IllegalEvalRecord):
            _aggregate(store)

    def test_archived_eval_passes_conclusion_gate(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §10 结论门接受 completed|archived
        _complete_cv(store, data_root)
        transition_eval_state(store, EVAL_ID, "archived")

        validated = validate_eval_for_conclusion(store, EVAL_ID)
        assert validated.workflow_state == "archived"
        assert validated.run_status == "FINISHED"
        assert validated.outcome == "passed"

    def test_completed_records_are_immutable(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §2.8：更换口径必须新建 eval-v...——completed 后父 Run 指标与
        # 结论不可再改写
        _complete_cv(store, data_root)
        with pytest.raises(IllegalEvalRecord):
            log_eval_aggregate(
                store, EVAL_ID, {"cv_f1_mean": 0.99}, folds=REQUIRED_FOLDS
            )

        _complete_full(store, data_root, eval_id=OTHER_EVAL_ID)
        with pytest.raises(IllegalEvalRecord):
            log_eval_summary(store, OTHER_EVAL_ID, {"f1": 0.99})

    def test_fold_metrics_stay_on_children_and_aggregate_on_parent(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §2.8：fold 过程指标只落子 Run；聚合只落父 Run
        record = _create(store, data_root)
        _finish_folds(store)
        _aggregate(store)

        parent_metrics = dict(_raw_run(store, record.run_id).data.metrics)
        assert parent_metrics == AGGREGATE_METRICS

        for fold, fold_record in get_eval_run(store, EVAL_ID).folds.items():
            child_metrics = dict(_raw_run(store, fold_record.run_id).data.metrics)
            assert child_metrics == FOLD_METRICS[fold]
            assert set(child_metrics).isdisjoint(set(AGGREGATE_METRICS))


# —————————————————— T5 workflow_state 状态机纪律 ——————————————————


class TestStateDiscipline:
    def test_combo_stays_in_fixed_table_along_lifecycle(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 全图行走：running→partial→running→failed→running→completed→archived，
        # 每步组合都落在 §5.3 固定表（委托 versioning.state 的表做判定）
        record = _create(store, data_root)
        _assert_combo_legal(record)
        # fold/聚合只允许在 running 下写，先备齐再走状态
        _finish_folds(store)
        _aggregate(store)

        partial = transition_eval_state(store, EVAL_ID, "partial", run_status="KILLED")
        assert (partial.workflow_state, partial.run_status) == ("partial", "KILLED")
        _assert_combo_legal(partial)

        recovered = transition_eval_state(store, EVAL_ID, "running")
        assert (recovered.workflow_state, recovered.run_status) == (
            "running",
            "RUNNING",
        )
        assert recovered.run_id == record.run_id
        _assert_combo_legal(recovered)

        failed = transition_eval_state(store, EVAL_ID, "failed", run_status="FAILED")
        assert (failed.workflow_state, failed.run_status) == ("failed", "FAILED")
        _assert_combo_legal(failed)

        transition_eval_state(store, EVAL_ID, "running")
        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        assert (completed.workflow_state, completed.run_status) == (
            "completed",
            "FINISHED",
        )
        _assert_combo_legal(completed)

        archived = transition_eval_state(store, EVAL_ID, "archived")
        assert (archived.workflow_state, archived.run_status) == (
            "archived",
            "FINISHED",
        )
        _assert_combo_legal(archived)
        assert archived.run_id == record.run_id

    @pytest.mark.parametrize(
        ("target", "run_status", "outcome"),
        [
            ("partial", None, None),
            ("partial", "RUNNING", None),
            ("partial", "FINISHED", None),
            ("failed", None, None),
            ("failed", "FINISHED", None),
            ("completed", "RUNNING", "passed"),
            ("archived", "FAILED", None),
            ("running", "FINISHED", None),
        ],
    )
    def test_illegal_target_status_combination_rejected(
        self,
        store: EvalRecordStore,
        data_root: Path,
        target: str,
        run_status: str | None,
        outcome: str | None,
    ) -> None:
        # 目标 workflow_state 与显式 run_status（或缺省的歧义）组合违反
        # §5.3 固定表 -> IllegalStateCombination（委托 versioning.state）
        record = _create(store, data_root)
        _finish_folds(store)
        _aggregate(store)
        if target == "archived":
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        elif target == "running":
            transition_eval_state(store, EVAL_ID, "partial", run_status="KILLED")

        with pytest.raises(IllegalStateCombination):
            transition_eval_state(
                store, EVAL_ID, target, run_status=run_status, outcome=outcome
            )

        # fail-closed：原状态组合不变
        after = get_eval_run(store, EVAL_ID)
        _assert_combo_legal(after)
        assert after.run_id == record.run_id

    def test_controlled_recovery_returns_same_run_to_running(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §11.3 同型：partial/failed 只能受控恢复回 running，原 Run ID 不变
        record = _create(store, data_root)
        partial = transition_eval_state(store, EVAL_ID, "partial", run_status="KILLED")
        assert (partial.workflow_state, partial.run_status) == ("partial", "KILLED")
        assert _raw_run(store, record.run_id).info.status == "KILLED"

        recovered = transition_eval_state(store, EVAL_ID, "running")
        assert recovered.run_id == record.run_id
        assert (recovered.workflow_state, recovered.run_status) == (
            "running",
            "RUNNING",
        )
        assert _raw_run(store, record.run_id).info.status == "RUNNING"

    def test_partial_then_failed_needs_running_in_between(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        transition_eval_state(store, EVAL_ID, "partial", run_status="KILLED")
        # partial→failed 非法（必须经 running）
        with pytest.raises(IllegalTransition):
            transition_eval_state(store, EVAL_ID, "failed", run_status="FAILED")
        assert get_eval_run(store, EVAL_ID).workflow_state == "partial"

        transition_eval_state(store, EVAL_ID, "running")
        failed = transition_eval_state(store, EVAL_ID, "failed", run_status="FAILED")
        assert failed.workflow_state == "failed"
        assert failed.run_id == record.run_id

    def test_tampered_state_tag_rejected_on_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # D038：实现必须拒绝人工或异常操作产生的非法组合
        record = _create(store, data_root)  # running/RUNNING
        _client(store).set_tag(record.run_id, "workflow_state", "completed")

        with pytest.raises(IllegalStateCombination):
            get_eval_run(store, EVAL_ID)
        with pytest.raises(IllegalStateCombination):
            transition_eval_state(store, EVAL_ID, "partial", run_status="FAILED")
        with pytest.raises(IllegalStateCombination):
            validate_eval_for_conclusion(store, EVAL_ID)

    def test_garbage_state_tag_rejected_on_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        _client(store).set_tag(record.run_id, "workflow_state", "paused")
        with pytest.raises(IllegalStateCombination):
            get_eval_run(store, EVAL_ID)

    def test_tampered_validity_tag_rejected_on_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §2.6：record_validity 合法值仅 valid|invalid
        record = _create(store, data_root)
        _client(store).set_tag(record.run_id, "record_validity", "maybe")
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_tampered_terminal_combo_blocked_at_gate(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # completed tag + RUNNING 原生（篡改）→ 组合非法，结论门 fail-closed
        record = _create(store, data_root)
        _finish_folds(store)
        _aggregate(store)
        transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        _client(store).update_run(record.run_id, status="RUNNING")

        with pytest.raises(IllegalStateCombination):
            validate_eval_for_conclusion(store, EVAL_ID)

    def test_complete_retries_after_outcome_write_failure(
        self,
        store: EvalRecordStore,
        data_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        record = _create(store, data_root)
        _finish_folds(store)
        _aggregate(store)
        original = MlflowClient.set_tag
        failed = False

        def fail_outcome_once(client, run_id, key, value, *args, **kwargs):
            nonlocal failed
            if key == OUTCOME_TAG and not failed:
                failed = True
                raise RuntimeError("injected outcome write failure")
            return original(client, run_id, key, value, *args, **kwargs)

        monkeypatch.setattr(MlflowClient, "set_tag", fail_outcome_once)
        with pytest.raises(RuntimeError):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        raw = _raw_run(store, record.run_id)
        assert raw.data.tags[WORKFLOW_STATE_TAG] == "running"
        assert raw.info.status == "RUNNING"

        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        assert (completed.workflow_state, completed.run_status, completed.outcome) == (
            "completed",
            "FINISHED",
            "passed",
        )

    def test_complete_locks_outcome_after_workflow_write_failure(
        self,
        store: EvalRecordStore,
        data_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        record = _create(store, data_root)
        _finish_folds(store)
        _aggregate(store)
        original = MlflowClient.set_tag
        failed = False

        def fail_workflow_once(client, run_id, key, value, *args, **kwargs):
            nonlocal failed
            if key == WORKFLOW_STATE_TAG and value == "completed" and not failed:
                failed = True
                raise RuntimeError("injected workflow write failure")
            return original(client, run_id, key, value, *args, **kwargs)

        monkeypatch.setattr(MlflowClient, "set_tag", fail_workflow_once)
        with pytest.raises(RuntimeError, match="workflow write failure"):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        raw = _raw_run(store, record.run_id)
        assert raw.data.tags[WORKFLOW_STATE_TAG] == "running"
        assert raw.data.tags[OUTCOME_TAG] == "passed"
        assert raw.info.status == "RUNNING"

        with pytest.raises(IllegalEvalRecord, match="outcome 不得改写"):
            transition_eval_state(store, EVAL_ID, "completed", outcome="failed")
        assert _raw_run(store, record.run_id).data.tags[OUTCOME_TAG] == "passed"

        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        assert (completed.workflow_state, completed.run_status, completed.outcome) == (
            "completed",
            "FINISHED",
            "passed",
        )

    def test_complete_is_idempotent_after_server_committed_finished(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        """服务端已提交、客户端丢响应后的同结论重试只读成功。"""
        _create(store, data_root)
        _finish_folds(store)
        _aggregate(store)
        first = transition_eval_state(
            store, EVAL_ID, "completed", outcome="passed"
        )
        retried = transition_eval_state(
            store, EVAL_ID, "completed", outcome="passed"
        )
        assert retried == first
        with pytest.raises(IllegalEvalRecord, match="outcome 不得改写"):
            transition_eval_state(store, EVAL_ID, "completed", outcome="failed")

    def test_complete_repairs_completed_running_after_terminate_failure(
        self,
        store: EvalRecordStore,
        data_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        record = _create(store, data_root)
        _finish_folds(store)
        _aggregate(store)
        original = MlflowClient.set_terminated
        failed = False

        def fail_terminate_once(client, run_id, *args, **kwargs):
            nonlocal failed
            if run_id == record.run_id and not failed:
                failed = True
                raise RuntimeError("injected terminate failure")
            return original(client, run_id, *args, **kwargs)

        monkeypatch.setattr(MlflowClient, "set_terminated", fail_terminate_once)
        with pytest.raises(RuntimeError):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        raw = _raw_run(store, record.run_id)
        assert raw.data.tags[WORKFLOW_STATE_TAG] == "completed"
        assert raw.data.tags[OUTCOME_TAG] == "passed"
        assert raw.info.status == "RUNNING"

        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        assert (completed.workflow_state, completed.run_status, completed.outcome) == (
            "completed",
            "FINISHED",
            "passed",
        )

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            ("partial", "completed"),
            ("failed", "completed"),
            ("completed", "running"),
            ("completed", "partial"),
            ("archived", "completed"),
            ("archived", "running"),
            ("running", "prepared"),  # prepared=无 Run，不存在回退入口
            ("running", "running"),  # 自环
            ("partial", "partial"),  # 自环
            ("failed", "partial"),
        ],
    )
    def test_illegal_transitions_rejected(
        self, store: EvalRecordStore, data_root: Path, source: str, target: str
    ) -> None:
        record = _prepare_eval_state(store, data_root, source)
        assert record.workflow_state == source

        with pytest.raises(IllegalTransition):
            transition_eval_state(store, EVAL_ID, target)

        # 拒绝后状态不变
        after = get_eval_run(store, EVAL_ID)
        assert after.workflow_state == source
        assert after.run_id == record.run_id

    def test_transition_accepts_workflow_state_enum(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 委托 versioning.state：枚举与值字符串等价
        _create(store, data_root)
        partial = transition_eval_state(
            store, EVAL_ID, WorkflowState.PARTIAL, run_status="FAILED"
        )
        assert partial.workflow_state == "partial"
        recovered = transition_eval_state(store, EVAL_ID, WorkflowState.RUNNING)
        assert recovered.workflow_state == "running"


# —————————————————— T6 record_validity ——————————————————


class TestRecordValidity:
    def test_mark_invalid_sets_tag_and_is_idempotent(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        assert record.record_validity == "valid"

        marked = mark_eval_invalid(store, EVAL_ID)
        assert marked.record_validity == "invalid"
        assert marked.run_id == record.run_id
        assert _raw_run(store, record.run_id).data.tags["record_validity"] == "invalid"

        # 同值幂等（transition_record_validity 语义），原生状态不被触碰
        again = mark_eval_invalid(store, EVAL_ID)
        assert again.record_validity == "invalid"
        assert again.run_status == "RUNNING"
        assert _raw_run(store, record.run_id).info.status == "RUNNING"

    def test_invalid_record_rejected_by_conclusion_gate(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §2.6/§10：record_validity=invalid 的测评被下游校验拒绝
        # （更正策略：invalid + 新建版本，不复活旧事实）
        _complete_cv(store, data_root)
        mark_eval_invalid(store, EVAL_ID)

        with pytest.raises(InvalidEvalRecord):
            validate_eval_for_conclusion(store, EVAL_ID)

    def test_invalid_check_precedes_gate_conditions(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # validity 优先于 scope 完整性：running 且零 fold + invalid →
        # InvalidEvalRecord（而非 IncompleteEvalRecord）
        _create(store, data_root)
        mark_eval_invalid(store, EVAL_ID)

        with pytest.raises(InvalidEvalRecord):
            validate_eval_for_conclusion(store, EVAL_ID)

    @pytest.mark.parametrize(
        "tampered_state",
        ["completed", "partial", "failed", "archived", "prepared"],
    )
    def test_invalid_precedes_illegal_state_combination(
        self, store: EvalRecordStore, data_root: Path, tampered_state: str
    ) -> None:
        # P2-1 回归（B6 同型）：§10 顺序钉死——record_validity=invalid 的
        # 判定必须先于 workflow_state/run_status 组合校验。修复前先构造
        # 快照（组合校验随读取先行），被篡改的 invalid 记录会以
        # IllegalStateCombination 冒名拒绝，invalid 事实被"洗白"为组合
        # 错误；修复后必须抛 InvalidEvalRecord。对照组（valid + 同样篡改
        # -> IllegalStateCombination）由 T5 篡改用例覆盖，二者合成 §10 的
        # 完整优先级矩阵。
        record = _create(store, data_root)  # running/RUNNING/valid
        mark_eval_invalid(store, EVAL_ID)
        # 原生状态仍 RUNNING：篡改后的 workflow_state 与之构成 §5.3 非法组合
        assert _raw_run(store, record.run_id).info.status == "RUNNING"
        _client(store).set_tag(record.run_id, "workflow_state", tampered_state)

        with pytest.raises(InvalidEvalRecord) as excinfo:
            validate_eval_for_conclusion(store, EVAL_ID)

        # 必须是 InvalidEvalRecord，而非修复前的 IllegalStateCombination
        assert not isinstance(excinfo.value, IllegalStateCombination)
        # fail-closed：校验只读，不修复也不掩盖被篡改的事实
        raw = _raw_run(store, record.run_id)
        assert raw.data.tags["record_validity"] == "invalid"
        assert raw.data.tags["workflow_state"] == tampered_state
        assert raw.info.status == "RUNNING"

    def test_validity_enum_alignment(self, store: EvalRecordStore, data_root: Path) -> None:
        # 与 versioning.state.RecordValidity 值域对齐（valid|invalid）
        _create(store, data_root)
        record = get_eval_run(store, EVAL_ID)
        assert record.record_validity == RecordValidity.VALID.value
        marked = mark_eval_invalid(store, EVAL_ID)
        assert marked.record_validity == RecordValidity.INVALID.value


# —————————————————— T7 读取 fail-closed（篡改/异常观测）——————————————————


class TestReadFailClosed:
    """D038/契约要点 5：读取路径对篡改 tag 与非法子 Run 观测一律域异常拒绝。"""

    def test_tampered_model_id_tag_rejected_on_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        _client(store).set_tag(record.run_id, "model_id", "not-a-model-id")
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_tampered_data_version_tag_rejected_on_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        _client(store).set_tag(record.run_id, "data_version", "data-v4.1")
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_tampered_model_version_number_tag_rejected_on_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        _client(store).set_tag(record.run_id, "model_version_number", "one")
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_tampered_scope_tag_rejected_on_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        _client(store).set_tag(record.run_id, "scope", "crossvalidation")
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [("config", ""), ("git_commit", "")],
    )
    def test_tampered_scalar_reference_tags_rejected_on_read(
        self,
        store: EvalRecordStore,
        data_root: Path,
        field: str,
        bad_value: str,
    ) -> None:
        record = _create(store, data_root)
        _client(store).set_tag(record.run_id, field, bad_value)
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    @pytest.mark.parametrize("scope", ["single_fold", "full"])
    def test_missing_split_tag_rejected_for_single_and_full(
        self, store: EvalRecordStore, data_root: Path, scope: str
    ) -> None:
        # 读取时校验 split 存在性（scope 条件）；声明后被删除视为篡改
        record = _create(store, data_root, scope=scope, split=SPLIT)
        _client(store).delete_tag(record.run_id, "split")
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_tampered_outcome_value_rejected_on_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        _complete_cv(store, data_root)
        record = get_eval_run(store, EVAL_ID)
        _client(store).set_tag(record.run_id, "outcome", "bogus")
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_deleted_outcome_tag_blocks_gate_not_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # outcome tag 被删除：读取层不炸（值域校验仅对存在值），快照如实
        # 反映缺失；结论门拒绝（缺 outcome 不可形成当前结论）
        _complete_cv(store, data_root)
        record = get_eval_run(store, EVAL_ID)
        _client(store).delete_tag(record.run_id, "outcome")

        snapshot = get_eval_run(store, EVAL_ID)
        assert snapshot.outcome is None
        with pytest.raises(IncompleteEvalRecord):
            validate_eval_for_conclusion(store, EVAL_ID)

    def test_child_with_garbage_fold_tag_rejected(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 错配 fold：fold tag 不可解析为编号（不泄漏裸 ValueError/解析异常）
        record = _create(store, data_root)
        _create_fold(store, fold=0)
        _inject_child(
            store,
            record.run_id,
            **{"mlflow.runName": "injected", "fold": "bogus"},
        )
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_child_with_missing_fold_tag_rejected(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 挂靠父 Run 但无 fold 标识的子 Run：非法观测
        record = _create(store, data_root)
        _inject_child(
            store, record.run_id, **{"mlflow.runName": "injected"}
        )
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_child_with_out_of_scope_fold_tag_rejected(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 额外 fold：fold3 不在 REQUIRED_FOLDS 内，即使绑定齐全也拒绝
        record = _create(store, data_root)
        _create_fold(store, fold=0)
        _inject_child(
            store,
            record.run_id,
            **{"mlflow.runName": "fold3"},
            fold="fold3",
            **{k: str(v) for k, v in FOLD_BINDINGS[0].items()},
        )
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_duplicate_fold_children_rejected_on_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 重复 fold：同父 Run 下 fold0 出现两个绑定齐全的子 Run
        record = _create(store, data_root)
        _create_fold(store, fold=0)
        _inject_child(
            store,
            record.run_id,
            **{"mlflow.runName": "fold0"},
            fold="fold0",
            **{k: str(v) for k, v in FOLD_BINDINGS[0].items()},
        )
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_child_missing_binding_tags_rejected(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 缺失/不完整 fold 绑定（无五个绑定 tags）拒绝
        record = _create(store, data_root)
        _inject_child(
            store,
            record.run_id,
            **{"mlflow.runName": "fold1", "fold": "fold1"},
        )
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_child_with_garbage_sample_count_rejected(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        bindings = {k: str(v) for k, v in FOLD_BINDINGS[1].items()}
        bindings["sample_count"] = "many"
        _inject_child(
            store,
            record.run_id,
            **{"mlflow.runName": "fold1"},
            fold="fold1",
            **bindings,
        )
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_full_scope_with_any_child_rejected(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # full 的 fold 上限为 0：任何子 Run（即使绑定齐全）都是额外 fold
        record = _create(store, data_root, scope="full", split=HOLDOUT_SPLIT)
        _inject_child(
            store,
            record.run_id,
            **{"mlflow.runName": "fold0"},
            fold="fold0",
            **{k: str(v) for k, v in FOLD_BINDINGS[0].items()},
        )
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_single_fold_with_second_child_rejected(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # single_fold 上限 1：第二个（不同编号、绑定齐全的）fold 子 Run 拒绝
        record = _create(store, data_root, scope="single_fold", split=SPLIT)
        _create_fold(store, fold=0)
        _inject_child(
            store,
            record.run_id,
            **{"mlflow.runName": "fold1"},
            fold="fold1",
            **{k: str(v) for k, v in FOLD_BINDINGS[1].items()},
        )
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_aggregate_tag_on_non_cv_scope_rejected(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # aggregate_folds 只允许出现在 cross_validation（single/full 无聚合）
        record = _create(store, data_root, scope="single_fold", split=SPLIT)
        _client(store).set_tag(record.run_id, AGGREGATE_FOLDS_TAG, "fold0")
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

    def test_aggregate_tag_value_rules_on_read(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # cross_validation 上 aggregate_folds 每项必须是 fold<N>（N ∈
        # REQUIRED_FOLDS）；语法合法但非全量的子集值读取不炸（完整性由
        # completed 门拒绝，见 T4）
        record = _create(store, data_root)
        _client(store).set_tag(record.run_id, AGGREGATE_FOLDS_TAG, "bogus")
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

        _client(store).set_tag(record.run_id, AGGREGATE_FOLDS_TAG, "fold0,fold9")
        with pytest.raises(IllegalEvalRecord):
            get_eval_run(store, EVAL_ID)

        _client(store).set_tag(record.run_id, AGGREGATE_FOLDS_TAG, "fold0,fold1")
        snapshot = get_eval_run(store, EVAL_ID)
        assert snapshot.workflow_state == "running"


# —————————————————— T8 读路径 eval_id 入口校验（P3 回归）——————————————————


class TestReadPathEvalIdValidation:
    """P3 回归（B6 复审同型）：读路径入口的 eval_id 校验。

    修复前若不校验 eval_id 即拼 MLflow filter_string：含单引号的注入串在
    MLflow 查询解析器抛 ``MlflowException``（域校验泄漏为底层异常）；
    双引号/尾随换行/非字符串则被静默当作"不存在"（与
    ``EvalRecordNotFound`` 混淆）。修复后读路径入口先 ``parse_eval_id``：
    畸形 ID 一律 ``InvalidIdentifier``（§3.1/§9 显式版本纪律 + D038
    fail-closed），绝不 ``MlflowException``，也绝不与
    ``EvalRecordNotFound`` 混淆。
    """

    @pytest.mark.parametrize(
        "operation",
        [
            lambda store: get_eval_run(store, INJECTION_EVAL_ID),
            lambda store: list_eval_fold_runs(store, INJECTION_EVAL_ID),
            lambda store: create_eval_fold_run(
                store, INJECTION_EVAL_ID, 0, **FOLD_BINDINGS[0]
            ),
            lambda store: log_eval_fold_metrics(
                store, INJECTION_EVAL_ID, 0, FOLD_METRICS[0]
            ),
            lambda store: end_eval_fold_run(
                store, INJECTION_EVAL_ID, 0, "FINISHED"
            ),
            lambda store: resume_eval_fold_run(store, INJECTION_EVAL_ID, 0),
            lambda store: log_eval_summary(store, INJECTION_EVAL_ID, SUMMARY_METRICS),
            lambda store: log_eval_aggregate(
                store, INJECTION_EVAL_ID, AGGREGATE_METRICS, folds=REQUIRED_FOLDS
            ),
            lambda store: transition_eval_state(
                store, INJECTION_EVAL_ID, "partial", run_status="FAILED"
            ),
            lambda store: mark_eval_invalid(store, INJECTION_EVAL_ID),
            lambda store: validate_eval_for_conclusion(store, INJECTION_EVAL_ID),
        ],
    )
    def test_injection_id_rejected_by_every_read_entry(
        self, store: EvalRecordStore, data_root: Path, operation
    ) -> None:
        # store 内已有合法记录：畸形 ID 不得与"不存在"混淆，也不得泄漏为
        # MLflow 查询异常（修复前的两种症状）
        _create(store, data_root)
        with pytest.raises(InvalidIdentifier) as excinfo:
            operation(store)

        assert not isinstance(excinfo.value, MlflowException)
        assert not isinstance(excinfo.value, EvalRecordNotFound)
        # fail-closed：拒绝发生在任何写入之前，既有事实原样（无新 Run/fold）
        assert get_eval_run(store, EVAL_ID).folds == {}
        assert len(_evals(store, EVAL_ID)) == 1
        assert len(_all_runs(store)) == 1

    @pytest.mark.parametrize("malformed_id", MALFORMED_QUOTED_EVAL_IDS)
    def test_malformed_shapes_rejected_by_get_eval_run(
        self, store: EvalRecordStore, data_root: Path, malformed_id: object
    ) -> None:
        _create(store, data_root)
        with pytest.raises(InvalidIdentifier) as excinfo:
            get_eval_run(store, malformed_id)

        assert not isinstance(excinfo.value, MlflowException)
        assert not isinstance(excinfo.value, EvalRecordNotFound)
        # 既有合法记录不受畸形读影响
        assert get_eval_run(store, EVAL_ID).eval_id == EVAL_ID


# —————————————————— T9 holdout 鉴权（§5.6）——————————————————


def _holdout_inputs(pre_registration: Path) -> dict:
    """对 purpose=holdout 数据创建 eval 的标准输入（scope=full + test split）。

    data_root 由 ``_create`` 第二个位置参数传入（与其他 scope 用例一致），
    鉴权三要素为 pre_registration / executor / split。
    """
    return {
        "data_version": HOLDOUT_DATA_VERSION,
        "scope": "full",
        "split": HOLDOUT_SPLIT,
        "pre_registration": pre_registration,
        "executor": EXECUTOR,
    }


class TestHoldoutAuthorization:
    """契约要点 4：eval 引用 purpose=holdout 数据须有效 claim + pre_registration。

    claim 由 staging 在首次模型调用前经 holdout.acquire_claim 建立（§5.6）；
    本模块只做 load/verify：四元组（eval/model/data/split）+ executor + 未消费
    必须全部一致，缺失/错配/已消费一律 fail-closed（语义决策点 3）。
    """

    def test_holdout_eval_without_claim_rejected(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        # 无 claim：staging 未建立全局一次性授权 -> fail-closed，无 Run 产生
        pre = _write_pre_registration(tmp_path / "pre.yaml")
        with pytest.raises(HoldoutAuthorizationError):
            _create(store, holdout_root, **_holdout_inputs(pre))
        assert _all_runs(store) == []

    def test_holdout_eval_with_valid_claim_and_pre_registration(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        # 正向：staging 先 acquire 全局 claim，再创建 eval 记录
        pre = _write_pre_registration(tmp_path / "pre.yaml")
        _acquire_holdout_claim(holdout_root, pre_registration=pre)

        record = _create(store, holdout_root, **_holdout_inputs(pre))

        assert record.eval_id == EVAL_ID
        assert record.data_version == HOLDOUT_DATA_VERSION
        assert record.scope == "full"
        assert record.split == HOLDOUT_SPLIT
        assert record.workflow_state == "running"

        authorization = _holdout_release_dir(holdout_root) / "authorization"
        assert (authorization / "claim.yaml").is_file()
        # 创建记录不等于消费：consumed.yaml 仍不存在（语义决策点 3）
        assert not (authorization / "consumed.yaml").exists()

    def test_holdout_consumed_claim_rejected(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        # 已消费 claim 不得再当可用授权（holdout.ClaimConsumed 语义）
        pre = _write_pre_registration(tmp_path / "pre.yaml")
        _acquire_holdout_claim(holdout_root, pre_registration=pre)
        authorization = _holdout_release_dir(holdout_root) / "authorization"
        mark_claim_consumed(
            authorization,
            ClaimIdentity(
                eval_version=EVAL_ID,
                model_version=MODEL_ID,
                data_version=HOLDOUT_DATA_VERSION,
                split=HOLDOUT_SPLIT,
            ),
            EXECUTOR,
            pre_registration_sha256=hashlib.sha256(pre.read_bytes()).hexdigest(),
        )
        with pytest.raises(HoldoutAuthorizationError):
            _create(store, holdout_root, **_holdout_inputs(pre))
        assert _all_runs(store) == []

    @pytest.mark.parametrize(
        ("claim_kwargs", "create_overrides"),
        [
            ({"eval_id": OTHER_EVAL_ID}, {}),  # claim 属于另一 eval 版本
            ({"model_id": OTHER_MODEL_ID}, {}),  # claim 绑定另一 model
            ({"split": "validation"}, {}),  # claim 绑定另一 split
            ({}, {"split": "validation"}),  # 创建方 split 与 claim/pre 不一致
        ],
    )
    def test_holdout_claim_quad_mismatch_rejected(
        self,
        store: EvalRecordStore,
        holdout_root: Path,
        tmp_path: Path,
        claim_kwargs: dict,
        create_overrides: dict,
    ) -> None:
        # §5.6：四元组任一字段不同都拒绝，且不创建第二个 claim
        pre = _write_pre_registration(tmp_path / "pre.yaml")
        _acquire_holdout_claim(
            holdout_root, pre_registration=pre, **claim_kwargs
        )
        inputs = _holdout_inputs(pre)
        inputs.update(create_overrides)

        with pytest.raises(HoldoutAuthorizationError):
            _create(store, holdout_root, **inputs)
        assert _all_runs(store) == []

    def test_holdout_executor_mismatch_rejected(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        # §5.6：新进程必须携带并验证原执行身份
        pre = _write_pre_registration(tmp_path / "pre.yaml")
        _acquire_holdout_claim(holdout_root, pre_registration=pre)
        inputs = _holdout_inputs(pre)
        inputs["executor"] = "runner-B"

        with pytest.raises(HoldoutAuthorizationError):
            _create(store, holdout_root, **inputs)
        assert _all_runs(store) == []

    def test_holdout_pre_registration_missing_rejected(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        missing = tmp_path / "staging" / "pre_registration.yaml"  # 文件不存在
        _acquire_holdout_claim(holdout_root, pre_registration=missing)

        with pytest.raises(HoldoutAuthorizationError):
            _create(store, holdout_root, **_holdout_inputs(missing))
        assert _all_runs(store) == []

    def test_holdout_pre_registration_argument_required(
        self, store: EvalRecordStore, holdout_root: Path
    ) -> None:
        # 未提供 pre_registration 路径（None）同样 fail-closed
        _acquire_holdout_claim(holdout_root)
        inputs: dict = {
            "data_version": HOLDOUT_DATA_VERSION,
            "scope": "full",
            "split": HOLDOUT_SPLIT,
            "data_root": holdout_root,
            "pre_registration": None,
            "executor": EXECUTOR,
        }

        with pytest.raises(HoldoutAuthorizationError):
            _create(store, **inputs)
        assert _all_runs(store) == []

    def test_holdout_pre_registration_invalid_content_rejected(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        # pre_registration 内容非法（one_time 非 True）-> fail-closed
        pre = _write_pre_registration(tmp_path / "pre.yaml", one_time=False)
        _acquire_holdout_claim(holdout_root, pre_registration=pre)

        with pytest.raises(HoldoutAuthorizationError):
            _create(store, holdout_root, **_holdout_inputs(pre))
        assert _all_runs(store) == []

    def test_holdout_pre_registration_quad_mismatch_rejected(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        # pre_registration 冻结的四元组与本次创建不一致 -> fail-closed
        pre = _write_pre_registration(
            tmp_path / "pre.yaml", model_version=OTHER_MODEL_ID
        )
        _acquire_holdout_claim(holdout_root, pre_registration=pre)

        with pytest.raises(HoldoutAuthorizationError):
            _create(store, holdout_root, **_holdout_inputs(pre))
        assert _all_runs(store) == []

    def test_holdout_split_required(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        # claim 四元组需要单一 split：holdout eval 必带 split（语义决策点 8）。
        # 用 cross_validation 隔离该规则（该 scope 平时可缺省 split，缺 split
        # 的唯一拒绝理由就是 holdout 鉴权）
        pre = _write_pre_registration(tmp_path / "pre.yaml")
        _acquire_holdout_claim(holdout_root, pre_registration=pre)
        inputs = _holdout_inputs(pre)
        inputs["scope"] = "cross_validation"
        inputs["split"] = None

        with pytest.raises(HoldoutAuthorizationError):
            _create(store, holdout_root, **inputs)
        assert _all_runs(store) == []

    def test_holdout_executor_argument_required(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        pre = _write_pre_registration(tmp_path / "pre.yaml")
        _acquire_holdout_claim(holdout_root, pre_registration=pre)
        inputs = _holdout_inputs(pre)
        inputs["executor"] = None

        with pytest.raises(HoldoutAuthorizationError):
            _create(store, holdout_root, **inputs)
        assert _all_runs(store) == []

    def test_second_eval_version_cannot_reuse_claim(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        # 一次性：claim 属 eval-v4.1-r1；即使为 eval-v4.1-r2 另备一份
        # pre_registration，claim 四元组仍不匹配 -> 拒绝，且不产生第二个 claim
        pre_r2 = _write_pre_registration(
            tmp_path / "pre.yaml", eval_version=OTHER_EVAL_ID
        )
        _acquire_holdout_claim(holdout_root, pre_registration=pre_r2)
        inputs = _holdout_inputs(pre_r2)

        with pytest.raises(HoldoutAuthorizationError):
            _create(store, holdout_root, OTHER_EVAL_ID, **inputs)
        assert _all_runs(store) == []

        authorization = _holdout_release_dir(holdout_root) / "authorization"
        assert len(list(authorization.glob("claim*.yaml"))) == 1

    def test_development_data_needs_no_authorization(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 对照组：development 数据无需 claim/pre_registration/executor
        record = _create(store, data_root, scope="full", split=SPLIT)
        assert record.data_version == DATA_VERSION
        assert record.workflow_state == "running"
        assert len(_all_runs(store)) == 1


# —————————————————— T10 全链路 ——————————————————


class TestFullEvalLifecycle:
    def test_cross_validation_end_to_end(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        record = _create(store, data_root)
        seen_run_ids = {record.run_id}
        fold_run_ids: dict[int, str] = {}

        for fold in REQUIRED_FOLDS:
            fold_record = _create_fold(store, fold=fold)
            fold_run_ids[fold] = fold_record.run_id
            log_eval_fold_metrics(store, EVAL_ID, fold, FOLD_METRICS[fold])
            end_eval_fold_run(store, EVAL_ID, fold, "FINISHED")

        _aggregate(store)
        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        seen_run_ids.add(completed.run_id)

        # D038：全程原父 Run ID 不变
        assert seen_run_ids == {record.run_id}

        # raw 全量断言：父 FINISHED、引用 tags 完整、聚合与结论齐备
        raw_parent = _raw_run(store, record.run_id)
        assert raw_parent.info.status == "FINISHED"
        assert raw_parent.data.tags["eval_id"] == EVAL_ID
        assert raw_parent.data.tags["workflow_state"] == "completed"
        assert raw_parent.data.tags["record_validity"] == "valid"
        assert raw_parent.data.tags["model_id"] == MODEL_ID
        assert raw_parent.data.tags["model_version_number"] == "1"
        assert raw_parent.data.tags["data_version"] == DATA_VERSION
        assert raw_parent.data.tags["config"] == CONFIG
        assert raw_parent.data.tags["git_commit"] == GIT_COMMIT
        assert raw_parent.data.tags["scope"] == "cross_validation"
        assert raw_parent.data.tags["outcome"] == "passed"
        assert raw_parent.data.tags["summary_complete"] == "true"
        assert raw_parent.data.tags["aggregate_folds"] == "fold0,fold1,fold2"
        assert dict(raw_parent.data.metrics) == AGGREGATE_METRICS

        # 三折嵌套且各自 FINISHED、指标落子 Run
        children = _children(store, record.run_id)
        assert len(children) == 3
        for child in children:
            fold = int(child.data.tags["fold"].removeprefix("fold"))
            assert child.info.run_id == fold_run_ids[fold]
            assert child.info.status == "FINISHED"
            assert child.data.tags["mlflow.parentRunId"] == record.run_id
            assert dict(child.data.metrics) == FOLD_METRICS[fold]

        # 结论门通过；archived 后仍通过（§10 completed|archived）
        assert validate_eval_for_conclusion(store, EVAL_ID).run_id == record.run_id
        archived = transition_eval_state(store, EVAL_ID, "archived")
        assert archived.workflow_state == "archived"
        assert (
            validate_eval_for_conclusion(store, EVAL_ID).workflow_state == "archived"
        )

    def test_holdout_full_scope_end_to_end(
        self, store: EvalRecordStore, holdout_root: Path, tmp_path: Path
    ) -> None:
        # §5.6 全链路：预注册 -> 全局一次性 claim -> eval 记录 -> 汇总 ->
        # completed(passed) -> 结论门放行
        pre = _write_pre_registration(tmp_path / "pre.yaml")
        _acquire_holdout_claim(holdout_root, pre_registration=pre)
        record = _create(store, holdout_root, **_holdout_inputs(pre))

        log_eval_summary(store, EVAL_ID, SUMMARY_METRICS)
        completed = transition_eval_state(
            store,
            EVAL_ID,
            "completed",
            outcome="passed",
            pre_registration=pre,
            executor=EXECUTOR,
        )

        assert completed.outcome == "passed"
        assert completed.scope == "full"
        assert completed.split == HOLDOUT_SPLIT
        assert completed.folds == {}
        assert dict(completed.metrics) == SUMMARY_METRICS
        assert validate_eval_for_conclusion(store, EVAL_ID).run_id == record.run_id

        raw = _raw_run(store, record.run_id)
        assert raw.info.status == "FINISHED"
        assert raw.data.tags["workflow_state"] == "completed"
        assert raw.data.tags["data_version"] == HOLDOUT_DATA_VERSION
        assert raw.data.tags["outcome"] == "passed"
        assert raw.data.tags["summary_complete"] == "true"
        authorization = _holdout_release_dir(holdout_root) / "authorization"
        assert (authorization / "consumed.yaml").is_file()

    def test_recovery_flow_completes_after_controlled_resume(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # §11.3/§5.6 中断恢复全流程：崩溃 fold FAILED -> 父 partial -> 双双
        # 受控恢复 -> 补折 -> 重聚合 -> completed（不得跳步）
        record = _create(store, data_root)
        _create_fold(store, fold=0)
        log_eval_fold_metrics(store, EVAL_ID, 0, FOLD_METRICS[0])
        end_eval_fold_run(store, EVAL_ID, 0, "FINISHED")

        crashed = _create_fold(store, fold=1)
        end_eval_fold_run(store, EVAL_ID, 1, "FAILED")

        partial = transition_eval_state(store, EVAL_ID, "partial", run_status="FAILED")
        assert (partial.workflow_state, partial.run_status) == ("partial", "FAILED")

        # partial -> completed 直接拒绝
        with pytest.raises(IllegalTransition):
            transition_eval_state(store, EVAL_ID, "completed", outcome="passed")

        # 受控恢复：父 Run 与崩溃 fold 各自经原 Run ID 恢复 RUNNING
        running = transition_eval_state(store, EVAL_ID, "running")
        assert running.run_id == record.run_id
        resumed = resume_eval_fold_run(store, EVAL_ID, 1)
        assert resumed.run_id == crashed.run_id
        log_eval_fold_metrics(store, EVAL_ID, 1, {"fold_f1": 0.82, "fold_loss": 0.43})
        end_eval_fold_run(store, EVAL_ID, 1, "FINISHED")

        fold2 = _create_fold(store, fold=2)
        log_eval_fold_metrics(store, EVAL_ID, 2, FOLD_METRICS[2])
        end_eval_fold_run(store, EVAL_ID, 2, "FINISHED")

        _aggregate(store)
        completed = transition_eval_state(store, EVAL_ID, "completed", outcome="passed")
        assert (completed.workflow_state, completed.run_status) == (
            "completed",
            "FINISHED",
        )

        # 崩溃折的恢复执行产生了新一批指标值（最新值生效）
        fold_records = get_eval_run(store, EVAL_ID).folds
        assert dict(fold_records[1].metrics) == {"fold_f1": 0.82, "fold_loss": 0.43}
        assert fold_records[2].run_id == fold2.run_id
        assert (
            validate_eval_for_conclusion(store, EVAL_ID).workflow_state == "completed"
        )


# —————————————————— T11 B7a 修复回归（aggregate 写前校验 + list 观测校验）——————————————————


class TestAggregateWriteValidation:
    """B7a 修复回归 1：log_eval_aggregate 写前校验（空集合/重复 fold）零写入。

    修复前校验只做集合一致性比较：``folds=()`` 且零子 Run 时
    ``observed == provided == 空集`` 恒成立，空聚合静默写父 Run——产生
    ``aggregate_folds=""`` 垃圾 tag（下次读取即 fail-closed 拒绝）；
    ``folds=(0, 0, 1, 2)`` 去重后恰与观测集合一致，重复报折不被发现、
    聚合照写。修复后写前显式校验：空集合与重复项一律
    ``IllegalEvalRecord``，且全部校验先于任何写入——父 Run 不落任何
    metrics / aggregate_folds / summary_complete（零写入语义）。
    """

    def test_empty_folds_rejected_with_zero_children(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 关键回归：零子 Run 时 folds=() 与观测集合同为空——集合一致性
        # 比较放不了行，必须由显式空集合校验拒绝
        record = _create(store, data_root)

        with pytest.raises(IllegalEvalRecord):
            log_eval_aggregate(store, EVAL_ID, AGGREGATE_METRICS, folds=())

        raw = _raw_run(store, record.run_id)
        assert AGGREGATE_FOLDS_TAG not in raw.data.tags
        assert SUMMARY_COMPLETE_TAG not in raw.data.tags
        assert dict(raw.data.metrics) == {}
        # 零写入：拒绝不留半成品状态，记录仍可读、仍 running、无 fold
        snapshot = get_eval_run(store, EVAL_ID)
        assert snapshot.workflow_state == "running"
        assert snapshot.folds == {}

    def test_empty_folds_rejected_with_three_children(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 三折齐全后 folds=()（少报全部已建 fold）：写前拒绝且零写入
        _create(store, data_root)
        _finish_folds(store)

        with pytest.raises(IllegalEvalRecord):
            _aggregate(store, folds=())

        raw = _raw_run(store, get_eval_run(store, EVAL_ID).run_id)
        assert AGGREGATE_FOLDS_TAG not in raw.data.tags
        assert SUMMARY_COMPLETE_TAG not in raw.data.tags
        assert dict(raw.data.metrics) == {}
        # fold 指标只落子 Run，父 Run 不受失败尝试影响
        folds = get_eval_run(store, EVAL_ID).folds
        assert set(folds) == set(REQUIRED_FOLDS)
        assert dict(folds[0].metrics) == FOLD_METRICS[0]

    def test_duplicate_folds_rejected_with_zero_writes(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # folds=(0, 0, 1, 2) 去重后 {0,1,2} 恰与观测集合一致：只比集合、
        # 不查重复项则重复报折不暴露且聚合照写——必须显式拒绝
        _create(store, data_root)
        _finish_folds(store)

        with pytest.raises(IllegalEvalRecord):
            _aggregate(store, folds=(0, 0, 1, 2))

        raw = _raw_run(store, get_eval_run(store, EVAL_ID).run_id)
        assert AGGREGATE_FOLDS_TAG not in raw.data.tags
        assert SUMMARY_COMPLETE_TAG not in raw.data.tags
        assert dict(raw.data.metrics) == {}
        # 零写入不残留半成品状态：同口径合法重记仍可用
        _aggregate(store)
        assert (
            _raw_run(store, get_eval_run(store, EVAL_ID).run_id).data.tags[
                AGGREGATE_FOLDS_TAG
            ]
            == "fold0,fold1,fold2"
        )


class TestListEvalFoldRunsObservation:
    """B7a 修复回归 2：list_eval_fold_runs 观测校验与 get_eval_run 对齐。

    修复前 list 只枚举子 Run、不构建父快照：重复 fold 子 Run、full scope
    违规子 Run、越界/超额 fold 等非法观测在 list 路径被静默放行（返回
    畸形快照），与 get_eval_run 的 fail-closed 纪律（D038）不一致。
    修复后 list 复用 _build_eval_record：非法观测一律
    ``IllegalEvalRecord``；正常路径仍按 fold 编号升序返回（不依赖
    MLflow 检索顺序）。
    """

    def test_list_rejects_duplicate_fold_children(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # raw 注入第二个绑定齐全的 fold0 子 Run：标识无重复（§5.5 无
        # 缺失无重复），list 不得放行
        record = _create(store, data_root)
        _create_fold(store, fold=0)
        _inject_child(
            store,
            record.run_id,
            **{"mlflow.runName": "fold0"},
            fold="fold0",
            **{k: str(v) for k, v in FOLD_BINDINGS[0].items()},
        )

        with pytest.raises(IllegalEvalRecord):
            list_eval_fold_runs(store, EVAL_ID)

    def test_list_rejects_child_under_full_scope(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # full 的 fold 上限为 0：任何子 Run（即使绑定齐全）都是违规观测
        record = _create(store, data_root, scope="full", split=HOLDOUT_SPLIT)
        _inject_child(
            store,
            record.run_id,
            **{"mlflow.runName": "fold0"},
            fold="fold0",
            **{k: str(v) for k, v in FOLD_BINDINGS[0].items()},
        )

        with pytest.raises(IllegalEvalRecord):
            list_eval_fold_runs(store, EVAL_ID)

    def test_list_rejects_fourth_fold_in_cv(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 三折齐全后 raw 注入第 4 个子 Run：fold3 编号越界（超出
        # REQUIRED_FOLDS 且超 cross_validation ≤3 上限）
        record = _create(store, data_root)
        for fold in REQUIRED_FOLDS:
            _create_fold(store, fold=fold)
        _inject_child(
            store,
            record.run_id,
            **{"mlflow.runName": "fold3"},
            fold="fold3",
            **{k: str(v) for k, v in FOLD_BINDINGS[0].items()},
        )

        with pytest.raises(IllegalEvalRecord):
            list_eval_fold_runs(store, EVAL_ID)

    def test_list_normal_path_returns_sorted_folds(
        self, store: EvalRecordStore, data_root: Path
    ) -> None:
        # 正常路径回归：乱序建折（2,0,1），list 仍按 fold 编号升序返回，
        # 且与 get_eval_run 观测同源（同 Run ID、同绑定）
        _create(store, data_root)
        for fold in (2, 0, 1):
            _create_fold(store, fold=fold)

        listed = list_eval_fold_runs(store, EVAL_ID)
        assert [f.fold for f in listed] == [0, 1, 2]
        assert all(isinstance(f, EvalFoldRecord) for f in listed)

        snapshot = get_eval_run(store, EVAL_ID)
        assert [f.run_id for f in listed] == [
            snapshot.folds[fold].run_id for fold in REQUIRED_FOLDS
        ]
        assert listed[0].model_artifact == FOLD_BINDINGS[0]["model_artifact"]
        assert listed[2].data_split == FOLD_BINDINGS[2]["data_split"]
