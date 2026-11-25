# -*- coding: utf-8 -*-
"""R3 冻结词表与契约常量：显式命令语法、澄清原因码、回执契约。"""
import hashlib
import json

R3_SCHEMA = 'zhcl-r3-command-1'
R3_RECEIPT_SCHEMA = 'zhcl-receipt-r3-1'

# --- 基本交互的显式命令语法（完整句精确匹配，冻结）---------------------------
CMD_LIST = '列出目录'
CMD_READ_PREFIX = '读取 '          # 读取 <相对路径精确匹配>
CMD_CHECK_READ = '检查 读取'       # CHECK_ACCESS(read_text)
CMD_CHECK_LIST = '检查 列表'       # CHECK_ACCESS(list)

# --- 澄清原因码（默认不产生动作；未知一律澄清）--------------------------------
REASON_NEGATED = 'NEGATED'
REASON_CONDITIONAL = 'CONDITIONAL'
REASON_QUOTATION = 'QUOTATION'
REASON_REFERENCE = 'REFERENCE'
REASON_NOT_A_COMMAND = 'NOT_A_COMMAND'
REASON_AMBIGUOUS = 'AMBIGUOUS'
CLARIFY_REASONS = (REASON_NEGATED, REASON_CONDITIONAL, REASON_QUOTATION,
                   REASON_REFERENCE, REASON_NOT_A_COMMAND, REASON_AMBIGUOUS)

# 冻结标记集（保守：出现即澄清，不动作）
NEGATION_MARKERS = ('不', '别', '勿', '禁止', '无须', '无需', '拒绝', '莫要')
CONDITIONAL_MARKERS = ('如果', '假如', '要是', '若', '明天', '下次', '稍后',
                       '之后', '以后', '未来', '等')
QUOTATION_MARKERS = ('"', '“', '”', '‘', '’', '「', '」', '『', '』')
REFERENCE_MARKERS = ('它', '这个', '那个', '这些', '那些', '该文件', '此文件',
                     '上面', '上述', '刚才', '提到', '指代', '前面')

# --- 回执契约 -----------------------------------------------------------------
RECEIPT_ORIGINS = ('SYNTHETIC', 'REAL', 'UNKNOWN')   # 严格枚举
R3_RECEIPT_FIELDS = ('schema', 'origin', 'request', 'result', 'receipt_sha256')

# 终态
VERDICT_PROPOSED = 'PROPOSED'
VERDICT_SUCCESS = 'SUCCESS'
VERDICT_FAILED = 'FAILED'
VERDICT_UNKNOWN = 'UNKNOWN'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()


def receipt_sha256(origin, request, result):
    return digest({'schema': R3_RECEIPT_SCHEMA, 'origin': origin,
                   'request': request, 'result': result})


CLARIFY_QUESTIONS = {
    REASON_NEGATED: '这句话是否定表达；系统不会生成任何动作候选。如需执行，请用显式命令：'
                    '「列出目录」「读取 <相对路径>」「检查 读取」「检查 列表」。',
    REASON_CONDITIONAL: '这句话带条件或时间限定；条件未满足时不产生动作候选。'
                        '条件满足后请用显式命令重新表述。',
    REASON_QUOTATION: '这句话是转述/引语，不作为指令执行。如需执行，请用显式命令直接表述。',
    REASON_REFERENCE: '这句话包含指代，无法确定目标；请给出作用域内的具体相对路径。',
    REASON_NOT_A_COMMAND: '这句话不是受支持的显式命令。当前仅支持：'
                          '「列出目录」「读取 <相对路径>」「检查 读取」「检查 列表」。',
    REASON_AMBIGUOUS: '这句话含义不明确；请用显式命令重新表述。',
}
