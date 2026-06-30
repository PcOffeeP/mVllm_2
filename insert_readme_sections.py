#!/usr/bin/env python3
"""在 README.md 中精确插入三块新内容。"""

from pathlib import Path

README = Path("README.md")

INSERT_A = """\n### Prompt Preset 总览\n\n系统支持 5 种 prompt preset，按协议分为两类：\n\n| Preset | 协议 | 说明 | 适用场景 |\n|--------|------|------|----------|\n| `baseline` | 传统 time/type 字段 | 最宽松的 JSON-only 提示，不约束时间格式或类型标签闭集 | 探索模型对断裂理解的上限，不受格式约束 |\n| `strict` | 传统 time/type 字段 | 在 baseline 基础上增加严格约束——时间必须带 `s` 后缀、`null` 条件有限、type 必须使用闭集标签 | 与训练数据格式对齐的基准测试 |\n| `fewshot` | 传统 time/type 字段 | 与 `strict` 相同协议，额外提供 1-2 个输出样例 | 评估 few-shot 示例对输出格式稳定性的影响 |\n| `strict_interval` | interval 五字段协议 | 从\"时间点\"转向\"区间帧对\"，强制 5 字段 JSON（has_fracture, fracture_between, type, location, confidence） | 主要评估协议，与训练数据格式一致 |\n| `fewshot_interval` | interval 五字段协议 | 与 `strict_interval` 相同协议，额外提供 4 个覆盖正常断裂/未断裂/视频异常/outside_gauge 的完整样例 | 评估 interval 协议下 few-shot 的增益 |\n\n当前评估使用 **interval 五字段协议**，模型需输出以下 JSON 对象：\n"""

INSERT_B = """\n#### 任务类型\n\n`--task` 参数指定推理时模型需要输出的字段，支持 3 种任务：\n\n| Task | 输出字段 | 说明 |\n|------|---------|------|\n| `time` | `time` / `fracture_between`、`has_fracture` | 仅定位断裂时间/区间，不要求识别断裂类型 |\n| `type` | `type` | 仅分类断裂类型，不要求时间定位 |\n| `joint` | 全部字段 | 同时定位断裂时间/区间并识别断裂类型，是主要评估任务 |\n\n"""

INSERT_C = """\n#### 系统测试参考\n\n如需对所有 prompt preset 和 task 组合进行系统测试，可参考以下模式：\n\n```bash\n# 遍历 5 种 prompt preset，对每种运行 joint 任务\nfor preset in baseline strict fewshot strict_interval fewshot_interval; do\n    python3 -m finetune.validation.run_inference \\\n        --task joint \\\n        --split test \\\n        --model-dir models/minicpm-v-4.5 \\\n        --model-name "base_${preset}" \\\n        --prompt-preset "$preset" \\\n        --output "results/base_test_${preset}.jsonl"\ndone\n```\n\n换成 `--task time` 或 `--task type` 可分别对时间定位或类型分类进行专项评估。实际使用时建议在项目根目录下创建 `scripts/run_all_tests.sh` 批量脚本。\n\n> **注意**：`baseline` 和 `strict` 等传统 prompt preset 使用的 time/type 字段协议与 interval 五字段协议的评估指标不同。前者通过 `evaluate_time` / `evaluate_type` 评估（legacy 指标），后者通过 `evaluate_joint` 评估（interval 指标）。请根据 prompt preset 选择对应的评估脚本。\n"""


def insert_sections(path: Path) -> int:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    before_count = len(lines)

    # 计算插入位置（按需求精确匹配）
    idx_prompt_protocol = None
    idx_current_eval = None
    idx_inference = None
    idx_from_root = None
    idx_joint_fold0_output = None
    idx_eval = None

    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if stripped == "### Prompt 协议" and idx_prompt_protocol is None:
            idx_prompt_protocol = i
        if idx_prompt_protocol is not None and idx_current_eval is None and "当前评估使用" in stripped:
            idx_current_eval = i
        if stripped == "### 推理" and idx_inference is None:
            idx_inference = i
        if idx_inference is not None and idx_from_root is None and "从项目根目录" in stripped:
            idx_from_root = i
        if "    --output results/joint_fold0.jsonl" in line and idx_joint_fold0_output is None:
            idx_joint_fold0_output = i
        if stripped == "### 评估" and idx_eval is None:
            idx_eval = i

    # 校验锚点
    required = {
        "### Prompt 协议": idx_prompt_protocol,
        "当前评估使用 interval": idx_current_eval,
        "### 推理": idx_inference,
        "从项目根目录": idx_from_root,
        "--output results/joint_fold0.jsonl": idx_joint_fold0_output,
        "### 评估": idx_eval,
    }
    missing = [name for name, idx in required.items() if idx is None]
    if missing:
        raise RuntimeError(f"未找到以下锚点: {missing}")

    # 校验相对顺序
    if not (idx_prompt_protocol < idx_current_eval < idx_inference < idx_from_root < idx_joint_fold0_output < idx_eval):
        raise RuntimeError("锚点顺序异常，请检查 README 结构")

    # 执行插入：C 放在 joint_fold0 代码块最后一行之后，即 idx_joint_fold0_output 后
    # A/B 放在目标行之前
    insertions = [
        (idx_current_eval, INSERT_A),      # A：在 "当前评估使用 interval" 之前
        (idx_from_root, INSERT_B),          # B：在 "从项目根目录" 之前
        (idx_joint_fold0_output + 1, INSERT_C),  # C：在输出行之後
    ]

    # 按索引从后往前插入，避免位置漂移
    insertions.sort(key=lambda x: x[0], reverse=True)
    for idx, text in insertions:
        lines.insert(idx, text)

    path.write_text("".join(lines), encoding="utf-8")
    after_count = len(lines)
    return after_count - before_count


if __name__ == "__main__":
    added = insert_sections(README)
    print(f"插入完成，新增 {added} 行")
