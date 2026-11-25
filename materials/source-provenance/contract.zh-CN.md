# 来源记录契约

2026-11-23。本文件是来源感知的证据准入契约。它只定义记录、三种处理和四值如何变化。它不修改运行时、二进制、存档或再再个体，也不代替再再作出最终事实判断。

现实结论仍由 CL 在已经获准的证据和规则上判定。外部模型只可以提供资料和转译，不得写入事实，不得采纳候选，不得接管执行。

## 1. 记录字段

一条来源记录至少包含下面这些字段，名称固定：

`evidence_id`, `claim_id`, `stance`, `source_id`, `canonical_locator`, `observed_at`, `source_family_id`, `derived_from`, `content_sha256`, `scope`, `review_status`, `supersedes`, `endpoint_mismatch`.

| 字段 | 作用 |
| --- | --- |
| `evidence_id` | 这一条证据记录的稳定编号 |
| `claim_id` | 它针对的命题。不同终点不用同一个编号 |
| `stance` | 这一条记录对命题的方向，只取 `supports` 或 `opposes`。它不是四值 |
| `source_id` | 来源个体。撤回来源时撤的是这个编号 |
| `canonical_locator` | 可点击的直接位置。没有确认到的位置不得编造 |
| `observed_at` | 这条记录被观察到的时间，不是用语气推断的“权威时间” |
| `source_family_id` | 来源家族。相同家族只算一支独立证据。空值表示家族不明 |
| `derived_from` | 它从哪些 `source_id` 转写而来。空数组表示没有转写。`null` 表示转写关系本身不明 |
| `content_sha256` | 来源字节的散列。见第 4 节。未取得字节时为 `null` |
| `scope` | 这条记录实际覆盖的终点、时间和对象。它只是说明。判定不读 `scope` 里的词 |
| `review_status` | 记录状态，只取 `recorded`、`withdrawn`、`invalid`。它不是四值 |
| `supersedes` | 被这条记录取代的 `source_id` 列表。空数组表示不取代。只认列表里的编号 |
| `endpoint_mismatch` | 布尔值。`true` 表示终点对不上该 `claim_id`，这条记录不进入独立家族。`false` 表示范围对得上。只认这个字段 |

## 2. 三种处理

每条记录先归入下面三种之一，再谈四值。

1. **同源（same-family）。** `source_family_id` 相同，或 `derived_from` 非空并指向已有来源。转载自填的另一个 `source_family_id` 不新开家族，家族跟已有来源。新闻转载、引述同一数据、截屏转帖、多时点同一机构记录，都进这一支，除非另有一条不依赖前者的独立记录。
2. **独立（independent）。** `source_family_id` 有值，`derived_from` 是空数组，且家族编号与其他已计入的家族不同。范围还必须对得上同一个 `claim_id`。
3. **不明（unknown）。** `source_family_id` 为空，或 `derived_from` 为 `null`，或归属无法确认。未知的独立性不按独立处理（unknown independence is not treated as independent）。

不明不能因为页面语气肯定、域名看起来正式、或同题转载很多，就升级成独立。一条不明记录不计入独立家族。它不得升格，也不得因为自己归属不明，就把同命题上已经范围吻合的独立家族改成未知。命题只有在不再有任何范围吻合的独立家族时，才因为归属不明而成为 `unknown`。

## 3. 四值

本契约的四值只有四个，与现有拒绝边界对齐，不另起名字：

| 四值 | 含义 |
| --- | --- |
| `admitted` | 已获准。至少有一支范围吻合的独立家族，且这些家族方向一致。旁边另有一条归属不明的记录时，那一条不挡获准，也不得被算进家族数。证据可以交给 CL。本契约到此为止 |
| `invalid_source` | 无效来源。对应 invalid source 拒绝。定位缺失却被当成原始记录，散列对不上已取得的字节，或 `review_status` 为 `invalid`。该命题上没有其他可计入的家族时，四值是 `invalid_source` |
| `conflict` | 冲突。对应 conflict 拒绝。同一个 `claim_id` 上有两支或更多范围吻合的独立家族，方向相反。终点对不上的记录不配成冲突 |
| `unknown` | 未知。对应 unknown 拒绝。没有任何范围吻合的独立家族，因为归属不能确认或转写关系为 `null`；或同一家族内方向相反，且没有记录的 `supersedes` 指向同案来源；或 `endpoint_mismatch` 为 `true` 的记录被排除后不再有可计入的家族；或撤完之后不再有任何范围吻合的家族。一条 `derived_from` 为 `null` 的记录本身是不明，不把旁边已经独立的家族拖成未知 |

