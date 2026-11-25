# -*- coding: utf-8 -*-
"""候选 CL 的独立校验（与模型/provider 无关的确定性裁决）。

校验面：结构字段、版本/来源、消息 ID 重算、folder 请求绑定、预算、
作用域/陈旧引用、重复 ID 策略，以及——最关键——真实 Compiler/CVM 的
纯 prepare/verify（解析/类型/操作码/能力/效果形状逐一复核）。

文本与模型不授予权限：候选能力固定来自冻结模板；任何越权 CL
（MOVE/CALL/未知操作码/未知引用）都会被真实编译器以
CAPABILITY_DENIED / UNKNOWN_OPCODE / UNRESOLVED_REF 拒绝。
"""
from . import vocab
from .candidates import CANDIDATE_FIELDS

ERROR_STALE_VERSION = 'STALE_VERSION'
ERROR_STALE_REGISTRY = 'STALE_REGISTRY'
ERROR_BAD_ORIGIN = 'BAD_ORIGIN'
ERROR_BAD_FIELDS = 'BAD_FIELDS'
ERROR_MESSAGE_ID = 'MESSAGE_ID_MISMATCH'
ERROR_REQUEST = 'REQUEST_INVALID'
ERROR_SOURCE_BUDGET = 'SOURCE_BUDGET_EXCEEDED'
ERROR_MENTION_BUDGET = 'MENTION_BUDGET_EXCEEDED'
ERROR_STALE_REF = 'STALE_REF'
ERROR_TEMPLATE_DRIFT = 'TEMPLATE_DRIFT'
ERROR_DUPLICATE_REJECT = 'DUPLICATE_ID_DIFFERENT_CONTENT'
DUPLICATE_IDEMPOTENT = 'DUPLICATE_ID_IDEMPOTENT'


class ValidationRecord:
    def __init__(self):
        self.passed = False
        self.checks = {}
        self.errors = []

    def fail(self, code, detail):
        self.errors.append({'code': code, 'detail': detail})

    def as_dict(self):
        return {'passed': self.passed, 'checks': self.checks, 'errors': self.errors}


def _check(record, name, ok, code=None, detail=None):
    record.checks[name] = bool(ok)
    if not ok and code is not None:
        record.fail(code, detail or name)
    return bool(ok)


