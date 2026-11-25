# 再再 · Zaizai

再再是一个在 Windows 本地运行的项目。桌面宿主保存会话，CL 为可核对的命题生成证明，PCGM 根据观察、规则和证据状态给出结论。本仓库收录联合发行 **2026.11.25-win.2.4** 的程序源码、工程文档和可公开复用的示例。

## 目录

| 目录 | 内容 |
| --- | --- |
| [native/source](native/source) | CL、PCGM、C 接口、Windows 文件与计算后端、语言配置和测试夹具 |
| [native/tools](native/tools) | Windows x64 原生构建脚本 |
| [native/sdk](native/sdk) | 两种 C 接口的公共头文件和并发读取示例 |
| [host](host) 与 [tools](tools) | 桌面对话、后台问询、词义治理以及本地管理工具 |
| [releases/joint25](releases/joint25) | Gemini 中文适配、版本化操作词汇与宿主对接 |
| [historical-runtime](historical-runtime/README.zh-CN.md) | R28、R22 的宿主算法与模块读取器，可从干净克隆导入 |
| [materials](materials) | 技术词典、公开课程、来源契约与词典重建工具 |
| [docs](docs) | 项目蓝图、接口与本地运行说明 |

## 构建 Windows 原生引擎

在已安装 Visual Studio 2022 x64 C++ Build Tools 和 Windows SDK 的机器上，从仓库根目录运行：

```powershell
python -B -X utf8 .\native\tools\build.py
.\native\bin\cl.exe capabilities
.\native\bin\pcgm-alpha.exe --capabilities
```

原生 CL、PCGM 和 C 接口可以从源码独立构建。桌面宿主的运行还需要本地 Python 环境、已初始化的个体存档和登记过的引擎。准备运行桌面宿主时，请先阅读[宿主运行说明](docs/windows-host-setup.zh-CN.md)。本仓库分发公共教学示例；个人会话、记忆、运行回执和登录配置由各自的本地安装保存。

## 词典与课程

[材料目录](materials) 包含 500 条 CL 技术义项、公开课程、来源判定契约、词典样例和重建工具。20 万词典的公开数据按版本随 Release 交付。词典保留候选或待审状态，字段、归属与许可见[词典说明](materials/lexicon-200k/ATTRIBUTION.md)。

完整数据下载：[cl-lexicon-200k-public-r001-r002.zip](https://github.com/SNM1Andy/zaizai/releases/download/public-data-2.4/cl-lexicon-200k-public-r001-r002.zip)。SHA-256 为 bbddb3009440f34c1ada7a2cf9501516bc573dc0b0af8efa9d063c9a32137c1e。

## 工程资料

- [CL 与 PCGM](docs/cl-pcgm.zh-CN.md)
- [宿主槽接口](docs/host-slots-31.zh-CN.md)
- [来源与证据](docs/source-provenance.zh-CN.md)
- [公开宿主版本的来源和调整](docs/source-notes.zh-CN.md)

各目录保留原有的来源和许可说明。数据集的使用条件见相应数据目录。

Windows GPU 后端沿用本地安装的共享准入时钟。该目录不可用时使用 CPU。项目源码暂未统一指定开源许可证，第三方数据遵循相应目录所附条款。
