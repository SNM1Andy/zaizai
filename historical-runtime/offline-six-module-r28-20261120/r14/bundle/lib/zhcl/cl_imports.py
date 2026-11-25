# -*- coding: utf-8 -*-
"""对冻结候选 CL 源码的延迟只读导入。

边界说明：
  * 只导入 al01.core / al01.folder_contracts 两个纯模块（模块级仅有定义，
    无 I/O、无锁、无进程副作用；见冻结候选源码与本轮探针实测）。
  * 用途仅限纯 prepare/verify 校验：Compiler.compile、CVM.prepare/verify、
    transaction_payload、folder_contracts 的请求/回执校验。
  * 这不等于主体接入：不构造 Individual/runtime，不取锁，不执行工具，
    不产生出生/回调/外部效应。
"""
from pathlib import Path

DEFAULT_CL_SRC = Path(__file__).resolve().parents[1]


def load(cl_src=None):
    """Load the validation modules bundled beside this package."""
    if cl_src is not None and Path(cl_src).resolve() != DEFAULT_CL_SRC:
        raise ValueError("R4 requires its bundled validation source")
    from al01 import core, folder_contracts
    for module in (core, folder_contracts):
        if Path(module.__file__).resolve().parent != DEFAULT_CL_SRC / "al01":
            raise ImportError("R4 validation module identity mismatch")
    return core, folder_contracts
