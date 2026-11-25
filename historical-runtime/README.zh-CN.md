# 宿主的历史算法与冷读代码

predeploy-single-entry-r22-20261119 下另保留 11 个经 R28 父来源清单及 R22 自身发行清单双重核实的顶层 Python 程序。它的 R14 程序子树与 R28 内的源文件逐字节相同，仓库只收一份共享子树。R28 在此基础上调整了读回器及桥接等八个顶层文件，以 R28 版本为当前宿主的实际入口。

这里收录 Windows 宿主 2.4 直接使用的旧版运行算法与冷读器。offline-six-module-r28-20261120 子目录保留了受检软件包的相对文件结构。

## 运行依赖

- host/inner3.py 的 _load_seed 通过历史包中的 r14/bundle/lib/al01/__init__.py 建立一个独立命名空间，再动态导入 coupled_runtime、development、control_embryos 和 neural_control。它依赖 CoupledRuntime._decode 解释本地保存的数据。几何、控制、治理和记忆的相关程序在同一 al01 目录。历史清单会核对其中每个受管源文件。
- tools/cold_read.py 载入 R28 顶层的 common、provenance、world_link、cold，以及 R14 的 base、offline 和 original_action。world_link.cold_world 使用 IntegratedLife._decode 和登记回执重读历史检查点。R22 的登记与业务账本结构可在 bridge.py、r14/bundle/lib/original_action.py、r14/bundle/components/m5.sql 中查看。SQL 只含设置与建表语句。
- 历史代码校验入口会比较完整的 Python 成员集合，所以连原包本身登记的构建、驱动与验收程序也保留原始字节。r14/bundle/r12-protocol.json 是公开结构的三对象确定性测试协议，未包含个体的实际存档。
- R14 的 cli_frozen 和 folder_broker 保留对旧外部派发适配器的延迟导入。该冻结发行主动关闭真实翻译、具体主机资源写入和自动动作重放，包清单本身没有 attempt_gate、cli_diagnostic、broker_custody。当前 inner3 的数值导入和 R28 冷读的模块加载不使用这些主动派发适配器。

## 干净克隆如何使用

在仓库根打开 Python，把 historical-runtime/offline-six-module-r28-20261120/r14/bundle/lib 加入模块搜索路径，可以单独导入 al01 的程序。数值模块使用 NumPy。以下命令不创建身份、数据库或任何存档：

~~~text
python -B -c "import sys; sys.path.insert(0, 'historical-runtime/offline-six-module-r28-20261120/r14/bundle/lib'); from al01.coupled_runtime import CoupledRuntime; from al01 import development, control_embryos, neural_control; print(CoupledRuntime.__name__)"
~~~

现场宿主仍严格按 state/native/offline-six-module-r28-20261120/ 下的原布局和身份锚读取。延续已有个体时，部署方应使用自己经过完整性校验的兼容备份和对应的本地发行清单。该清单绑定运行解释器、依赖与原个体数据，公开的 SOURCE-MANIFEST.json 只校验公开程序。它不充当本地 FREEZE.json、parent-sources.json 或身份证明。源码阅读无需复制原机数据或启动后台进程。

旧包的 direct.cl 属于一次实际绑定的请求输入。公开源码没有带入该请求、互动正文、回执、私有冻结清单、保存的场、记忆、检查点或 SQLite 数据库。
