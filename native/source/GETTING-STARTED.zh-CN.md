# CL / PCGM 云端原生工作台 0.123

CL 是独立编译器、类型检查器和证明引擎，可单独运行或嵌入 C 程序。PCGM 是个体运行时，掌管观察记录、记忆、方案比较和提交决策。回档、改写和保留现状依当前标准比较，不因新旧偏袒；规则回档不会撤回后来已记下的观察。

本包是 Linux x86-64 离线验收工作台，不是 Alice 或正式再再的安装更新。当前实际验收是 CPU；没有宣称 Windows 和 CUDA 已通过。

## 先核对和发现工具

在解压目录执行：

```sh
sha256sum -c SHA256SUMS
./cl --help
./cl capabilities
```

发布包只提供本地工具，无需安装服务。若需要从源码重建，使用带 C++20 的编译器、基础 POSIX 工具和 Python 3：

```sh
make -j2 all sdk
make check
```

## CL 独立用法

给可信发布包与其独立校验值，目标文件一行一个不带终止句点的 ground atom，例如 `feasible(test_b)`。

```sh
./cl package-prove fixtures/pilot.clpkg "$PACKAGE_SHA256" goals.txt
./cl evidence-init fixtures/pilot.clpkg "$PACKAGE_SHA256" goals.txt work.journal
# 另一个进程用同一发布包和目标运行 ./cl evidence-audit ...，无需写入租约。
```

在 CL 证据会话内，`id view`查看结果，`id check`用全量重算复核，`id observe REV ROW ATOM`写一条，`id withdraw REV ROW`撤回，`id restore REV ROW`恢复。批次写入语法是 `id batch TX REV ; observe ROW ATOM ; withdraw OTHER_ROW`；`id receipt TX`不重做旧请求。另一个只读会话使用 `id snapshot latest`、`id receipt latest TX`、`id feed SNAPSHOT_SHA256 CURSOR LIMIT`，版本改变则不要混用旧页。

`evidence-freeze`以准确证据快照做成离线包；`evidence-frozen-verify`必须得到可信的包、发布物和快照摘要，重算而不只读出结论。移动文件不会改变校验值。

## 嵌入和联合验收

C 应用只需 `cl-c-api.h` 与同目录的共享库 `libcl_runtime.so`；调用 `cl_evidence_freeze_v1`、`cl_evidence_verify_v1`，用 `cl_free_v1`释放返回缓冲。示例和旧 ABI 验收程序一并提供。不必带 CLI 或 PCGM。

`check-frozen-proof-admission.py`完整展示：CL 独立生成冻结包，PCGM 只读预览、核对原问题、明确接纳观察；不是读取证明就自动改程序。`check-measurement-history.py`展示原始测量、CL 推导与 PCGM 经验，用历史依据重建旧结论。`check-lifecycle.py`覆盖实际重启、热切换及回档保存事实。整个工作台只处理包里的测试个体。

### 纯内存证据更新（0.147）
C 宿主可以用 `cl_evidence_buffer_init_v1` 生成初始快照，再将已保存的快照、它的 SHA-256 和完整 batch 命令交给 `cl_evidence_buffer_batch_v1`。三个返回缓冲区分别是候选快照、对照回执、当前证明；必须各自用 `cl_free_v1` 释放。读取能力时按位检查 `CL_EVIDENCE_TRANSITIONS_V1`，不要用整个掩码作版本号。

回执里的 `committed` 是候选快照内部沿用的格式，不表示 C 宿主磁盘已经写入。宿主应在原子确认旧 SHA-256 仍是当前头后才采用返回快照。同一头可以推得互斥候选，不能都视为已提交；SHA-256 核对快照字节，不认证提交者。PCGM 的回档/改写选择与此不同，CL 的缓冲区接口只改变指定观察的生效状态，不决定 PCGM 应用哪套规则。

### 我要复验别人给的暂停点（0.150）
已有可信写入者保存的暂停点可沿用快速 `package-round-reopen`。如果文件由其他执行端给出，用
`cl package-round-audit PACKAGE PACKAGE_SHA256 GOALS CHECKPOINT CHECKPOINT_SHA256` 先核验；直接续算用
`cl package-round-reopen-verified PACKAGE PACKAGE_SHA256 GOALS CHECKPOINT CHECKPOINT_SHA256`。
它从规则包重算到原轮次，逐字节比对事实、证明、前沿、开销和索引；只复用重算出来的状态。
如果用 C，请按位检测 `CL_CHECKPOINT_AUDIT_V1`，再用 `cl_package_checkpoint_audit_v1`。
这花的是一遍前缀计算的成本，证明内容一致，不认证作者；不是 PCGM 更换规则或回档的决定。