冲突不被多数票压掉。三支转载对一支独立反证，仍然是 `conflict`。未知也不被多数票压成 `admitted`。

四值变化只由记录的增减和归属判定引起。语气、域名个数、出处名气都不进入这个函数。可信度不按域名个数打分，也不按语气打分（credibility is not scored by domain count or by tone）。

## 4. 散列、家族、结论

`content_sha256` 只核对字节是否原样（a content hash checks byte integrity only）。散列相同，只说明字节相同，不说明有了第二支独立证据。散列不同，只说明字节变了，不说明新的家族已经独立。

是否独立，看来源家族，不看散列，也不看域名（source family is what says whether support is independent）。

命题真假不在本契约里落笔。现实结论仍由 CL 在已经获准的证据和规则上判定（a real conclusion stays with CL on already-admitted evidence and rules）。

## 5. 反例

下面四类都不得算成新的独立证据：

- **新闻转载。** 通讯社稿件被另一家网站原文转出，或新闻只是复述一份撤回通知。`derived_from` 指向原稿，家族与原稿相同。
- **引述同一数据。** 多篇文章引用同一张表、同一次发布、同一个仪表上的同一个数。家族是那次发布，不是每篇文章。
- **截屏转帖。** 截屏没有可确认的原始机构记录，或转帖人没有给出原始定位。家族按不明处理，不得把截屏本身当成独立测量。
- **多时点同一机构记录。** 同一机构前后几份记录，家族仍是该机构的那条序列。后一份若取代前一份，`supersedes` 列出被取代记录的 `source_id`，只更新这个家族的当前方向；前一份记录还在，但不是第二支独立家族。`supersedes` 为空、同一家族内方向又相反时，不得自行挑选语气更强的一份。该家族不计入独立家族，四值是 `unknown`，不是 `conflict`。`scope` 里出现 `supersedes` 或 `endpoint_mismatch` 这两个词，都不触发。

## 6. 撤回后重算

撤掉一项，只撤该项自己的来源（withdrawing one item withdraws only that item's own source）。被撤的是一个 `source_id`。其他 `source_id`、其他家族、其他命题都不跟着删除。

重算范围只有：剩余记录的家族归并、该命题的独立家族数、该命题的四值。不得把撤回写成反方向的新证据，不得因此声称命题已经成立，也不得编造下一步工作。

转载不增加独立证据（a reprint does not increase independent evidence）。撤掉一篇转载，原稿还在，独立家族数不变。撤掉原稿，转载仍在记录里，但它们的 `derived_from` 失去可核的父记录时，这些转载改为不明，不得升格成独立原稿。

## 7. 不得触发的动作

无论四值是哪一个，都不得：

- 按域名个数或语气改写四值
- 用多数票取消 `conflict`
- 把不明当成独立
- 写入事实
- 采纳候选
- 接管执行
- 修改运行时、二进制、存档或再再个体
- 替再再作出最终事实判断

外部模型只可以提供资料和转译，不得写入事实，不得采纳候选，不得接管执行（an external model may only supply materials and translations, and may not write facts, adopt a candidate, or take over execution）。

## 8. 与现有材料的边界

任务包里的三行 `fixture_only` 种子（`dev-reprint`、`dev-conflict`、`dev-unknown-lineage`）是开发示意，不是公网事实，也不是本契约的验收集。

另一份原生议程日志记录的是别的场景。本契约不读取它，也不把它当成这次来源评测的结果。本契约给出的是字段、处理和预期，不是一次运行后的通过计数。
