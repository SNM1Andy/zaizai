# CL official buffer-only SDK build excludes native filesystem adapters

Separate genuine CL compiler/proof code from Linux-owned leases, file journals, audit streams, resolver directory reads, and command drivers. Build a second SDK image from the same sources with that OS layer unavailable during compilation; declare its exact supported C ABI feature bits. Keep in-memory package/workspace compile and proofs, freeze/verify sealed evidence when given bytes, diagnostics and accelerator contract. The full native build is unchanged. A Windows link or execution has not been validated.

Acceptance: actual detached native C consumer works with only its buffer SDK plus explicitly provided pinned artifacts; exact proof bytes match normal CL. Verify nonlinked Linux native-file symbols and no file lease/session APIs in the buffer SDK, full SDK still exports both paths, errors remain deterministic and resources bounded. Build from same source in a clean Linux directory; no Alice or CUDA.

## 使用和平台边界

`make memory-sdk` 生成 `libcl_memory.so`，以 `cl-memory-api.h` 接入。这个版本不编译 Linux 目录、持久锁、文件会话或独立 CLI 接口。输入和输出都用调用者的缓冲区；仍可验证完整工作区、编译、求证、核验已有日志字节。查询 `cl_runtime_features_v1` 可分辨缓冲区能力与持久化文件能力。完整 `libcl_runtime.so` 两种能力都保留。`libcl_memory.so` 是在 Linux CPU 上验证过的移植基础，Windows 工具链和二进制仍未验证，不当作已经发布的 Windows 版本。