### CL 文本符号（0.151）
CL 的 `sym` 可以直接表示完整的 UTF-8 符号，不必把对象名翻译成英文再存。例：
```cl
: observed(sym).
: known(sym).
& first observed("中文事实").
known($x) <- observed($x).
? known("中文事实").
```
双引号内可写空格和普通标点；字面双引号和反斜杠用 `\"` 与 `\\`。这是按精确字节比较的一个符号，不是任意自然语言句法分析；例如带声调的单一字符与组合字符不会静默合并，`"bare"` 也不同于旧式裸符号 `bare`。模块名、谓词名与观察 ID 仍沿用稳定 ASCII 语法。导出的证明 JSON 对文本符号给出可读值和 `encoding: "quoted_utf8"`；持久传输使用无空格的确定性编码。

### 用 CL 编写的语法识别文本常量（0.152）

新 profile 显式声明 `quoted_symbol`；旧 profile 不自动改变。两份语法源码在
`fixtures/unicode-standard-grammar.cl` 和 `fixtures/unicode-forward-grammar.cl`。
后者还支持将条件写在 `=>` 左边：

```text
: item(sym).
: result(sym).
& observed item("上海 # 東京").
item($x) => result($x).
? result("上海 # 東京").
```

```sh
pin=$(sha256sum profiles/unicode-forward.clcp | cut -d' ' -f1)
./cl profile-build profiles/unicode-forward.clcp "$pin" example.cl > example.clir
./cl ir-json example.clir
python3 check-authored-unicode.py  # 先 make all；除此无需安装其他依赖
```

CL 的语法证明按原始 UTF-8 **字节**标注位置。引号内的 `#` 是文本，引号外的
`#` 在 authored profile 中仍可作为注释。新 profile 可由上一版 CL profile
编译出下一版，并由下一版重新编译三个阶段到逐字节固定点，再显式激活。
编译进程不必重启；强制退出后的恢复使用已经提交的版本。PCGM 的候选激活
仍由 PCGM 按快照进行，不由编译器代为决定。

### 无需文件接口的 CL 编译器候选（0.153）

`cl_profile_rebuild_v1` 从当前 profile、三个 CL 阶段源码和一个固定回归样例
重新编译候选。候选三阶段必须重编译得到相同字节，样例也必须仍生成预先钉住的
IR。调用返回候选 profile 和回执两个缓冲区，不写文件、不切换运行态。
`cl_profile_rebuild_audit_v1` 从同一批钉住的输入重做编译，逐字节比较对方给的
两个缓冲区；匹配只证明可复现，不代表签名、身份或激活授权。
Linux 纯内存 C 接入示例见 `cl-profile-rebuild-sdk-check.c`。

### PCGM：哪些观察足以改变原选择

原生只读命令：`id choice_attribution 决定任务ID 当前状态SHA256`，经
`pcgm-alpha --read-channel STATE` 或当前已部署等价端发送。两端要求精确的
历史决定底稿和当前状态摘要。最多处理四条相对历史状态的净变化，枚举其全部
子集；若相对历史出现不同且唯一的选择，给出所有包含意义上的最小充分集合。
例如，A 单独足够，B 与 C 合在一起也足够，未影响结果的 D 不会被列成必要证据。
这里是对固定选项的重算，不是因果证明，也不是一条执行或回档指令。

### CL 精确符号条件（0.155）

`sym_eq(a,b)` 与 `sym_ne(a,b)` 是规则体中的正号条件，两个操作数
必须是已绑定的 `sym`；它们成为新增保留名称，不是可自行声明的谓词。
前者只在两个规范值逐字节相同的时候成立，后者只在两个已知值不同时成立。
`bare` 与 `"bare"` 不同，`"é"` 与 `"é"` 也不同。不存在的输入
不会被当成「不等」。证明会带上实际用于通过条件的两个操作数。

`profiles/exact-symbol-guards.clcp` 是明确声明支持该能力的 CL 语法和
类型规则组合。旧 profile 不自动获得新条件。只有涉及新增条件的可移植
IR 才标为 `CLIR-8`。除新保留名之外，既有语义和 IR 格式不变；这不是
字符串排序、拼写校正或自然语言推理。

### PCGM 本地观察批次（0.156）

同一批更正的状态和订阅通知只发布一次。先用只读 `storage` 取得逻辑状态
`logical_sha256`，再把消息交给已持有写入权的本机 PCGM 进程：

