# 合流说明 · Codex 核心线

## 原生入口与授权

| 调用位置 | 输入 | 行为 |
| --- | --- | --- |
| 受管写者 | `--resume-agenda-local STATE APPROVAL_FD` | 只在取得现有个体的写锁后启动。首帧主动给出议程，批准写入引起状态版本变化时附带下一轮议程。宿主提供两个不同的管道 |
| 只读端 | `ID agenda`，或 resident 读管道的 `agenda` | 从已编译的规则与活跃证明得到目标、最小缺口和两种假设的后果。检查唯一性和完整性后才给出 review 摘要 |
| 独立批准管道 | `enroll_agenda ACTOR HEAD REVIEW PIN` | 在当前版本复算后登记目标与一张票。PIN 是下面规范字节的 SHA-256。权限来自宿主交付的管道 |
| resident 读管道 | `agenda_receipt ACTOR ORIGINAL_HEAD REVIEW PIN` | 登记应答丢失时按原始字段查 `recorded` 和票号，或查到 `not_recorded`。重复已登记批准读回原票 |
| 冻结答卷 | `--frozen-question-review`，随后走 resident 的 `answer` 批准帧 | 核对当前身份、头版本、票号、请求散列、本地成员及 CL 的制品、包、快照、证明散列。首次接证会检查缺口是否仍有效 |
| resident 读管道 | `answer_receipt ACTOR TICKET REQUEST ARTIFACT PACKAGE SNAPSHOT PROOF` | 断线后先查精确回执。可取得 `recorded`、`withdrawn` 或 `not_recorded`，原答卷重放不会复活已撤观察 |
| 受管交互写者 | `:repair_compare`、`:repair_step` | 同一套原生比较器分别预演或执行，宿主给一个无参数工作步。PCGM 依据现有 `@` 范围、实际瓶颈和正反例选择规则或回退 |
| 现有对话消费者 | `ID reasoned_outcome CASE GOAL [since PIN]`，`:chat CASE TURN outcome [since PIN]` | 读口返回结构化结果，对话口使用已持久化的焦点，将本轮响应记入同一会话。相同回合重放原回执 |

`enroll_agenda` 的审批字节按 UTF-8 编码，结尾也有一个 LF。

```text
PCGM-LOCAL-AGENDA-APPROVAL-1
ACTOR
ORIGINAL_HEAD
REVIEW
```

新输出版本为 `pcgm-work-agenda-v1`、`pcgm-resident-agenda-v1`、`pcgm-agenda-enrollment-receipt-v1`、`pcgm-bounded-repair-v1` 和 `pcgm-reasoned-outcome-v1`。原有作用域审批、冻结审查、单写锁和已登记票的精确回执继续使用原生协议。受管写者之间按状态交接，一次只有一个写者持锁。综合用例在接证和修复两个入口之间重新打开同一存档。

## 与三条输入线接合

1. Gemini 提供 `cl-dialogue-candidate-v1` 的候选目标、字节区间和待澄清解释。DeepSeek 通过 `cl-lexicon-sense-v1` 提供义项与参数类型。合并方先核对它们使用相同的义项、参数和基线，再交原生层检验。
2. Grok 负责 `cl-source-observation-v1` 的来源家族、范围、独立性与撤回引用。核心验收中，原件与转载已由夹具绑定为相同观察 ID，重放不增加观察。独立证据经原生 CL 编译和冻结后才进入批准管道。
3. 消费 `pcgm-reasoned-outcome-v1` 的四值、两支证明、缺口和原票。需要归因时，在变更前用 `:pin NAME` 留基准，再查询 `since NAME`。比较结果包含作用目标、前后状态、用到的规则、观察及其在证明中的位置。读端逐项撤销至多八条变化做反事实检查。两个端点的净差异不能枚举中间每一次变化。
4. 用 `fixtures/outcome/` 的“放行”样本逐层替换模拟输入。首先核对两义项对应仓储和款项两个目标，其次核对转载的原观察 ID，再核对独立答卷如何使两个目标分别得到正证与反证，最后按观察 ID 撤回并重开会话查原票。真实中文解析、来源独立性与词典质量由各自任务线验收。

## 能力边界与回退点

- 议程搜索能用一条无争议的关系事实绑定规则头的全部变量，支持参数投影、重排和重复变量。单轮上限为 256 条规则、2048 条观察、4096 次事实探测和 16 个落地待审目标。并列、争议、证据不足或截断都有明示结果。需要多条事实联合绑定规则头变量的目标待扩展。
- 相同地面缺口沿用既有去重约束。原票的必要依据受质疑时暂停首次接证，依据恢复后复用原票。如果另一个目标也缺相同事实，而原票已失去依据，本版等待证据变化，尚无把原票改挂到另一目标的操作。
- 自主修复受现有 `@` 约束，只生成经授权的一元终端规则。两件不同的、能引用干净证据的未决实例才进入改写评估。正式 CL 对有界切片独立编译并校验四值。命题的正向目标和带反证的硬条件参加比较。知识分支展示补入正反证的推演与精确票号，实际采信始终需要独立批准。执行频率由宿主调度。
- 规则热改及回退都在同一受管个体上提交。可比较的回退点是最近一次适用的有界规则修订及其持久化决策回执。回退只移除对应规则片段，历史追加回退事件，热改后发生的观察保留。复现源码原点可在独立源码树用 `git apply -R --check core.patch` 核对逆补丁，运行存档有自己的事务和回执。
- 本轮环境为本机临时 Linux x86-64 CPU。加速验证覆盖随包的 CPU 投影和直接计算参考路径。任务快照无独立 CUDA 后端。Windows 部署、真卡 CUDA 语义和性能、正式个体迁移、外部三线联合实装、系统掉电恢复、全历史 SDK 套件和开放式中文长对话均未在本轮验收。
