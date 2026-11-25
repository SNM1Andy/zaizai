# -*- coding: utf-8 -*-
"""zhcl: 中文 <-> CL 双向转译纯组件协议（模块6，冻结有界基线）。

纯组件、离线、可注入外部 provider；本包不发起任何网络请求、不构造个体、
不执行工具、不注入主体学习。CL 校验复用冻结候选的真实 Compiler/CVM 纯
prepare/verify（见 cl_imports.py 的边界说明）。
"""
from . import vocab  # noqa: F401

__all__ = ['vocab']