```text
:observation_batch corrections HEAD_SHA256 ; observe new reading("已核对 ; 更正") ; withdraw old ; restore prior
```

最多八项，目标 ID 不重复。更正不覆盖历史原观察；新值以另一个 ID 加入，
旧值仅变成非活跃。传感器、导入产物和问题回答所持有的证据不在这个接口的
处理范围。任何一项错误或过时都不会只写前一部分。即使没收到回执，也能用
只读命令 `q observation_batch corrections REQUEST_SHA256` 查询；请求摘要是
整行原文的 SHA-256（不含换行）。只有同一标识和完全相同的请求字节才返回
已提交回执，不会再次执行。

### CL：同一工作区准备一次，连续查证（0.157）

`cl_workspace_prepare_v1` 依据归档与依赖锁的摘要独立复编，先在给定资源限额内
完成推理，才返回只读句柄。以后可在多个线程用 `cl_prepared_workspace_proof_v1`
独立查证，每次显式给出预期归档摘要，避免把另一代的旧证明当作新证明。
与一次性查询的回执一致，不读取文件、不重新链接、不重跑推理；无需保留输入缓冲区。
调用者须等待所有查询结束再 close。请不要把这个接口当作决定、验证签名或写入状态的方法。

### PCGM：复核历史观察更正（0.158）

需要日后重演时，写入端可用 `:observation_batch_audited` 代替普通批次命令，
其余参数不变。它在提交前锚定历史状态，最多保留 16 个这类批次。之后通过只读端：

```text
q observation_batch_audit corrections REQUEST_SHA256 ; diagnostic(ok) ; stable(ok)
```

最多四个带类型的目标。PCGM 用当时的事实、规则和更正请求重新求证，比对提交
的事件和通知，返回更正前后证明及其 SHA-256。后续观察不会改写这份历史结果。
普通批次没存底稿时只报 `basis_not_retained`；摘要不匹配、底稿缺失或损坏时
拒绝，不从当前状态猜测。报告没有写入权，也不是事实真伪、签名或因果鉴定。

### CL 证明链完整性核验（0.160 源码增量）
`cl package-proof-integrity PACKAGE TRUSTED_SHA256 GOALS` 单独核验证明链。输出分正负两侧标记 `NO_SUPPORT`、`DIRECT_DISPUTE`、`DISPUTED_ANCESTRY`、`CLEAN_WITNESS`。后者表示至少存在一条没有本次已知争议前提的路径，不表示被审核事实必定正确。普通 `package-prove` 原输出不变。
v1 对含闭合聚合、基于观察的单位转换的规则包明确拒绝核验，避免删去争议前提后改变聚合输入或转换唯一性。尚未接入 PCGM 决策，也不是 Windows 构建。

### CL 冻结历史的证明链完整性（0.161 源码增量）
`cl evidence-frozen-integrity ARTIFACT ARTIFACT_SHA256 PACKAGE_SHA256 JOURNAL_SHA256` 在离线包的准确观察世代重算原有签名证明，再核查当前闭包内有没有独立的无争议证明路径。已撤回的观察不参与，该报告不会随之后的观察变化漂移。报告同时固定目标和原签名证明的摘要；内容被改写，即使重新计算外部哈希，也无法通过原始证明逐字节复算。并不修改原冻结格式、PCGM 接纳或决策。与 0.160 一样，闭合聚合及基于观察的单位换算还不在证明完整性核验范围内。

### PCGM 精确问题的只读证据复核（0.162 源码增量）
`pcgm-alpha --frozen-question-integrity STATE TICKET REQUEST_SHA ARTIFACT ARTIFACT_SHA PACKAGE_SHA SNAPSHOT_SHA`；Beta 同用。PCGM 核对问题和原请求，CL 分开重算原签名结果与证明链完整性。输出的 `clean_signed_advisory` 只表示恰有单侧支持且存在不经过已知争议前提的路径，不改记忆、不自动决定，也不是来源真实或任务已经完成的证明。普通旧式只读复核与显式接纳接口输出不变。

### CL 原生宿主接口（0.163 源码增量）
`cl_evidence_integrity_v1` 在完整 SDK 和不持有文件操作能力的内存 SDK 中均可用。先检查 `cl_abi_version_v1()==1`，再检测 `CL_FROZEN_INTEGRITY_V1` 能力位。传入冻结档和从可信方单独得到的三份摘要；返回报告与原 CLI 字节一致，不自动写入 PCGM。输出、诊断是独立且初始为零的缓冲描述符，返还的内存统一用 `cl_free_v1`。这是新入口，不改变旧版冻结档、证据接纳、情绪或决策。
