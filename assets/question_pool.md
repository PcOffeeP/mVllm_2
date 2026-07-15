# 旧基线问题池

> 定位：旧直接预测基线的问题模板快照，仅供查阅。
> 当前 prompt 权威来源：[`pipeline/prompt_library.yaml`](../pipeline/prompt_library.yaml)。
> 运行时问题池来源：[`pipeline/config/question_pool.yaml`](../pipeline/config/question_pool.yaml)。
> `generate_questions.py`、`fill_answers.py` 和 `randomize_qs.py` 均直接读取 YAML，不读取本文档。
>
> 关联文档：[README.md](../README.md)。

## S1：中文-时间（18 条）

- 试样在哪一秒断裂？
- 断裂发生在第几秒？
- 请问试样断裂的时间点是？
- 啥时候断的？
- 试样何时发生破坏？
- 给我断裂的具体时间。
- 断裂发生在哪个时刻？
- 视频里第几秒出现断裂？
- 试样断裂的时间戳是多少？
- 何时断裂？只回答时间。
- 告诉我断裂发生在第几秒。
- 断裂起始时间点是？
- 试样在视频的第几秒断开？
- 断裂瞬间对应的时间是多少？
- 视频时间轴上，断裂发生在？
- 请问破坏发生在第几秒？
- 拉断的具体时间是？
- 只输出断裂时间。

## S2：中文-模式（18 条）

- 试样的断裂方式是什么？
- 这是什么断裂模式？
- 断裂模式属于哪一种？
- 怎么断的？描述断裂形式。
- 试样破坏模式是啥？
- 给出断裂模式的术语名称。
- 断裂属于韧性还是脆性？
- 这是什么断裂模式？
- 试样的破坏形式如何？
- 只回答断裂模式。
- 断裂后试样呈现什么特征？
- 请判断断裂模式。
- 这是什么破坏方式？
- 试样断裂的形态是？
- 断裂模式名称是什么？
- 如何分类这次断裂？
- 断裂形式属于哪种？
- 只告诉我断裂模式。

## S3：中文-二者（18 条）

- 试样在哪一秒断裂？断裂方式是什么？
- 断裂时间和断裂模式分别是？
- 请指出破坏发生的时刻和模式。
- 何时断裂？如何断裂？
- 告诉我断裂时间和断裂形式。
- 断裂发生在第几秒？属于什么模式？
- 给出断裂的时间和模式。
- 试样何时断裂？断裂特征是什么？
- 破坏时间与破坏方式？
- 视频里第几秒断裂？什么模式？
- 断裂瞬间的时间戳和模式名称。
- 何时发生断裂？请描述断裂形态。
- 试样断裂的时间和形式分别是？
- 告诉我时间和断裂模式。
- 断裂起始时刻和断裂模式？
- 何时拉断？怎么断的？
- 输出断裂时间和断裂模式。
- 第几秒断的？属于哪种破坏？

## S4：英文-时间（18 条）

- When does the specimen fracture?
- At what second does the break occur?
- What's the fracture timestamp?
- Tell me the exact time of failure.
- When does the sample break?
- Give me the fracture time only.
- At which moment does fracture happen?
- What second does the fracture take place?
- The time of fracture is?
- When does failure occur in the video?
- Report the fracture second.
- Fracture onset time?
- At what time does the specimen fail?
- What's the break time?
- When does fracture initiate?
- Give the fracture time.
- Time of failure?
- When does it break?

## S5：英文-模式（18 条）

- What is the fracture mode?
- Describe the fracture mode.
- What's the failure pattern?
- How did it break?
- Identify the fracture style.
- Give the fracture mode name.
- Is it ductile or brittle?
- What type of failure is this?
- Classify the fracture behavior.
- Mode of fracture?
- Describe the failure mode.
- What does the fracture look like?
- Fracture pattern?
- Tell me the fracture mode.
- How would you categorize this break?
- What failure mode does it show?
- Describe the break pattern.
- Only give the fracture mode.

## S6：英文-二者（18 条）

- When does fracture occur and what is the mode?
- Give me the fracture time and its mode.
- What time does it break and how?
- Report the fracture second and mode.
- When and how does the specimen fail?
- Time of fracture and failure description.
- At what second does it break? What mode?
- Identify the fracture moment and pattern.
- When is the break? What is the fracture mode?
- Fracture timestamp and mode, please.
- Tell me when it fractures and how.
- What time? What failure mode?
- When does it fail and what's the mode?
- Give both time and fracture style.
- Fracture time and fracture pattern?
- When does breakage occur? Describe it.
- Time and mode of fracture.
- When? How? (fracture time & mode)

## 关联文档

- [README.md](../README.md)
