# Windows 宿主源码与本地运行

Python 宿主位于 host，管理、备份和恢复工具位于 tools。联合发行的中文解析适配器、运维和算子位于 releases/joint25。Grok 的独立来源观察库位于 integrations/grok，宿主内的来源准入实现位于 host/source_provenance25.py。

## 空目录和已有安装

干净克隆可以阅读源码和运行无状态接口。桌面应用启动时会导入 host/native.py，从安装根下的 state/native/joint-reopen.json 读取本地身份锚。host/service.py 以 SQLite 的 mode=rw 打开 state/dashboard-split.sqlite，再用 setup 维护现有宿主表。初始化这一套正式运行时还涉及原生受管个体、属主摘要、对话记录、登记的模块及可执行文件。仅建立一个空 SQLite 文件无法得到可用的桌面个体。

延续已有个体时，使用部署方自己的兼容发行、身份锚、受管存档和已核对的全量备份。需要安装根的 runtime/python.exe、bin 或 releases/joint25/bin 下的对应引擎、匹配的词典资产、安装清单和槽登记。备份工具要求先有可启动的同版宿主上下文，支持先恢复到新目录并核对。新建演示身份请使用原生发行文档的初始化流程，并为其生成自身的宿主登记资料。公开源码中的示例和开发自检不提供真实个体数据。

部分 Windows 验收工具按通用产品安装路径 D:/再再2.0 识别原安装，以便拒绝在原数据上运行故障演练。旧版迁移工具可通过 ZAIZAI_LEGACY_INSTALL 指定旧安装清单，用 ZAIZAI_LEGACY_SHORTCUT 指定旧入口。顾问接口使用用户本机已安装的 DeepSeek Harness，可以用 ZAIZAI_HARNESS_DIR 指定应用目录。公开的提供方名称和接口地址是代码常量。安装方自行配置其账户，宿主通过本机顾问接口发起已获准的请求。

## 教学材料

host/study3_assets/catalog.json 是三张原创公开示例卡。卡号 C-01、C-10、C-11 对应仓库自带的技术测验夹具，演示可检验预测、备份还原和来源时间核对。它们用于说明项目的摄取与校验结构。公开三卡未作为旧安装的课本、对话或实测成绩发布。

部署方可在自己的副本按相同 JSON 结构提供完整的本地课程。每项应含 id、title、summary、source_note、boundary、kind，source 和 sha256 对应可复查的课程来源和版本。operational_examples.json 和 frozen_exams.json 提供特定卡号的封存测验；独立测验摘要由 EXAM_PIN 固定。更换试卷时需重新验收并登记版本。已有资料不会随克隆自动迁移。

## 可独立使用的入口

- host/source_provenance25.py 提供同族合并、冲突和撤回后的来源判定。
- releases/joint25/language/zaizai_adapter 提供中文候选解析模块。
- host/corelex25.py 读取发布版的技术核心词义示例。扩展候选词库由单独授权的数据发行提供。
- tools/save_state.py 的 backup 和 restore-to 用于现有安装的本地备份与还原；restore-to 的目标必须是一个新目录。