def validate(candidate, context, registry, cl_src=None):
    """独立校验一个候选；返回 (ok, ValidationRecord)。registry 实现重复 ID 策略。"""
    record = ValidationRecord()
    core, folder_contracts = _load_modules(cl_src)

    # 1) 结构字段
    if not isinstance(candidate, dict) or set(candidate) != set(CANDIDATE_FIELDS) | {'candidate_sha256'}:
        _check(record, 'fields', False, ERROR_BAD_FIELDS, 'candidate fields')
        return False, record
    _check(record, 'fields', True)

    # 2) 版本/来源（冻结锚点 + 真实模块实值）
    actual_version = core.VERSION
    actual_registry = _registry_version(core)
    _check(record, 'cl_version',
           candidate['cl_version'] == vocab.CL_VERSION == actual_version,
           ERROR_STALE_VERSION, 'cl_version %r vs %r' % (candidate.get('cl_version'), actual_version))
    _check(record, 'registry_version',
           candidate['registry_version'] == vocab.REGISTRY_VERSION == actual_registry,
           ERROR_STALE_REGISTRY, 'registry_version mismatch')
    provenance = candidate.get('provenance') or {}
    _check(record, 'origin', provenance.get('origin') == vocab.ORIGIN, ERROR_BAD_ORIGIN, 'provenance origin')
    _check(record, 'authority', provenance.get('authority') == vocab.AUTHORITY, ERROR_BAD_ORIGIN,
           'provenance authority must be NONE')
    _check(record, 'rules_version', provenance.get('rules_version') == vocab.RULES_VERSION,
           ERROR_BAD_ORIGIN, 'rules_version')
    _check(record, 'capabilities',
           sorted(candidate.get('capabilities') or []) == sorted(vocab.OP_CAPABILITIES[candidate['operation']])
           and set(candidate['capabilities']) <= set(vocab.CAPS_GRANTED),
           ERROR_TEMPLATE_DRIFT, 'capability set must equal the frozen template grant')

    # 3) 消息 ID 重算 + folder 请求绑定
    op = candidate.get('operation')
    expected_id = vocab.message_id(op, context['scope_ref'],
                                   entry_ref=candidate.get('entry_ref'),
                                   intent=candidate.get('intent'),
                                   question=candidate.get('question'))
    _check(record, 'message_id',
           candidate.get('candidate_id') == expected_id
           and (candidate.get('request') is None or
                candidate['request']['request_id'] == expected_id),
           ERROR_MESSAGE_ID, 'request_id must equal recomputed message id')
    if op != vocab.OP_QUESTION:
        request = candidate.get('request')
        request_ok = False
        try:
            folder_contracts.validate_request(request)
            # 独立重算（与 folder_contracts.request_sha256 同规范、不同实现路径）
            import hashlib
            independent = hashlib.sha256(
                vocab.canonical(request).encode('utf8')).hexdigest()
            request_ok = (folder_contracts.request_sha256(request) == independent)
        except Exception as exc:  # noqa: BLE001 — 捕获并记录，不吞语义
            record.fail(ERROR_REQUEST, '%s: %s' % (type(exc).__name__, exc))
        _check(record, 'request', request_ok, ERROR_REQUEST, 'folder request binding/limits')

    # 4) 预算
    source = candidate.get('source') or ''
    source_bytes = len(source.encode('utf8'))
    _check(record, 'source_budget', source_bytes <= vocab.SOURCE_MAX_BYTES,
           ERROR_SOURCE_BUDGET, '%d bytes > %d' % (source_bytes, vocab.SOURCE_MAX_BYTES))
    if op == vocab.OP_QUESTION:
        mention_bytes = len((candidate.get('question') or '').encode('utf8'))
        _check(record, 'mention_budget', 0 < mention_bytes <= vocab.MENTION_MAX_BYTES,
               ERROR_MENTION_BUDGET, '%d bytes' % mention_bytes)

    # 5) 作用域/陈旧引用
    if op == vocab.OP_READ_TEXT:
        refs = {e['entry_ref'] for e in context['entries']}
        _check(record, 'entry_in_scope', candidate.get('entry_ref') in refs,
               ERROR_STALE_REF, 'entry_ref not in current frozen listing')
    if op == vocab.OP_CHECK_ACCESS:
        _check(record, 'intent_allowed', candidate.get('intent') in vocab.ALLOWED_INTENTS,
               ERROR_TEMPLATE_DRIFT, 'forbidden access intent')

    # 6) 模板精确一致（防止任何非冻结 CL 进入）
    expected_source = vocab.template(op, entry_ref=candidate.get('entry_ref'),
                                     intent=candidate.get('intent'),
                                     question=candidate.get('question'))
    _check(record, 'template_exact', source == expected_source,
           ERROR_TEMPLATE_DRIFT, 'source must equal the frozen template')

    # 7) 真实 Compiler/CVM 纯 prepare/verify
    try:
        visible = tuple(e['entry_ref'] for e in context['entries'])
        ir = core.Compiler(visible, vocab.CAPS_GRANTED).compile(source)
        _check(record, 'ir_version', ir.get('version') == vocab.CL_VERSION,
               ERROR_STALE_VERSION, 'compiled ir version')
        vm = core.CVM(vocab.CAPS_GRANTED)
        tx = vm.prepare(source, {'version': 0, 'world_version': 0}, visible)
        vm.verify(tx)
        payload = core.transaction_payload(tx)
        _check(record, 'payload_ir_binding', payload.get('ir') == ir, ERROR_TEMPLATE_DRIFT, 'ir binding')
        _check(record, 'payload_versions',
               payload.get('state_version') == 0 and payload.get('world_version') == 0,
               ERROR_TEMPLATE_DRIFT, 'state/world version')
        expected_effect = vocab.expected_effect(
            op, entry_ref=candidate.get('entry_ref'), intent=candidate.get('intent'),
            question=candidate.get('question'))
        effect_ok = (payload.get('messages') == expected_effect['messages']
                     and payload.get('proposals') == expected_effect['proposals']
                     and payload.get('neuron_calls') == expected_effect['neuron_calls']
                     and payload.get('wait_reason') == expected_effect['wait_reason'])
        _check(record, 'effects_exact', effect_ok, ERROR_TEMPLATE_DRIFT,
               'payload effects must equal the frozen executed template')
        _check(record, 'operation_count_bounded', ir.get('operation_count', 9999) <= 256,
               ERROR_SOURCE_BUDGET, 'ir operation count')
    except core.CLError as exc:
        # 真实编译器的拒绝原样记录：CAPABILITY_DENIED/UNKNOWN_OPCODE/
        # UNRESOLVED_REF/TYPE_ERROR/BUDGET_EXCEEDED/...
        record.checks['real_cl'] = False
        record.fail('CL_' + exc.code, str(exc))
    else:
        record.checks['real_cl'] = True

    # 8) 自摘要 + 重复 ID 策略（同文幂等，异文拒绝）
    recomputed_sha = vocab.digest({k: candidate[k] for k in CANDIDATE_FIELDS})
    _check(record, 'self_digest', candidate.get('candidate_sha256') == recomputed_sha,
           ERROR_TEMPLATE_DRIFT, 'candidate_sha256 recomputation')
    cid = candidate.get('candidate_id')
    sha = candidate.get('candidate_sha256')
    if cid in registry:
        if registry[cid] == sha:
            record.checks['duplicate_policy'] = DUPLICATE_IDEMPOTENT
        else:
            record.checks['duplicate_policy'] = False
            record.fail(ERROR_DUPLICATE_REJECT, 'same id, different content')
    else:
        record.checks['duplicate_policy'] = True

    record.passed = bool(record.checks.get('fields')) and not record.errors
    return record.passed, record


def _load_modules(cl_src):
    from .cl_imports import load
    return load(cl_src)


def _registry_version(core):
    from al01 import contracts
    return contracts.REGISTRY_VERSION
