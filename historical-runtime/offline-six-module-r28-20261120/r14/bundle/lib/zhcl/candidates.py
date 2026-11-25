# -*- coding: utf-8 -*-
"""解释记录 → 转译候选（确定性构建，不依赖模型）。

每个候选携带：冻结 CL 源串、folder 请求（真实 folder_contracts 构造与
校验）、消息 ID（冻结规则确定性导出）、来源/版本标记与候选自摘要。
构建器只使用冻结模板；模型/provider 无法把任意 CL 塞进候选。
"""
from . import vocab

CANDIDATE_FIELDS = (
    'schema', 'candidate_id', 'operation', 'entry_ref', 'intent', 'question',
    'cl_version', 'registry_version', 'capabilities', 'source', 'request',
    'provenance',
)


def build_candidate(interpretation, context):
    """由单条解释意图构建候选 dict（不含 candidate_sha256）。"""
    operation = interpretation['operation']
    if operation not in vocab.OPS:
        raise ValueError('undeclared operation: %r' % (operation,))
    entry_ref = interpretation.get('entry_ref')
    intent = interpretation.get('intent')
    question = interpretation.get('question')

    scope_ref = context['scope_ref']
    candidate_id = vocab.message_id(operation, scope_ref, entry_ref=entry_ref,
                                    intent=intent, question=question)
    source = vocab.template(operation, entry_ref=entry_ref, intent=intent,
                            question=question)
    capabilities = list(vocab.OP_CAPABILITIES[operation])

    request = None
    if operation != vocab.OP_QUESTION:
        from .cl_imports import load
        _, folder_contracts = load()
        request = folder_contracts.make_request(
            operation, scope_ref, request_id=candidate_id,
            entry_ref=entry_ref, intent=intent)

    provenance = {
        'origin': vocab.ORIGIN,
        'authority': vocab.AUTHORITY,
        'rules_version': vocab.RULES_VERSION,
        'proposed_by': interpretation.get('proposed_by', 'rules'),
        'provider': interpretation.get('provider'),
        'provider_version': interpretation.get('provider_version'),
    }
    candidate = {
        'schema': vocab.TRANSLATION_SCHEMA,
        'candidate_id': candidate_id,
        'operation': operation,
        'entry_ref': entry_ref,
        'intent': intent,
        'question': question,
        'cl_version': vocab.CL_VERSION,
        'registry_version': vocab.REGISTRY_VERSION,
        'capabilities': capabilities,
        'source': source,
        'request': request,
        'provenance': provenance,
    }
    candidate['candidate_sha256'] = vocab.digest(candidate)
    return candidate


def interpret_to_candidates(record, context):
    """解释记录 → 候选列表（每条意图一个候选）。"""
    candidates = []
    for item in record['intents']:
        try:
            candidates.append(build_candidate(item, context))
        except ValueError as exc:
            # 词表外意图不会进入候选（防御性；解释层已过滤）
            candidates.append({'schema': vocab.TRANSLATION_SCHEMA,
                               'candidate_id': None, 'operation': item.get('operation'),
                               'build_error': str(exc)})
    if record['questions']:
        for question in record['questions']:
            item = {'operation': vocab.OP_QUESTION, 'entry_ref': None,
                    'intent': None, 'question': question, 'proposed_by': 'rules'}
            candidates.append(build_candidate(item, context))
    return candidates
