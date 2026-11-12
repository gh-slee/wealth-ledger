"""Explicit reusable parser context from verified, already committed evidence."""
import hashlib
import json

from . import source_ingestion as ingestion
from .source_pipeline import bounded_read, NORMALIZED_BYTES
from .source_submission import SubmissionError

PERSISTENT = frozenset({'account_alias', 'source_timezone', 'format_selection'})


def source_profiles(project):
    """No new settings store or parser calls; revisions/timestamps are never reused."""
    ingestion.verify_store(project)
    conn = ingestion._open(project)
    try:
        if not ingestion._schema(conn): return []
        profiles = {}
        for row in ingestion._rows(conn, 'src_batches'):
            raw = bounded_read(ingestion._archive_path(project, row['canonical_path']), NORMALIZED_BYTES)
            if hashlib.sha256(raw).hexdigest() != row['canonical_sha256']: raise SubmissionError('source_integrity')
            value = json.loads(raw)
            context = value['evidence']['context']
            options = {key: context[key] for key in sorted(PERSISTENT) if context.get(key) is not None}
            identity = {'adapter_id': row['adapter_id'], 'options': options}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            profiles[key] = {'id': key, 'provider_id': row['provider'], **identity,
                             'label': options.get('account_alias') or row['adapter_id']}
            if len(profiles) > 200: raise SubmissionError('context_profile_limit')
        return sorted(profiles.values(), key=lambda item: (item['provider_id'], item['label'], item['id']))
    finally:
        if conn: conn.close()


def resolve_profiles(project, options, count, selections):
    if not isinstance(options, (tuple, list)) or options and len(options) != count:
        raise SubmissionError('invalid_context')
    choices = options or [{} for _ in range(count)]
    if any(not isinstance(choice, dict) for choice in choices): raise SubmissionError('invalid_context')
    profiles = {item['id']: item for item in source_profiles(project)} if any('profile_id' in item for item in choices) else {}
    selected = dict(selections or {})
    resolved = []
    for slot, item in enumerate(choices, 1):
        choice = dict(item)
        if 'profile_id' in choice:
            profile_id = choice.pop('profile_id')
            if not isinstance(profile_id, str) or not ingestion.SHA.fullmatch(profile_id): raise SubmissionError('invalid_context_profile')
            profile = profiles.get(profile_id)
            if not profile or PERSISTENT & choice.keys(): raise SubmissionError('invalid_context_profile')
            if str(slot) in selected and selected[str(slot)] != profile['adapter_id']:
                raise SubmissionError('invalid_context_profile')
            selected[str(slot)] = profile['adapter_id']
            choice = {**profile['options'], **choice}
        resolved.append(choice)
    return resolved, selected


def investment_accounts(project):
    """Verified bound investment identities for dated manual cash declarations."""
    ingestion.verify_store(project)
    conn = ingestion._open(project)
    try:
        if not ingestion._schema(conn): return []
        bindings = {(r['provider'], r['source_account']): r for r in ingestion._rows(conn, 'src_bindings')}
        result = {}
        for row in ingestion._rows(conn, 'src_batches'):
            raw = bounded_read(ingestion._archive_path(project, row['canonical_path']), NORMALIZED_BYTES)
            if hashlib.sha256(raw).hexdigest() != row['canonical_sha256']: raise SubmissionError('source_integrity')
            value = json.loads(raw)
            for account in value['accounts']:
                if account['role'] != 'investment': continue
                binding = bindings[(account['key']['provider'], account['key']['account_id'])]
                result[binding['ledger_account']] = {'account_id': binding['ledger_account'],
                    'label': account['label'], 'masked_number': account['masked_identifier']}
        return sorted(result.values(), key=lambda row: row['account_id'])
    finally:
        if conn: conn.close()
