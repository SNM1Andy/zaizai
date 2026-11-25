# -*- coding: utf-8 -*-
"""R3 显式命令匹配：完整句精确匹配，默认澄清不动作。

判定顺序（命中即澄清，0 候选）：
  引语/转述 → 否定 → 条件/时间限定 → 指代 → 命令语法精确匹配 → 否则澄清。
仅当文本经规范化后与冻结命令完全相等（读取命令的 <相对路径> 必须与
上下文中条目相对路径精确一致）才产生动作候选。
"""
from . import vocab_r3


def normalize(text):
    if not isinstance(text, str):
        return ''
    s = ' '.join(text.split())
    if s.endswith('。'):
        s = s[:-1].rstrip()
    return s


def _has_any(text, markers):
    return any(m in text for m in markers)


def exact_entry(text, context):
    """精确匹配相对路径；返回 entry 或 None（不做模糊/大小写折叠）。"""
    for entry in context['entries']:
        if text == entry['relative_path']:
            return entry
    return None


def match_command(text, context):
    """返回 dict：
      {status: 'OK'|'AMBIGUOUS', reason, question, command}
    command ∈ {operation, entry_ref|intent} 仅当 status=='OK'。
    """
    if not isinstance(text, str) or not text.strip():
        return {'status': 'AMBIGUOUS', 'reason': vocab_r3.REASON_NOT_A_COMMAND,
                'question': vocab_r3.CLARIFY_QUESTIONS[vocab_r3.REASON_NOT_A_COMMAND],
                'command': None}
    s = normalize(text)
    if _has_any(s, vocab_r3.QUOTATION_MARKERS):
        return {'status': 'AMBIGUOUS', 'reason': vocab_r3.REASON_QUOTATION,
                'question': vocab_r3.CLARIFY_QUESTIONS[vocab_r3.REASON_QUOTATION],
                'command': None}
    if _has_any(s, vocab_r3.NEGATION_MARKERS):
        return {'status': 'AMBIGUOUS', 'reason': vocab_r3.REASON_NEGATED,
                'question': vocab_r3.CLARIFY_QUESTIONS[vocab_r3.REASON_NEGATED],
                'command': None}
    if _has_any(s, vocab_r3.CONDITIONAL_MARKERS):
        return {'status': 'AMBIGUOUS', 'reason': vocab_r3.REASON_CONDITIONAL,
                'question': vocab_r3.CLARIFY_QUESTIONS[vocab_r3.REASON_CONDITIONAL],
                'command': None}
    if _has_any(s, vocab_r3.REFERENCE_MARKERS):
        return {'status': 'AMBIGUOUS', 'reason': vocab_r3.REASON_REFERENCE,
                'question': vocab_r3.CLARIFY_QUESTIONS[vocab_r3.REASON_REFERENCE],
                'command': None}

    if s == vocab_r3.CMD_LIST:
        return {'status': 'OK', 'reason': None, 'question': None,
                'command': {'operation': 'LIST_SCOPE', 'entry_ref': None,
                            'intent': None}}
    if s.startswith(vocab_r3.CMD_READ_PREFIX):
        path = s[len(vocab_r3.CMD_READ_PREFIX):]
        entry = exact_entry(path, context)
        if entry is not None:
            return {'status': 'OK', 'reason': None, 'question': None,
                    'command': {'operation': 'READ_TEXT',
                                'entry_ref': entry['entry_ref'], 'intent': None}}
        return {'status': 'AMBIGUOUS', 'reason': vocab_r3.REASON_NOT_A_COMMAND,
                'question': '相对路径「%s」不在当前作用域；请用作用域内的精确相对路径。' % path,
                'command': None}
    if s == vocab_r3.CMD_CHECK_READ:
        return {'status': 'OK', 'reason': None, 'question': None,
                'command': {'operation': 'CHECK_ACCESS', 'entry_ref': None,
                            'intent': 'read_text'}}
    if s == vocab_r3.CMD_CHECK_LIST:
        return {'status': 'OK', 'reason': None, 'question': None,
                'command': {'operation': 'CHECK_ACCESS', 'entry_ref': None,
                            'intent': 'list'}}
    return {'status': 'AMBIGUOUS', 'reason': vocab_r3.REASON_NOT_A_COMMAND,
            'question': vocab_r3.CLARIFY_QUESTIONS[vocab_r3.REASON_NOT_A_COMMAND],
            'command': None}
