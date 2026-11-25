# 核心线对话与来源夹具

五个输入在 2026-11-25 本轮首次运行前冻结。上游语义、义项和来源关系由夹具作者给定。冻结原句为“青签这单说的‘放行’是哪种？”，JSONL 内保留原句的双引号，字节区间使用 UTF-8 左闭右开约定。两个候选分别询问该单进入仓储流程或款项流程。关系 `dock_context(blue)` 的正负证据能区分这两种解释。

| 文件 | 来源与用途 |
| --- | --- |
| `routes.cl` | 冻结的 PCGM 模拟工单规则，初始目标集为空。 |
| `provider.cl` | 独立 CL 生产者的声明。测试从其证据日志生成冻结答卷。 |
| `dialogue-candidate.jsonl` | 模拟 Gemini 提供的一个有歧义的候选，含两个类型化目标及 UTF-8 字节位置。 |
| `lexicon-senses.jsonl` | 模拟 DeepSeek 提供的两个候选义项。 |
| `source-observations.jsonl` | 模拟 Grok 提供的三个来源记录。登记处和转载预先绑定同一观察 ID；仓储部门独立提供待核对的上下文。 |

核心测试检查同一观察 ID 的转载重放，随后从活跃证据发起议程，经独立批准通道登记问题并接纳仓储答卷。之后加入反向观察，按 ID 撤回，核对同一票、观察状态和历史对话。真实来源家族核验与自然语言候选生成由对应任务线验收。

## 结果读取

`ID reasoned_outcome CASE GOAL [since PIN]` 是 `--read-channel` 的只读帧。CASE 是调用方传入的关联 ID。GOAL 是已声明关系的类型正确、无变量的正向原子，可在登记为目标前读取。指定 `since PIN` 时，必须已用 `:pin PIN` 在同一个体和同一历史中留存了可比较的基准。

`:chat CASE TURN focus GOAL` 选定已登记的目标；`:chat CASE TURN outcome [since PIN]` 将同一结果保存为对话回执。结果里的 `state_revision` 引用写入这一轮对话之前的推理状态。相同请求与回合 ID 在重启后返回原回执。无焦点时，请求得到已有的 `clarify no_focus`。原生对话回执上限为 16 KiB，较大的结果由只读帧读取，结果上限为 2 MiB。

| 字段 | 读法 |
| --- | --- |
| `source_id`、`baseline_version` | 个体身份、交接源码清单的 SHA-256。 |
| `status`、`positive_proof`、`negative_proof` | 四值及两条分别重建的证据链，单支超过 128 个节点时保留原生截断标记。 |
| `missing`、`missing_scan_complete` | 在原生缺口搜索中可寻址的正向前提。空列表需结合扫描完成标记与当前四值判断。 |
| `question_ticket`、`questions` | 仅有一张匹配票时给出其 ID，零张或多张时为 null。列表保留该目标已有的全部票、请求摘要、答卷出处和活动状态。 |
| `effect_receipt` | 指定基准时给出历史状态版本、作用目标、结论与证明变化、规则变化及观察引用，未指定基准时为 null。 |

观察差异涵盖目标的依赖谓词范围。每项分别标明是否出现在新旧证明中。至多对八项变更逐项在当前规则下撤销一次、重新推理，结果在 `status_if_change_undone`。超过范围或反事实求值失败时此字段为 null。新旧观察在两个基准上都不活动时，净差异为空；中间的历史变化可使用更接近的基准查看。规则引用使用原生稳定身份，并给出完整规则文本、守卫和是否进入实际证明。所有比较均在内存内执行。

运行 `python3 handoff-checks/reasoned-outcome-check.py ./pcgm-alpha ./cl`，也可指定 beta。标准输出逐行保留模拟工单、热替换与回退过程中的原生结果，标准错误输出测试结论。
