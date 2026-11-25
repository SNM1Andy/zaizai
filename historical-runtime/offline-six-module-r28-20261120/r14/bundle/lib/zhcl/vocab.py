# -*- coding: utf-8 -*-
"""冻结词汇表与协议常量（人工规则冻结，不随模型输出变化）。

本文件是协议真值的锚点之一：CL 模板、能力集、预算与状态词表全部在此冻结。
模型/provider 只能在该词表内提议，不能扩展操作、能力或权限。
"""
import hashlib
import json

# --- 协议版本与来源标记 -----------------------------------------------------
TRANSLATION_SCHEMA = 'zhcl-translation-1'
RECEIPT_SCHEMA = 'zhcl-receipt-1'
RULES_VERSION = 'zhcl-rules-1'
ORIGIN = 'ZH_CL_TRANSLATION'
AUTHORITY = 'NONE'  # 文本与模型不授予任何权限

# --- 复用的 CL 版本锚点（必须与冻结候选 al01.core / al01.contracts 一致）-----
# 校验器（validate_cl.py）会用真实模块的实际值逐项比对这两个常量。
CL_VERSION = 'CL-0.1-foundation-14'
REGISTRY_VERSION = 'neurons-0.5'

# --- 能力集（固定授予，最小权限；无 move、无 neuron）-------------------------
CAPS_GRANTED = ('read', 'observe', 'emit')

# --- 预算 -------------------------------------------------------------------
SOURCE_MAX_BYTES = 256      # 候选 CL 源串的 UTF-8 字节上限（协议层，严于解析器）
MENTION_MAX_BYTES = 512     # 澄清/反问文本的 UTF-8 字节上限

# --- 操作词表（folder_contracts.OPERATIONS 的子集 + 澄清）---------------------
OP_LIST_SCOPE = 'LIST_SCOPE'
OP_READ_TEXT = 'READ_TEXT'
OP_CHECK_ACCESS = 'CHECK_ACCESS'
OP_QUESTION = 'QUESTION'          # 反问/澄清：不产生 folder request
OPS = (OP_LIST_SCOPE, OP_READ_TEXT, OP_CHECK_ACCESS, OP_QUESTION)

ALLOWED_INTENTS = ('list', 'read_text')  # CHECK_ACCESS 仅允许这两种意图

# --- 流水线状态 -------------------------------------------------------------
STATUS_OK = 'OK'
STATUS_AMBIGUOUS = 'AMBIGUOUS'
STATUS_UNSUPPORTED = 'UNSUPPORTED'
PIPE_STATUSES = (STATUS_OK, STATUS_AMBIGUOUS, STATUS_UNSUPPORTED)

VERDICT_PROPOSED = 'PROPOSED'   # 候选已通过全部独立校验，但无执行回执
VERDICT_SUCCESS = 'SUCCESS'     # 有通过独立验证的执行回执（OK）
VERDICT_FAILED = 'FAILED'       # 有通过验证的失败回执（带类型化原因）
VERDICT_UNKNOWN = 'UNKNOWN'     # 无回执 / 回执不可验证 / 结果未知；绝不声称已执行
VERDICTS = (VERDICT_PROPOSED, VERDICT_SUCCESS, VERDICT_FAILED, VERDICT_UNKNOWN)

# --- 冻结的 CL 模板（候选 CL 源串只能等于这些模板，杜绝模型注入任意 CL）------
_TEMPLATES = {
    OP_LIST_SCOPE: 'EMIT(OK(value="LIST_SCOPE"));',
    OP_READ_TEXT: 'PROPOSE(OBSERVE(@{entry_ref}));',
    OP_CHECK_ACCESS: 'EMIT(OK(value="CHECK_ACCESS:{intent}"));',
    OP_QUESTION: 'EMIT(UNRESOLVED(mention={question}));',
}

# 从真实 Compiler/CVM 执行捕获并冻结的期望事务效果（见 dev/probe_cl_semantics.py）
EXPECTED_EFFECTS = {
    OP_LIST_SCOPE: dict(
        messages=[{'tag': 'OK', 'type': 'Result<Text>', 'value': 'LIST_SCOPE'}],
        proposals=[], neuron_calls=[], wait_reason=None),
    OP_READ_TEXT: dict(
        messages=[], proposals=[{'kind': 'observe', 'target': '{entry_ref}'}],
        neuron_calls=[], wait_reason=None),
    OP_CHECK_ACCESS: dict(
        messages=[{'tag': 'OK', 'type': 'Result<Text>', 'value': 'CHECK_ACCESS:{intent}'}],
        proposals=[], neuron_calls=[], wait_reason=None),
    OP_QUESTION: dict(
        messages=[{'unresolved_ref': {'mention': '{question}'}}],
        proposals=[], neuron_calls=[], wait_reason=None),
}

# 各操作所需的固定能力（模板静态声明，校验器用真实编译器的 CAPABILITY_DENIED 复核）
OP_CAPABILITIES = {
    OP_LIST_SCOPE: ('emit',),
    OP_READ_TEXT: ('read', 'observe', 'emit'),
    OP_CHECK_ACCESS: ('emit',),
    OP_QUESTION: ('emit',),
}


def cl_string(text):
    """把自然语言文本安全地放进 CL 字符串字面量（转义反斜杠与双引号）。"""
    if not isinstance(text, str):
        raise ValueError('CL string requires str')
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    return '"' + escaped + '"'


def template(operation, *, entry_ref=None, intent=None, question=None):
    """返回该操作的冻结 CL 源串；参数只能进入占位符。"""
    if operation == OP_LIST_SCOPE:
        return _TEMPLATES[OP_LIST_SCOPE]
    if operation == OP_READ_TEXT:
        return _TEMPLATES[OP_READ_TEXT].format(entry_ref=entry_ref)
    if operation == OP_CHECK_ACCESS:
        return _TEMPLATES[OP_CHECK_ACCESS].format(intent=intent)
    if operation == OP_QUESTION:
        return _TEMPLATES[OP_QUESTION].format(question=cl_string(question))
    raise ValueError('undeclared operation: %r' % (operation,))


def expected_effect(operation, *, entry_ref=None, intent=None, question=None):
    """该操作模板经真实 CVM 执行后的冻结期望事务效果（探针实测值）。"""
    if operation == OP_LIST_SCOPE:
        return EXPECTED_EFFECTS[OP_LIST_SCOPE]
    if operation == OP_READ_TEXT:
        return {
            'messages': [], 'proposals': [{'kind': 'observe', 'target': entry_ref}],
            'neuron_calls': [], 'wait_reason': None}
    if operation == OP_CHECK_ACCESS:
        return {
            'messages': [{'tag': 'OK', 'type': 'Result<Text>',
                          'value': 'CHECK_ACCESS:' + intent}],
            'proposals': [], 'neuron_calls': [], 'wait_reason': None}
    if operation == OP_QUESTION:
        return {
            'messages': [{'unresolved_ref': {'mention': question}}],
            'proposals': [], 'neuron_calls': [], 'wait_reason': None}
    raise ValueError('undeclared operation: %r' % (operation,))


def canonical(value):
    """协议内统一规范化序列化（与 al01.core.canonical 同语义）。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()


def message_id(operation, scope_ref, *, entry_ref=None, intent=None, question=None):
    """消息 ID：由冻结规则字段确定性导出；同文同参数必得同 ID。"""
    key = {'schema': TRANSLATION_SCHEMA, 'rules_version': RULES_VERSION,
           'operation': operation, 'scope_ref': scope_ref,
           'entry_ref': entry_ref, 'intent': intent, 'question': question}
    return 'req_' + digest(key)[:32]
