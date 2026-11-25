# CL / PCGM 原生工作台 (Linux x86_64 CPU)

- 独立 CL：`bin/cl --help` 或 `bin/cl capabilities`。
- C 语言：让自己的构建读取 `lib/pkgconfig/CLRuntime.pc`。用 `pkg-config --cflags --libs CLRuntime` 取参数。编译好的客户端如需跟随目录搬移，可将其放在 bin，设置 `\$ORIGIN/../lib` 的运行库搜索路径；具体编译命令见源码包里的验收程序。
- PCGM：`bin/pcgm-alpha`、`bin/pcgm-beta` 是同一个体的两个原生运行端。仅在你自己明确指定的状态路径执行，不会向任何外部机器上传，也不会启动后台常驻程序。
- `share/cl/fixtures` 是可检查的源码示例，不含正式再再数据。`MANIFEST.sha256.json` 描述整个目录的原始字节；另存可信的清单 SHA-256 可发现改包。

移动整个目录即可移动运行时，无需系统范围的安装。Linux CPU 实测；不要将包用于未验证的 Windows 或 CUDA。

## 两种 C SDK：用哪一个
- `CLRuntime`：包含文件型 CL 会话。用法不变。
- `CLMemory`：只传内存缓冲区。可以编译 CL、初始化证据、推导候选快照、封存并核验，不含文件会话。一个程序只选择其中一种 SDK；不要在同一链接进程同时引入两个同名 C ABI。
- `share/cl/examples/evidence-host.c`：真实的最简输入/输出宿主范例。Linux 下独立编译需要 C 编译器和 pkg-config；只运行 bin 下的命令不需要开发包。共享库需要和本机兼容的 glibc/libstdc++（工具链环境见交付说明），本包不是 Windows 文件。

在空目录解包前核对压缩文件的外部 SHA-256。解包后可用随包验证器验证完整目录：
```sh
ROOT="/绝对路径/CL-PCGM-0.163"
python3 "$ROOT/share/cl/verify-runtime.py" verify "$ROOT" "另行保存的清单SHA256"
"$ROOT/bin/cl" capabilities
```

## 不碰正式状态，先验证一条推理
下面的命令只在新建临时目录产生一个实验状态。第一问没有观察，应为 `UNKNOWN`；加入观察后，同样的问题应为 `POSITIVE`。
```sh
STATE_DIR=$(mktemp -d)
printf '%s\n' 'upper(negative,-7@token)' ':observe fresh quote(cny_cent,token,3,2)' 'upper(negative,-7@token)' |
  "$ROOT/bin/pcgm-alpha" --init-managed "$ROOT/share/cl/fixtures/observed-unit-conversion.cl" "$STATE_DIR/demo.state"
printf '%s\n' 'upper(negative,-7@token)' |
  "$ROOT/bin/pcgm-alpha" --resume "$STATE_DIR/demo.state"
```
本包在 Linux x86-64、GCC 14.2、glibc 2.41 环境构建和验收；没有替其他 Linux 发行版、Windows 或 CUDA 作结论。

共享库的 ELF 请求符号上限：`CLMemory` 为 GLIBC_2.32 / GLIBCXX_3.4.31，`CLRuntime` 为 GLIBC_2.34 / GLIBCXX_3.4.32。这些是二进制可查的要求，不等于在所有满足要求的发行版都已验收。命令行与 PCGM 执行端在本包中静态链接。

## CL 自编译与 Unicode 逻辑常量

```sh
profile="$ROOT/share/cl/profiles/unicode-forward.clcp"
pin=$(sha256sum "$profile" | cut -d' ' -f1)
scratch=$(mktemp -d)
"$ROOT/bin/cl" profile-build "$profile" "$pin" "$ROOT/share/cl/fixtures/unicode-example.cl" > "$scratch/example.clir"
"$ROOT/bin/cl" ir-json "$scratch/example.clir"
```

示例结果为 `POSITIVE`，带引号的中文和标点被当作一个 `sym` 常量。此流程
不启动 PCGM，也不写它的状态。CLMemory 的 `cl_profile_rebuild_v1` 和
`cl_profile_rebuild_audit_v1` 支持从固定输入重建并核验候选编译器，见随包
`share/cl/examples/profile-rebuild-host.c`。这两个接口均不替应用激活候选。

## 0.163 联合交接包的独立组件

联合包不是单一引擎。CL 编译与证明引擎是 **0.157**，本机 PCGM 双端是
**0.159**（接口基线）。清单分别记录两部分的版本；`"$ROOT/bin/cl" capabilities` 和
`"$ROOT/bin/pcgm-alpha" --capabilities` 可在不打开任何状态时分别查看。
PCGM 额外返回其正在运行的二进制自身摘要，不必靠外部文件名称辨认。

CL 的固定工作区准备接口可并发复用一次推理，见
`share/cl/examples/prepared-workspace-host.c`。PCGM 的历史观察审计用
当时的底稿和已提交请求重演，不读取今天的证据替代历史，也不执行决定。
二者都在本包的离线移目录验收中实测。
