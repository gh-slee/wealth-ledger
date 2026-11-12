"""Fixed ingestion storage structure; this is not full migration acceptance."""
import json
import hashlib
import os
import secrets
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
import re
import unittest

from kurafolio.persistence import ingestion_schema as schema

ORACLE = json.loads((Path(__file__).parent / 'fixtures/ingestion/oracle.json').read_text())


class IngestionStorageDDLTests(unittest.TestCase):
    def test_inventory_is_the_exact_closed_contract_and_copy_isolated(self):
        expected = ORACLE['sql-inventory']
        self.assertEqual(expected, schema.inventory())
        actual = schema.inventory()
        actual['tables'].clear()
        self.assertEqual(expected, schema.inventory())
        self.assertEqual(22, len(expected['tables']))
        self.assertEqual(19, len(schema.TENANT_TABLES))
        self.assertEqual(52, len(expected['foreign_keys']))
        self.assertEqual(22, len(expected['triggers']))

    def test_tables_have_exact_columns_and_only_reviewed_generated_targets(self):
        sql = schema.tables_ddl()
        names = re.findall(r'CREATE TABLE wl_ingestion\.([a-z_]+)\(', sql)
        self.assertEqual(list(schema.TABLES), names)
        self.assertEqual(2, sql.count('GENERATED ALWAYS AS'))
        self.assertIn('entity_id uuid GENERATED ALWAYS AS (COALESCE(account_id,instrument_id,issuer_id)) STORED NOT NULL', sql)
        self.assertIn('entity_version text GENERATED ALWAYS AS (COALESCE(account_version,instrument_version,issuer_version)) STORED NOT NULL', sql)
        for forbidden in ('CREATE EXTENSION', 'CREATE TYPE', 'CREATE SEQUENCE', 'CREATE VIEW',
                          'IF NOT EXISTS', 'ON DELETE CASCADE', 'ON UPDATE CASCADE'):
            self.assertNotIn(forbidden, sql)

    def test_all_tenant_tables_force_rls_and_exact_scope_policies(self):
        sql = schema.tables_ddl()
        policies = schema.policies_ddl('synthetic_reader', 'synthetic_operator')
        self.assertEqual(19, sql.count('ENABLE ROW LEVEL SECURITY'))
        self.assertEqual(19, sql.count('FORCE ROW LEVEL SECURITY'))
        self.assertEqual(19, policies.count('CREATE POLICY runtime_scope'))
        self.assertEqual(19, policies.count('CREATE POLICY operator_scope'))
        self.assertEqual(19, policies.count('TO "synthetic_reader"'))
        self.assertEqual(19, policies.count("current_setting('ledger.tenant_id',true)"))
        self.assertEqual(19, policies.count("current_setting('ledger.portfolio_id',true)"))
        for role in ('public', 'a;DROP SCHEMA wl_pg', 'a"b', '', 'a' * 64):
            with self.assertRaises(ValueError):
                schema.policies_ddl(role, 'synthetic_operator')
        with self.assertRaises(ValueError):
            schema.policies_ddl('same_role', 'same_role')

    def test_all_fks_are_scoped_no_cascade_and_initially_deferred(self):
        sql = schema.tables_ddl()
        expected = ORACLE['sql-inventory']['foreign_keys']
        self.assertEqual(52, sql.count('DEFERRABLE INITIALLY DEFERRED'))
        for row in expected:
            with self.subTest(constraint=row['name']):
                text = ('CONSTRAINT ' + row['name'] + ' FOREIGN KEY(' + ','.join(row['columns']) +
                        ') REFERENCES ' + row['target'] + '(' + ','.join(row['target_columns']) + ')')
                self.assertIn(text, sql)

    def test_no_raw_payload_or_filename_column(self):
        for table in schema.inventory()['tables']:
            for column in table['columns']:
                self.assertNotIn(column['name'], {'raw', 'raw_payload', 'raw_csv', 'filename', 'source_fields'})
                if column['name'] == 'raw_bytes':
                    self.assertEqual('bigint', column['type'])

    def test_byte_limits_unknown_nulls_and_distinct_generation_fields(self):
        sql = schema.tables_ddl()
        self.assertIn('accepted_generation bigint NOT NULL', sql)
        self.assertIn('mapping_generation bigint NOT NULL', sql)
        self.assertIn('control_generation bigint NOT NULL', sql)
        self.assertIn('(last_request_id IS NULL)=(last_result_bytes IS NULL)', sql)
        self.assertIn('pg_catalog.octet_length(last_result_bytes) BETWEEN 1 AND 16384', sql)
        self.assertIn('pg_catalog.octet_length(minimal_bytes) BETWEEN 1 AND 4194304', sql)
        self.assertIn('pg_catalog.octet_length(review_bytes)+COALESCE(pg_catalog.octet_length(plan_bytes),0)<=16777216', sql)
        self.assertIn('expires_at=created_at+interval \'86400 seconds\'', sql)

    def test_gateway_worker_and_helpers_have_separate_exact_signatures(self):
        self.assertEqual(9, len(schema.GATEWAY))
        self.assertEqual(8, len(schema.WORKER))
        self.assertFalse(set(schema.GATEWAY) & set(schema.WORKER))
        self.assertEqual('wl_ingestion.claim_member_v1(uuid,text,jsonb,bytea)',
                         schema.signature('claim_member_v1'))
        self.assertEqual('wl_ingestion.accept_preview_v1(text,uuid,bigint,jsonb,text,jsonb)',
                         schema.signature('accept_preview_v1'))
        with self.assertRaises(ValueError):
            schema.signature('unreviewed_function')
        self.assertNotIn('GRANT ', schema.tables_ddl())

    def test_trigger_inventory_is_exact_and_not_activated_by_tables(self):
        sql = schema.triggers_ddl()
        self.assertEqual(22, sql.count('CREATE TRIGGER'))
        self.assertNotIn('CREATE TRIGGER', schema.tables_ddl())
        for row in schema.inventory()['triggers']:
            self.assertIn('EXECUTE FUNCTION wl_ingestion.' + row['function'] + '();', sql)

    def test_cancel_matches_its_gateway_declaration(self):
        declared = {x['name']: x for x in schema.inventory()['functions']}['cancel_set_v1']
        self.assertEqual((['text', 'uuid', 'bigint', 'jsonb', 'text', 'jsonb'], 'jsonb', 'identity_source_gateway'),
                         (declared['arguments'], declared['returns'], declared['execute']))
        self.assertIn('REVOKE ALL ON FUNCTION wl_ingestion.cancel_set_v1(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;',
                      schema.CANCEL_DDL)
        self.assertEqual(1, schema.CANCEL_DDL.count('CREATE FUNCTION'))
        for fragment in ('GRANT ', 'SESSION_RECHECK', 'SET_RESULT', 'DELETE ', '_effects_v1', '_quota_v1'):
            self.assertNotIn(fragment, schema.CANCEL_DDL)

    def test_decide_and_reads_match_their_gateway_declarations(self):
        declared = {x['name']: x for x in schema.inventory()['functions']}
        for name, ddl in (('decide_set_v1', schema.DECIDE_DDL), ('read_set_v1', schema.READ_SET_DDL),
                          ('read_receipt_v1', schema.READ_RECEIPT_DDL)):
            with self.subTest(function=name):
                self.assertEqual((['text', 'uuid', 'bigint', 'jsonb', 'text', 'jsonb'], 'jsonb', 'identity_source_gateway'),
                    (declared[name]['arguments'], declared[name]['returns'], declared[name]['execute']))
                self.assertIn('REVOKE ALL ON FUNCTION wl_ingestion.' + name +
                              '(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;', ddl)
                self.assertEqual(1, ddl.count('CREATE FUNCTION'))
                for fragment in ('GRANT ', 'SESSION_RECHECK', 'SET_RESULT', 'HELD_BYTES', 'UUID_RE',
                                 'DECISIONS_SHAPE', 'DELETE ', '_effects_v1'):
                    self.assertNotIn(fragment, ddl)
        # Reads never write or lock.
        for ddl in (schema.READ_SET_DDL, schema.READ_RECEIPT_DDL):
            self.assertNotRegex(ddl, r'\b(INSERT|UPDATE|FOR UPDATE|FOR SHARE)\b')

    def test_paged_reads_match_their_gateway_declarations(self):
        declared = {x['name']: x for x in schema.inventory()['functions']}
        for name, ddl in (('read_sets_v1', schema.READ_SETS_DDL), ('read_preview_v1', schema.READ_PREVIEW_DDL)):
            with self.subTest(function=name):
                self.assertEqual((['text', 'uuid', 'bigint', 'jsonb', 'text', 'jsonb'], 'jsonb', 'identity_source_gateway'),
                    (declared[name]['arguments'], declared[name]['returns'], declared[name]['execute']))
                self.assertIn('REVOKE ALL ON FUNCTION wl_ingestion.' + name +
                              '(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;', ddl)
                self.assertEqual(1, ddl.count('CREATE FUNCTION'))
                for fragment in ('GRANT ', 'SESSION_RECHECK', 'SET_RESULT', 'CURSOR_PRELUDE', 'NEXT_CURSOR',
                                 'UUID_RE', 'PAGE_BYTES', 'pg_catalog.least(', 'pg_catalog.extract('):
                    self.assertNotIn(fragment, ddl)
                # Reads never write or lock, and SQL never holds the cursor key.
                self.assertNotRegex(ddl, r'\b(INSERT|UPDATE|DELETE|FOR UPDATE|FOR SHARE|hmac)\b')

    def test_worker_guard_matches_its_private_declaration(self):
        declared = {x['name']: x for x in schema.inventory()['functions']}['_guard_worker_v1']
        ddl = schema.worker_guard_ddl()
        self.assertEqual((['uuid', 'text', 'jsonb'], 'jsonb', 'operator_owner_only'),
                         (declared['arguments'], declared['returns'], declared['execute']))
        self.assertIn('REVOKE ALL ON FUNCTION wl_ingestion._guard_worker_v1(uuid,text,jsonb) FROM PUBLIC;', ddl)
        self.assertIn('w.login_role IS DISTINCT FROM session_user', ddl)
        self.assertEqual(1, ddl.count('CREATE FUNCTION'))
        self.assertNotRegex(ddl, r'\b(GRANT|INSERT|UPDATE|DELETE)\b')

    def test_create_and_reserve_match_their_gateway_declarations(self):
        declared = {x['name']: x for x in schema.inventory()['functions']}
        for name, ddl in (('create_set_v1', schema.CREATE_DDL), ('reserve_member_v1', schema.RESERVE_DDL)):
            with self.subTest(function=name):
                self.assertEqual((['text', 'uuid', 'bigint', 'jsonb', 'text', 'jsonb'], 'jsonb', 'identity_source_gateway'),
                    (declared[name]['arguments'], declared[name]['returns'], declared[name]['execute']))
                self.assertIn('REVOKE ALL ON FUNCTION wl_ingestion.' + name +
                              '(text,uuid,bigint,jsonb,text,jsonb) FROM PUBLIC;', ddl)
                self.assertEqual(1, ddl.count('CREATE FUNCTION'))
                for fragment in ('GRANT ', 'SESSION_RECHECK', 'SET_RESULT', 'UUID_RE', 'SET_BYTES', 'MEMBER_PINS',
                                 'INSTANT_', 'CONTROLS', 'DELETE '):
                    self.assertNotIn(fragment, ddl)
                # A session failure after a reservation must roll it back, so it raises.
                self.assertNotIn("RETURN pg_catalog.jsonb_build_object('ok',false,'code','session_changed')", ddl)
                self.assertIn("MESSAGE='session_changed'", ddl)

    def test_quota_and_purge_match_their_private_declarations(self):
        declared = {x['name']: x for x in schema.inventory()['functions']}
        for name, ddl, arguments in (
                ('_quota_v1', schema.QUOTA_DDL, 'uuid,uuid,text,bigint,bigint'),
                ('_purge_v1', schema.PURGE_DDL, 'uuid,uuid,uuid')):
            with self.subTest(function=name):
                self.assertEqual((arguments.split(','), 'void', 'operator_owner_only'), (
                    declared[name]['arguments'], declared[name]['returns'], declared[name]['execute']))
                self.assertIn('RETURNS void\nLANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp', ddl)
                self.assertIn('REVOKE ALL ON FUNCTION wl_ingestion.' + name + '(' + arguments + ') FROM PUBLIC;', ddl)
                self.assertEqual(1, ddl.count('CREATE FUNCTION'))
                for fragment in ('GRANT ', 'INVALID;', 'BUSY;', 'LIMIT;', 'READ_USER', 'SET_BYTES'):
                    self.assertNotIn(fragment, ddl)
        # Purge deletes only transient review rows, never accepted evidence or control history.
        self.assertEqual({'previews', 'decisions', 'stages'},
                         set(re.findall(r'DELETE FROM wl_ingestion\.(\w+)', schema.PURGE_DDL)))
        self.assertNotRegex(schema.QUOTA_DDL, r'DELETE|TRUNCATE')
        self.assertEqual({'read': {'rate': (60, 600)}, 'control': {'rate': (30, 300)},
                          'raw': {'rate': (10, 60), 'leases': (1, 4)},
                          'storage': {'sets': (8, 64), 'bytes': (134217728, 1073741824)}}, schema.QUOTA_LIMITS)

    def test_transition_and_head_guards_match_their_private_declarations(self):
        declared = {x['name']: x for x in schema.inventory()['functions']}
        for name, ddl in (('_transition_v1', schema.TRANSITION_DDL), ('_head_v1', schema.HEAD_DDL)):
            with self.subTest(function=name):
                self.assertEqual(([], 'trigger', 'operator_owner_only'), (declared[name]['arguments'],
                    declared[name]['returns'], declared[name]['execute']))
                self.assertIn('CREATE FUNCTION wl_ingestion.' + name + '() RETURNS trigger\n'
                    'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp', ddl)
                self.assertIn('REVOKE ALL ON FUNCTION wl_ingestion.' + name + '() FROM PUBLIC;', ddl)
                self.assertEqual(1, ddl.count('CREATE FUNCTION'))
                for fragment in ('GRANT ', 'CREATE TRIGGER', 'REJECT;', 'CONFLICT;', 'EXPIRED;'):
                    self.assertNotIn(fragment, ddl)
        declared_effects = declared['_effects_v1']
        effects = schema.effects_ddl()
        self.assertEqual((['uuid', 'uuid', 'uuid', 'uuid'], 'jsonb', 'operator_owner_only'),
            (declared_effects['arguments'], declared_effects['returns'], declared_effects['execute']))
        self.assertIn('CREATE FUNCTION wl_ingestion._effects_v1(p_tenant uuid,p_portfolio uuid,p_preview uuid,'
                      'p_receipt uuid)\nRETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp', effects)
        self.assertIn('REVOKE ALL ON FUNCTION wl_ingestion._effects_v1(uuid,uuid,uuid,uuid) FROM PUBLIC;', effects)
        self.assertEqual(1, effects.count('CREATE FUNCTION'))
        self.assertNotIn('GRANT ', effects)
        accept = declared['accept_preview_v1']
        self.assertEqual((['text', 'uuid', 'bigint', 'jsonb', 'text', 'jsonb'], 'jsonb'),
                         (accept['arguments'], accept['returns']))
        self.assertIn('accept_preview_v1', schema.GATEWAY)
        self.assertIn('REVOKE ALL ON FUNCTION wl_ingestion.accept_preview_v1(text,uuid,bigint,jsonb,text,jsonb) '
                      'FROM PUBLIC;', schema.ACCEPT_DDL)
        self.assertNotIn('GRANT ', schema.ACCEPT_DDL)
        # Acceptance inserts the same entity bodies that Plan validation hashed.
        self.assertIn(schema._ENTITY_BODY_SQL, schema.plan_validator_ddl())
        self.assertIn(schema._ENTITY_BODY_SQL, effects)
        guarded = {x['table'] for x in schema.inventory()['triggers'] if x['function'] == '_transition_v1'}
        self.assertEqual(guarded, set(re.search(r"TG_TABLE_NAME NOT IN\s*\(([^)]*)\)",
            schema.TRANSITION_DDL).group(1).replace("'", '').replace('\n', '').replace(' ', '').split(',')))


@unittest.skipUnless(os.environ.get('WEALTH_LEDGER_INGESTION_TEST') == '1',
                     'Opt-in isolated ingestion PostgreSQL fragment acceptance')
class IngestionAppendOnlyPostgresTests(unittest.TestCase):
    """Real SQL fragment checks; incomplete deferred-parent inserts roll back."""
    IMAGE = 'postgres@sha256:edb0c08dc33befd0262ab3b5cf1c4f3f8cfd8b09e88c05b45adee29d6761ddb6'

    @classmethod
    def command(cls, args, **kwargs):
        return subprocess.run(args, capture_output=True, timeout=kwargs.pop('timeout', 45), **kwargs)

    @classmethod
    def sql(cls, statement):
        result = cls.command(['docker', 'exec', '-i', cls.container, 'psql', '-X', '-A', '-t',
            '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1'], input=statement.encode())
        if result.returncode:
            raise AssertionError('Synthetic PostgreSQL fragment statement failed')
        return result.stdout.decode().strip()

    @classmethod
    def remove_owned_container(cls):
        listing = cls.command(['docker', 'container', 'ls', '-a', '--filter',
            'name=' + cls.container, '--format', '{{.Names}} {{.Label "wealth-ledger.test-owner"}}'])
        if listing.returncode:
            raise AssertionError('Owned synthetic PostgreSQL cleanup could not be verified')
        exact = [line.split() for line in listing.stdout.decode().splitlines()
                 if line.split() and line.split()[0] == cls.container]
        if not exact:
            return
        if exact != [[cls.container, cls.owner]]:
            raise AssertionError('Synthetic PostgreSQL ownership mismatch; container preserved')
        result = cls.command(['docker', 'rm', '-f', '-v', cls.container])
        if result.returncode:
            raise AssertionError('Owned synthetic PostgreSQL cleanup failed')

    @classmethod
    def setUpClass(cls):
        from kurafolio.persistence import schema as foundation, identity_schema, source_schema
        cls.directory = tempfile.TemporaryDirectory(prefix='wl007-append-only-')
        cls.addClassCleanup(cls.directory.cleanup)
        secret = Path(cls.directory.name) / 'bootstrap.txt'
        descriptor = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(secrets.token_urlsafe(32) + '\n')
        cls.owner = uuid.uuid4().hex
        cls.container = 'wl007-test-append-only-' + cls.owner[:12]
        cls.addClassCleanup(cls.remove_owned_container)
        result = cls.command(['docker', 'run', '-d', '--pull', 'never', '--name', cls.container,
            '--label', 'wealth-ledger.test=ingestion-append-only',
            '--label', 'wealth-ledger.test-owner=' + cls.owner, '--network', 'none',
            '--memory', '512m', '--cpus', '1', '--pids-limit', '128',
            '--tmpfs', '/var/lib/postgresql:rw,nosuid,nodev,size=512m',
            '--mount', 'type=bind,source=' + str(secret) + ',target=/run/secrets/bootstrap,readonly',
            '-e', 'POSTGRES_PASSWORD_FILE=/run/secrets/bootstrap', cls.IMAGE])
        if result.returncode:
            raise AssertionError('Exact cached PostgreSQL test image and Docker daemon required')
        deadline = time.monotonic() + 45
        while True:
            process = cls.command(['docker', 'exec', cls.container, 'cat', '/proc/1/comm'], timeout=5)
            ready = cls.command(['docker', 'exec', cls.container, 'pg_isready', '-U', 'postgres'], timeout=5)
            if process.stdout.strip() == b'postgres' and ready.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise AssertionError('Synthetic PostgreSQL startup deadline')
            time.sleep(.2)
        cls.sql('CREATE SCHEMA wl_pg;\n' + foundation.ddl()[0] + '\n' + identity_schema.ddl()
                + '\n' + source_schema.ddl() + '\n' + schema.tables_ddl() + '\n' + schema.IMMUTABLE_DDL
                + '\n' + schema.OUTBOX_GUARD_DDL + '\n' + schema.user_guard_ddl()
                + '\n' + schema.minimal_validator_ddl() + '\n' + schema.plan_validator_ddl() + '\n' + schema.reference_validator_ddl() + '\n' + schema.REPLAY_DDL
                + '\n' + schema.TRANSITION_DDL + '\n' + schema.HEAD_DDL + '\n' + schema.effects_ddl()
                + '\n' + schema.ACCEPT_DDL + '\n' + schema.QUOTA_DDL + '\n' + schema.PURGE_DDL
                + '\n' + schema.CANCEL_DDL + '\n' + schema.DECIDE_DDL
                + '\n' + schema.READ_SET_DDL + '\n' + schema.READ_RECEIPT_DDL
                + '\n' + schema.READ_SETS_DDL + '\n' + schema.READ_PREVIEW_DDL
                + '\n' + schema.worker_guard_ddl() + '\n' + schema.CREATE_DDL
                + '\n' + schema.RESERVE_DDL + '\n' + schema.CLAIM_DDL + '\n' + schema.RENEW_DDL
                + '\n' + schema.ADMIT_DDL + '\n' + schema.FINISH_DDL)
        cls.sql('CREATE TABLE wl_pg.alembic_version(version_num text PRIMARY KEY);')
        for trigger in schema.inventory()['triggers']:
            if trigger['function'] == '_immutable_v1':
                cls.sql('CREATE TRIGGER ' + trigger['name'] + ' BEFORE INSERT OR UPDATE OR DELETE ON '
                        'wl_ingestion.' + trigger['table'] + ' FOR EACH ROW EXECUTE FUNCTION '
                        'wl_ingestion._immutable_v1();')
        cls.sql('CREATE TRIGGER outbox_guard BEFORE INSERT OR UPDATE OR DELETE ON '
                'wl_ingestion.outbox FOR EACH ROW EXECUTE FUNCTION wl_ingestion._outbox_guard_v1();')

    def test_closed_minimal_shape_scalars_without_claiming_graph_admission(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import encode
        predicate = schema._minimal_shape_predicate()
        cases = []
        for name, value in ORACLE.items():
            if name.startswith('minimal-') or name.endswith('-minimal.json'):
                cases.append(('literal_' + name, value, True))
        for token, expected in (('9' * 38, True), ('9' * 39, False), ('-0.00000000', True),
                ('0.' + '0' * 23 + '1', True), ('0.' + '0' * 24 + '1', False), ('1e2', False)):
            value = deepcopy(ORACLE['minimal-native.json'])
            value['records'][0]['legs'][0]['quantity'] = token
            cases.append(('decimal_' + str(len(cases)), value, expected))
        for token, fraction, expected in (
                ('2024-02-29T12:00:00+00:00', 0, True),
                ('2026-02-29T12:00:00+00:00', 0, False),
                ('2026-01-01T23:59:59.000001+23:59', 6, True),
                ('2026-01-01T23:59:59.000001+23:60', 6, False),
                ('2026-01-01T12:00:00-00:00', 0, False),
                ('2026-01-01T12:00:00.100000+00:00', 0, False)):
            value = deepcopy(ORACLE['minimal-native.json'])
            value['provenance']['evidence_at'].update(token=token, fractional_digits=fraction)
            cases.append(('clock_' + str(len(cases)), value, expected))
        for label, support in (
                ('supported_with_reason', {'classification': 'supported_shape', 'reasons': ['unsupported_activity']}),
                ('unsupported_empty', {'classification': 'unsupported', 'reasons': []}),
                ('duplicate_reason', {'classification': 'unsupported', 'reasons': ['unsupported_activity', 'unsupported_activity']})):
            value = deepcopy(ORACLE['minimal-native.json'])
            value['records'][0]['support'] = support
            cases.append((label, value, False))
        for codepoint in (*range(1, 32), *range(127, 160)):
            value = deepcopy(ORACLE['minimal-native.json'])
            value['accounts'][0]['label'] = 'synthetic' + chr(codepoint)
            cases.append(('control_codepoint_' + str(codepoint), value, codepoint >= 32))
        for spelling in ('1.0', '1.00'):
            raw = encode(ORACLE['minimal-native.json'])
            altered = raw.replace(b'"version":1', ('"version":' + spelling).encode(), 1)
            self.assertNotEqual(raw, altered)
            cases.append(('integer_enum_' + spelling, altered, False))
        raw = encode(ORACLE['minimal-parser2.json'])
        altered = raw.replace(b'"parser_api":2', b'"parser_api":2.0', 1)
        self.assertNotEqual(raw, altered)
        cases.append(('nullable_integer_enum_with_scale', altered, False))
        value = deepcopy(ORACLE['minimal-native.json'])
        value['accounts'][0]['unrecognized_field'] = 'rejected'
        cases.append(('unknown_field', value, False))
        value = deepcopy(ORACLE['minimal-native.json'])
        del value['records'][0]['fees']
        cases.append(('missing_required_null', value, False))
        value = deepcopy(ORACLE['minimal-native.json'])
        value['assets'][0]['source_descriptor'] = "opaque \\' quote'); DROP SCHEMA wl_ingestion; --"
        cases.append(('descriptor_stays_data', value, True))
        # These deliberately pass shape/scalars. A future checked entry point
        # must add graph and satoshi semantics before any stage is admitted.
        value = deepcopy(ORACLE['minimal-native.json'])
        value['accounts'][0]['local_id'] = '5'
        cases.append(('graph_not_implemented_by_predicate', value, True))
        value = deepcopy(ORACLE['minimal-native.json'])
        value['records'][0]['legs'][1]['quantity'] = '0.010000001'
        cases.append(('whole_satoshi_not_implemented_by_predicate', value, True))
        statements = ['BEGIN; CREATE SCHEMA wl007_shape_probe;',
            'CREATE FUNCTION wl007_shape_probe.check_minimal(payload jsonb) RETURNS boolean '
            'LANGUAGE sql AS $predicate$ SELECT ' + predicate + '; $predicate$;',
            'SET LOCAL standard_conforming_strings=off;']
        for number, (label, value, expected) in enumerate(cases):
            raw = value if type(value) is bytes else encode(value)
            call = "wl007_shape_probe.check_minimal(pg_catalog.convert_from(decode('" + raw.hex() + "','hex'),'UTF8')::jsonb)"
            statements.append('DO $check$ BEGIN IF ' + call + ' IS DISTINCT FROM ' +
                ('true' if expected else 'false') + " THEN RAISE EXCEPTION 'scalar_case_" + str(number) +
                "'; END IF; END $check$;")
        statements.append('ROLLBACK;')
        self.sql('\n'.join(statements))
        self.assertEqual('0', self.sql("SELECT count(*) FROM pg_catalog.pg_namespace WHERE nspname='wl007_shape_probe'"))

    def _assert_minimal_cases(self, cases):
        statements = ['BEGIN;']
        for index, (raw, code) in enumerate(cases):
            argument = 'NULL' if raw is None else "decode('" + raw.hex() + "','hex')"
            call = 'wl_ingestion._validate_minimal_v1(' + argument + ')'
            if code is None:
                statements.append("DO $case$ BEGIN IF wl_ingestion._canonical_v1(" + call + ')<>' +
                    argument + " THEN RAISE EXCEPTION 'minimal_roundtrip_" + str(index) +
                    "'; END IF; END $case$;")
            else:
                self.assertIn(code, {'import_invalid', 'import_limit', 'import_conflict',
                                     'import_evidence_unsupported'})
                statements.append('DO $case$ BEGIN BEGIN PERFORM ' + call +
                    "; RAISE EXCEPTION 'minimal_missing_rejection_" + str(index) +
                    "'; EXCEPTION WHEN SQLSTATE '22023' THEN IF SQLERRM<>'" + code +
                    "' THEN RAISE; END IF; END; END $case$;")
        statements.append('ROLLBACK;')
        self.sql('\n'.join(statements))

    def test_minimal_entry_preserves_literals_and_has_no_public_execution(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import encode
        cases = [(encode(value), None) for name, value in ORACLE.items()
                 if name.startswith('minimal-') or name.endswith('-minimal.json')]
        value = deepcopy(ORACLE['minimal-native.json'])
        value['accounts'][0]['label'] = 'Allowed C1\x85 and DEL\x7f'
        value['assets'][0]['source_descriptor'] = 'Text with [braces] {and} "quotes" \\slashes'
        cases.append((encode(value), None))
        self._assert_minimal_cases(cases)
        self.assertEqual('0', self.sql("SELECT count(*) FROM pg_catalog.pg_proc p "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(p.proacl,"
            "pg_catalog.acldefault('f',p.proowner))) a "
            "WHERE p.oid='wl_ingestion._validate_minimal_v1(bytea)'::regprocedure "
            "AND a.grantee=0 AND a.privilege_type='EXECUTE'"))
        self.assertEqual('t', self.sql("SELECT prosecdef AND proconfig @> "
            "ARRAY['search_path=pg_catalog, pg_temp'] FROM pg_catalog.pg_proc "
            "WHERE oid='wl_ingestion._validate_minimal_v1(bytea)'::regprocedure"))

    def test_minimal_entry_canonical_bytes_and_resource_errors(self):
        from kurafolio.ingestion.codec import encode
        valid = encode(ORACLE['minimal-native.json'])
        cases = [(None, 'import_limit'), (b'', 'import_limit'),
            (b'x' * (4194304 + 1), 'import_limit'),
            (b'[' * 33 + b']' * 33, 'import_limit'),
            (b'[' + b'null,' * 131072 + b'null]', 'import_limit')]
        for raw in (b'\xff', b'NaN', b'null', b'{}', valid + b'\n', b' ' + valid,
                valid.replace(b'"version":1', b'"version":1.0', 1),
                valid.replace(b'"version":1', b'"version":1e0', 1),
                valid.replace(b'"version":1', b'"version":1,"version":1', 1),
                valid.replace(b'"version":1', b'"version":true', 1),
                b'{"SECRET_SENTINEL":"\\u0000"}'):
            cases.append((raw, 'import_invalid'))
        self._assert_minimal_cases(cases)

    def test_minimal_entry_graph_satoshi_cash_and_unknown_evidence(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import encode
        cases = []
        for field in ('account_local_id', 'asset_local_id', 'quantity'):
            value = deepcopy(ORACLE['minimal-native.json'])
            value['records'][0]['legs'][1][field] = '0.010000001' if field == 'quantity' else '99999'
            cases.append((encode(value), 'import_invalid'))
        value = deepcopy(ORACLE['minimal-parser2.json'])
        value['records'][0]['legs'][0]['role'] = 'OTHER'
        cases.append((encode(value), 'import_evidence_unsupported'))
        value = deepcopy(ORACLE['metadata-native-minimal.json'])
        value['records'][0]['lifecycle'] = None
        cases.append((encode(value), 'import_evidence_unsupported'))
        value = deepcopy(ORACLE['minimal-native.json'])
        value['coverage'][0]['time'] = {'tag': 'interval',
            'start': {'tag': 'legacy_unspecified', 'token': 'unknown start', 'zone': None, 'legacy': None},
            'end': {'tag': 'legacy_unspecified', 'token': 'unknown end', 'zone': None, 'legacy': None},
            'start_inclusive': True, 'end_inclusive': True}
        cases.append((encode(value), 'import_conflict'))
        for token in ('-1.00', '0', '100.00'):
            value = deepcopy(ORACLE['minimal-native.json'])
            value['records'][0].update(kind='FUNDING', source_kind='cash_flows', source_type='deposit',
                legs=[], lifecycle=None, acquisition_cost=None, acquisition_cost_cad=None,
                cash_flow={'cash_amount': {'amount': token, 'currency': 'CAD'}, 'direction': 'in',
                    'boundary': 'unclassified', 'transfer_reference': None, 'counterpart': None, 'cash_leg_of': None})
            value['coverage'][0]['kind'] = 'cash_flows'
            self.assertEqual('unclassified', value['records'][0]['cash_flow']['boundary'])
            cases.append((encode(value), None if token == '100.00' else 'import_invalid'))
        value = deepcopy(ORACLE['snapshot-t2-empty-complete-minimal.json'])
        at = deepcopy(value['snapshots'][0]['as_of'])
        at['token'] = '2026-02-02T12:00:00+00:00'
        value['coverage'][0]['time'] = {'tag': 'point', 'at': at}
        cases.append((encode(value), 'import_invalid'))
        value = deepcopy(ORACLE['snapshot-t1-minimal.json'])
        at = {'tag': 'date_only', 'token': '2026-01-01', 'zone': None}
        value['snapshots'][0]['as_of'] = deepcopy(at)
        value['coverage'][0]['time'] = {'tag': 'point', 'at': deepcopy(at)}
        for row in value['records']:
            row['as_of'] = deepcopy(at)
        cases.append((encode(value), None))
        self._assert_minimal_cases(cases)

    def test_minimal_entry_legacy_offset_seconds_and_canonical_boundaries(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import encode
        cases = []
        # Each canonical legacy token below denotes the literal trade instant
        # 2026-01-01T12:00:00+00:00, including positive/negative subminute offsets.
        for token in ('2026-01-01T12:00:01+00:00:01',
                '2026-01-01T11:59:59-00:00:01',
                '2026-01-01T12:00:01.000001+00:00:01.000001',
                '2026-01-01T11:59:58.999999-00:00:01.000001',
                '2026-01-01T13:00:00.000001+01:00:00.000001',
                '2026-01-02T11:59:59.999999+23:59:59.999999'):
            value = deepcopy(ORACLE['minimal-native.json'])
            value['records'][0]['event_time'] = {'tag': 'legacy_unspecified', 'token': token,
                'zone': None, 'legacy': None}
            cases.append((encode(value), None))
        for token in ('2026-01-01T12:00:00+00:00:00',
                '2026-01-01T12:00:00+00:00:00.000001',
                '2026-01-01T13:00:00+01:00:00',
                '2026-01-01T13:02:03+01:02:03.000000'):
            value = deepcopy(ORACLE['minimal-native.json'])
            value['records'][0]['event_time'] = {'tag': 'legacy_unspecified', 'token': token,
                'zone': None, 'legacy': None}
            cases.append((encode(value), 'import_invalid'))
        # The sealed Fee schema requires an account reference. The Python
        # graph's optional branch does not widen that closed type declaration.
        for account, expected in ((None, 'import_invalid'), ('1', None)):
            value = deepcopy(ORACLE['minimal-native.json'])
            value['records'][0]['fees'] = [{'account_local_id': account, 'asset_local_id': '1',
                'quantity': '0.00000001', 'included_in_leg': False, 'included_in_cost': False}]
            cases.append((encode(value), expected))
        self._assert_minimal_cases(cases)

    def test_minimal_entry_shape_error_classes(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import encode
        cases = []
        value = deepcopy(ORACLE['minimal-native.json'])
        value['accounts'][0]['label'] = 'x' * 161
        cases.append((encode(value), 'import_limit'))
        value = deepcopy(ORACLE['snapshot-t1-minimal.json'])
        value['records'][0]['name'] = 'x' * 161
        cases.append((encode(value), 'import_invalid'))
        value = deepcopy(ORACLE['minimal-native.json'])
        value['accounts'] *= 65
        cases.append((encode(value), 'import_limit'))
        value = deepcopy(ORACLE['minimal-native.json'])
        value['records'][0]['support'] = {'classification': 'unsupported', 'reasons': []}
        cases.append((encode(value), 'import_invalid'))
        self._assert_minimal_cases(cases)

    @staticmethod
    def _plan_seed(plan, *, decisions=None, stages=None):
        """Construct a rolled-back stored basis from fixed synthetic vectors."""
        from kurafolio.ingestion.codec import encode, sha256
        def literal(value):
            if value is None:
                return 'NULL'
            if type(value) is bytes:
                return "decode('" + value.hex() + "','hex')"
            return "'" + str(value).replace("'", "''") + "'"
        def insert(table, values):
            return 'INSERT INTO wl_ingestion.' + table + '(' + ','.join(values) + ') VALUES(' + ','.join(literal(x) for x in values.values()) + ');'
        scope = {'tenant_id': plan['tenant_id'], 'portfolio_id': plan['portfolio_id']}
        statements = [insert('roots', {**scope, **{k: plan['expected_' + k] for k in (
            'accepted_generation', 'mapping_generation', 'control_generation')}})]
        # Fixtures use exact instants. These tests deliberately do not claim
        # live authorization/expiry or a committable initialized database.
        import datetime
        expires = datetime.datetime.fromisoformat(plan['expires_at']['token'])
        created = (expires - datetime.timedelta(days=1)).isoformat()
        statements.append(insert('sets', {**scope, 'id': plan['set_id'],
            'actor_user_id': plan['tenant_id'], 'creation_operation_id': str(uuid.uuid4()),
            'request_digest': '1' * 64, **{k: plan[k] for k in ('incarnation', 'restore_epoch', 'realm_digest')},
            'state': 'READY', 'revision': plan['expected_set_revision'], 'created_at': created,
            'expires_at': expires.isoformat(), 'member_count': len(plan['inputs']),
            'reserved_bytes': 16777216, 'receipt_id': None, 'cleanup_state': 'not_needed'}))
        if decisions is None:
            decisions = next(v for v in ORACLE.values() if type(v) is dict
                and 'operation_id' in v and 'mappings' in v and sha256(encode(v)) == plan['decision_digest'])
        statements.append(insert('decisions', {**scope, 'set_id': plan['set_id'],
            'revision': int(plan['expected_set_revision']) - 1,
            'request_digest': sha256(encode(decisions)), 'canonical_bytes': encode(decisions),
            'digest': sha256(encode(decisions)), 'created_at': created, 'purge_at': expires.isoformat()}))
        for ordinal, input_ in enumerate(plan['inputs']):
            minimal = (stages or {}).get(input_['stage_digest'])
            if minimal is None:
                minimal = next(v for v in ORACLE.values() if type(v) is dict
                    and 'provenance' in v and 'accounts' in v and sha256(encode(v)) == input_['stage_digest'])
            pin = next(x for x in plan['pinned_sources'] if x['member_id'] == input_['member_id'])
            statements.append(insert('members', {**scope, 'set_id': plan['set_id'],
                'id': input_['member_id'], 'ordinal': ordinal, **{k: v for k, v in pin.items()
                    if k != 'member_id'}, 'context_bytes': None, 'raw_digest': input_['raw_digest'],
                'raw_bytes': 1, 'state': 'admitted', 'error_code': None, 'stage_digest': input_['stage_digest'],
                'fence': 1, 'raw_deadline': None}))
            statements.append(insert('stages', {**scope, 'set_id': plan['set_id'],
                'member_id': input_['member_id'], 'digest': input_['stage_digest'],
                'codec': 'minimal-evidence-v1', 'minimal_bytes': encode(minimal),
                'created_at': created, 'purge_at': expires.isoformat()}))
        def bodies(value):
            if type(value) is dict:
                if type(value.get('id')) is dict and 'kind' in value['id'] and 'value' in value['id']:
                    yield value
                for child in value.values():
                    yield from bodies(child)
            elif type(value) is list:
                for child in value:
                    yield from bodies(child)
        stored_bodies = list(bodies(ORACLE))
        inserted = set()
        for mapping in plan['mappings']:
            target, kind = mapping['target'], mapping['entity_kind']
            if target['mode'] != 'existing' or (kind, target['id'], target['version']) in inserted:
                continue
            inserted.add((kind, target['id'], target['version']))
            body = next(b for b in stored_bodies if b['id']['value'] == target['id']
                and sha256(encode(b)) == target['version'])
            table = {'account': 'accounts', 'instrument': 'instruments', 'issuer': 'issuers'}[kind]
            fields = ('category', 'role', 'label') if kind == 'account' else ('label',) if kind == 'issuer' else (
                'kind', 'currency', 'ticker', 'mic', 'symbol', 'network', 'settlement_identity', 'identifiers')
            values = {**scope, 'id': target['id'], 'version': target['version'],
                'body': encode(body).decode(), **{k: encode(body[k]).decode() if k == 'identifiers' else body[k] for k in fields}}
            if kind == 'instrument':
                issuer = body['issuer']
                values.update(issuer_id=None if issuer is None else issuer['value'],
                    issuer_version=None if issuer is None else next(m['target']['version'] for m in plan['mappings']
                        if m['entity_kind'] == 'issuer' and m['target']['id'] == issuer['value']))
            statement = insert(table, values).replace('INSERT INTO wl_ingestion.', 'INSERT INTO wl_pg.', 1)
            statements.append(statement)
        return '\n'.join(statements)

    def _assert_plan(self, plan, *, raw=None, code=None, mutate_basis=''):
        from kurafolio.ingestion.codec import encode
        raw = encode(plan) if raw is None else raw
        argument = "decode('" + raw.hex() + "','hex')"
        call = "wl_ingestion._validate_plan_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] + "','" + plan['set_id'] + "'," + argument + ')'
        if code is None:
            check = 'IF wl_ingestion._canonical_v1(' + call + ')<>' + argument + " THEN RAISE EXCEPTION 'plan_roundtrip'; END IF;"
        else:
            check = 'BEGIN PERFORM ' + call + "; RAISE EXCEPTION 'plan_missing_rejection'; EXCEPTION WHEN SQLSTATE '22023' THEN IF SQLERRM<>'" + code + "' THEN RAISE; END IF; END;"
        self.sql('BEGIN;\n' + self._plan_seed(plan) + '\n' + mutate_basis + '\nDO $check$ BEGIN ' + check + ' END $check$;ROLLBACK;')

    def test_plan_entry_literal_proposed_entities_and_financial_projections(self):
        for name, plan in ORACLE.items():
            if not (name.startswith('plan-') or name.endswith('-plan.json')):
                continue
            with self.subTest(vector=name):
                self._assert_plan(plan)
        self.assertEqual('0', self.sql("SELECT count(*) FROM pg_catalog.pg_proc p "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(p.proacl,"
            "pg_catalog.acldefault('f',p.proowner))) a WHERE "
            "p.oid='wl_ingestion._validate_plan_v1(uuid,uuid,uuid,bytea)'::regprocedure "
            "AND a.grantee=0 AND a.privilege_type='EXECUTE'"))

    def test_plan_entry_rehashed_tampering_cannot_replace_stored_basis(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import encode
        original = ORACLE['plan-native-first-use.json']
        mutations = []
        plan = deepcopy(original)
        plan['facts'][0]['financial_digest'] = '1' * 64
        mutations.append((plan, 'import_conflict'))
        plan = deepcopy(original)
        plan['facts'] = plan['facts'][:-1]
        mutations.append((plan, 'import_invalid'))
        plan = deepcopy(original)
        plan['facts'][1] = deepcopy(plan['facts'][0])
        mutations.append((plan, 'import_invalid'))
        plan = deepcopy(original)
        plan['inputs'][0]['discovery_digest'] = '1' * 64
        mutations.append((plan, 'import_stale'))
        plan = deepcopy(original)
        plan['pinned_sources'][0]['connection_generation'] = '2'
        mutations.append((plan, 'import_stale'))
        plan = deepcopy(original)
        plan['mappings'][0]['target']['id'] = '10000000-0000-4000-8000-000000000099'
        mutations.append((plan, 'import_conflict'))
        plan = deepcopy(original)
        plan['expected_mapping_generation'] = '1'
        mutations.append((plan, 'import_stale'))
        for plan, code in mutations:
            # Seed original trusted bytes; only the submitted Plan is changed.
            with self.subTest(case=len(encode(plan)), code=code):
                self._assert_plan(original, raw=encode(plan), code=code)
        self._assert_plan(original, code='import_stale', mutate_basis='DELETE FROM wl_ingestion.stages;')

    def test_plan_entry_raw_bounds_and_canonical_rejections(self):
        from kurafolio.ingestion.codec import encode
        plan = ORACLE['plan-native-first-use.json']
        raw = encode(plan)
        for altered, code in ((raw + b'\n', 'import_invalid'),
                (raw.replace(b'"version":1', b'"version":1e0', 1), 'import_invalid'),
                (b'[' * 33 + b']' * 33, 'import_limit'),
                (b'[' + b'null,' * 131072 + b'null]', 'import_limit'),
                (b'x' * (16777216 + 1), 'import_limit'),
                (b'{"private_marker":"\\u0000"}', 'import_invalid')):
            with self.subTest(code=code, size=len(altered)):
                self._assert_plan(plan, raw=altered, code=code)

    @staticmethod
    def _preview_seed(plan):
        from kurafolio.ingestion.codec import encode, digest
        # The reference helper consumes the stored Plan. Review disclosure is a
        # separate prepare-preview responsibility, not granted by these markers.
        values = {'tenant_id': plan['tenant_id'], 'portfolio_id': plan['portfolio_id'],
            'id': plan['preview_id'], 'set_id': plan['set_id'], 'set_revision': plan['expected_set_revision'],
            'decision_revision': str(int(plan['expected_set_revision']) - 1),
            'plan_bytes': encode(plan), 'plan_digest': digest(plan),
            **{k: plan[k] for k in ('expected_accepted_generation', 'expected_mapping_generation',
                'expected_control_generation', 'incarnation', 'restore_epoch', 'realm_digest')},
            'expires_at': plan['expires_at']['token'], 'created_at': '2026-02-02T13:00:00+00:00',
            'purge_at': plan['expires_at']['token'], 'review_bytes': encode({}), 'review_digest': digest({})}
        def literal(v):
            return "decode('" + v.hex() + "','hex')" if type(v) is bytes else "'" + str(v).replace("'", "''") + "'"
        return 'INSERT INTO wl_ingestion.previews(' + ','.join(values) + ') VALUES(' + ','.join(literal(v) for v in values.values()) + ');'

    def test_plan_reference_entry_first_use_and_current_head_cas(self):
        for name in ('plan-first-use.json', 'plan-native-first-use.json', 'snapshot-seed-t2-plan.json'):
            plan = ORACLE[name]
            call = "wl_ingestion._references_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] + "','" + plan['preview_id'] + "')"
            with self.subTest(vector=name):
                self.sql('BEGIN;' + self._plan_seed(plan) + self._preview_seed(plan) + 'SELECT ' + call + ';ROLLBACK;')
        self.assertEqual('0', self.sql("SELECT count(*) FROM pg_catalog.pg_proc p "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(p.proacl,"
            "pg_catalog.acldefault('f',p.proowner))) a WHERE "
            "p.oid='wl_ingestion._references_v1(uuid,uuid,uuid)'::regprocedure "
            "AND a.grantee=0 AND a.privilege_type='EXECUTE'"))

    @staticmethod
    def _accepted_basis_seed(plan_name):
        """Retain immutable first-use vectors; this is not an acceptance engine."""
        from kurafolio.ingestion.codec import encode, digest
        from kurafolio.ingestion.reconciliation import source_revision_key, financial_projection
        from kurafolio.ingestion.mapping import MappingIndex
        plan = ORACLE[plan_name]
        input_ = plan['inputs'][0]
        minimal = next(v for v in ORACLE.values() if type(v) is dict and 'provenance' in v
            and 'accounts' in v and digest(v) == input_['stage_digest'])
        input_id, plan_id = 'f0000000-0000-4000-8000-000000000001', 'f0000000-0000-4000-8000-000000000002'
        def literal(v):
            if v is None:
                return 'NULL'
            return "decode('" + v.hex() + "','hex')" if type(v) is bytes else "'" + str(v).replace("'", "''") + "'"
        def insert(table, values):
            return 'INSERT INTO wl_ingestion.' + table + '(' + ','.join(values) + ') VALUES(' + ','.join(literal(v) for v in values.values()) + ');'
        scope = {'tenant_id': plan['tenant_id'], 'portfolio_id': plan['portfolio_id']}
        statements = [insert('accepted_inputs', {**scope, 'id': input_id, 'codec': 'minimal-evidence-v1',
            'canonical_bytes': encode(minimal), 'digest': input_['stage_digest'], 'raw_digest': input_['raw_digest'],
            'discovery_digest': input_['discovery_digest'], 'installation_id': plan['pinned_sources'][0]['installation_id'],
            'created_at': '2026-02-02T13:00:00+00:00'}),
            insert('accepted_plans', {**scope, 'id': plan_id, 'preview_id': plan['preview_id'],
            'codec': 'acceptance-plan-v1', 'canonical_bytes': encode(plan), 'digest': digest(plan),
            'receipt_id': 'f0000000-0000-4000-8000-000000000003', 'created_at': '2026-02-02T13:00:00+00:00'})]
        index = MappingIndex(plan['mappings'], input_['member_id'])
        for fact in plan['facts']:
            collection, local = fact['collection'], fact['local_id']
            typed = minimal['membership'] if collection == 'membership' else minimal[collection][int(local)]
            key = source_revision_key(minimal, collection, local, **scope,
                connection_id=plan['pinned_sources'][0]['connection_id'])
            material = financial_projection(minimal, collection, local, index, scope={**scope,
                'connection_id': plan['pinned_sources'][0]['connection_id']})
            if digest(material) != fact['financial_digest']:
                raise AssertionError('Fixed material vector mismatch before storage test')
            statements.append(insert('source_revisions', {**scope, 'id': fact['accepted_revision_id'],
                'source_key': digest(key['source']), 'source_revision': key['revision'],
                'financial_digest': fact['financial_digest'], 'source_change': 'original', 'accepted_change': 'original',
                'parent_id': None, 'input_id': input_id, 'collection': collection, 'local_id': local,
                'typed_bytes': encode(typed), 'typed_digest': digest(typed), 'created_at': '2026-02-02T13:00:00+00:00'}))
            statements.append(insert('lineage', {**scope, 'source_revision_id': fact['accepted_revision_id'],
                'input_id': input_id, 'collection': collection, 'local_id': local, 'source_claim_bytes': encode(key),
                'raw_digest': input_['raw_digest'], 'installation_id': plan['pinned_sources'][0]['installation_id'],
                'evidence_digest': digest(typed)}))
            if fact['economic_group_id'] is not None:
                statements.append(insert('activity_heads', {**scope, 'economic_group_id': fact['economic_group_id'],
                    'revision_id': fact['accepted_revision_id'], 'active': 'true'}))
        return '\n'.join(statements)

    def test_plan_reference_entry_checks_retained_duplicate_and_correction_bytes(self):
        for name in ('branch-fresh_duplicate_only-plan.json', 'branch-new_equal_meaning_revision-plan.json',
                     'branch-equal_value_explicit_correction-plan.json', 'branch-mapping_only_existing_issuer-plan.json'):
            plan = ORACLE[name]
            baseline = 'plan-native-first-use.json' if 'existing_issuer' in name else 'plan-first-use.json'
            call = "wl_ingestion._references_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] + "','" + plan['preview_id'] + "')"
            seed = self._plan_seed(plan) + self._accepted_basis_seed(baseline) + self._preview_seed(plan)
            with self.subTest(vector=name):
                self.sql('BEGIN;' + seed + 'SELECT ' + call + ';ROLLBACK;')
            # An incomplete/foreign accepted basis cannot establish authority.
            check = 'DO $check$ BEGIN BEGIN PERFORM ' + call + "; RAISE EXCEPTION 'reference_missing_rejection'; EXCEPTION WHEN SQLSTATE '22023' THEN IF SQLERRM<>'import_conflict' THEN RAISE; END IF; END; END $check$;"
            with self.subTest(vector=name, missing_basis=True):
                self.sql('BEGIN;' + self._plan_seed(plan) + self._preview_seed(plan) + check + 'ROLLBACK;')

    def test_plan_reference_entry_rejects_rebound_ids_omitted_heads_and_wrong_scope(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import digest
        baseline = ORACLE['branch-fresh_duplicate_only-plan.json']
        cases = []
        plan = deepcopy(baseline)
        plan['facts'][0]['accepted_revision_id'] = '60000000-0000-4000-8000-000000000099'
        cases.append(('absent_duplicate', plan, 'plan-first-use.json', ''))
        plan = deepcopy(baseline)
        plan['facts'][0]['accepted_revision_id'] = plan['facts'][1]['accepted_revision_id']
        cases.append(('wrong_collection', plan, 'plan-first-use.json', ''))
        plan = deepcopy(ORACLE['branch-equal_value_explicit_correction-plan.json'])
        plan['heads'] = []
        cases.append(('missing_leaf_head', plan, 'plan-first-use.json', ''))
        plan = deepcopy(ORACLE['branch-equal_value_explicit_correction-plan.json'])
        plan['heads'][0]['prior_revision_id'] = None
        cases.append(('stale_head', plan, 'plan-first-use.json', ''))
        plan = deepcopy(ORACLE['plan-native-first-use.json'])
        plan['heads'] = []
        cases.append(('missing_initial_head', plan, None, ''))
        for label, plan, original, mutation in cases:
            decisions = {'version': 1, 'operation_id': '10000000-0000-4000-8000-000000000099',
                'expected_set_revision': '1', **{k: plan[k] for k in ('mappings', 'new_entities', 'authorities', 'parents')}}
            plan['decision_digest'] = digest(decisions)
            seed = self._plan_seed(plan, decisions=decisions) + self._preview_seed(plan)
            if original:
                seed += self._accepted_basis_seed(original)
            call = "wl_ingestion._references_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] + "','" + plan['preview_id'] + "')"
            code = 'import_stale' if label == 'stale_head' else 'import_conflict'
            check = 'DO $check$ BEGIN BEGIN PERFORM ' + call + "; RAISE EXCEPTION 'reference_missing_rejection'; EXCEPTION WHEN SQLSTATE '22023' THEN IF SQLERRM<>'" + code + "' THEN RAISE; END IF; END; END $check$;"
            with self.subTest(case=label):
                self.sql('BEGIN;' + seed + mutation + check + 'ROLLBACK;')
        plan = ORACLE['plan-native-first-use.json']
        call = "wl_ingestion._references_v1('10000000-0000-4000-8000-000000000099','" + plan['portfolio_id'] + "','" + plan['preview_id'] + "')"
        self.sql('BEGIN;' + self._plan_seed(plan) + self._preview_seed(plan) +
            'DO $check$ BEGIN BEGIN PERFORM ' + call + "; RAISE EXCEPTION 'foreign_preview'; EXCEPTION WHEN SQLSTATE '22023' THEN IF SQLERRM<>'import_stale' THEN RAISE; END IF; END; END $check$;ROLLBACK;")

    def test_plan_entry_preparation_revision_is_checked_without_writing_state(self):
        plan = ORACLE['plan-native-first-use.json']
        self._assert_plan(plan, mutate_basis="UPDATE wl_ingestion.sets SET state='RECONCILING',revision=revision-1;")
        for mutation in ("UPDATE wl_ingestion.sets SET state='RECONCILING';",
                "UPDATE wl_ingestion.sets SET state='CANCELLED';",
                "UPDATE wl_ingestion.members SET state='reupload_required';"):
            with self.subTest(mutation=mutation):
                self._assert_plan(plan, code='import_stale', mutate_basis=mutation)

    def test_plan_reference_entry_same_set_duplicate_uses_the_pinned_new_revision(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import digest
        plan = deepcopy(ORACLE['plan-native-first-use.json'])
        second = '20000000-0000-4000-8000-000000000099'
        for name in ('inputs', 'pinned_sources', 'mappings', 'facts'):
            extra = deepcopy(plan[name])
            for row in extra:
                row['member_id'] = second
                if name == 'facts':
                    row['action'] = 'duplicate'
            plan[name].extend(extra)
        decisions = {'version': 1, 'operation_id': '10000000-0000-4000-8000-000000000099',
            'expected_set_revision': '1', **{k: plan[k] for k in ('mappings', 'new_entities', 'authorities', 'parents')}}
        plan['decision_digest'] = digest(decisions)
        call = "wl_ingestion._references_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] + "','" + plan['preview_id'] + "')"
        self.sql('BEGIN;' + self._plan_seed(plan, decisions=decisions) + self._preview_seed(plan) + 'SELECT ' + call + ';ROLLBACK;')

    def test_plan_reference_entry_mirror_cycles_and_latest_link_choice(self):
        plan = ORACLE['plan-native-first-use.json']
        call = "wl_ingestion._references_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] + "','" + plan['preview_id'] + "')"
        def edge(index, left, right, *, revision=1, kind='mirror', tenant=None):
            return "INSERT INTO wl_ingestion.authority_links VALUES('" + (tenant or plan['tenant_id']) + "','" + plan['portfolio_id'] + "','90000000-0000-4000-8000-" + str(index).zfill(12) + "'," + str(revision) + ",'60000000-0000-4000-8000-" + str(left).zfill(12) + "','60000000-0000-4000-8000-" + str(right).zfill(12) + "','" + kind + "','synthetic-mirror-proof','" + '1' * 64 + "','f0000000-0000-4000-8000-000000000002');"
        chain = edge(1, 1, 2) + edge(2, 2, 3)
        # These intentionally incomplete deferred parent rows isolate graph
        # validation. No committable acceptance or upgrade is established.
        for label, rows, code in (
                ('acyclic', chain, None),
                ('cycle', chain + edge(3, 3, 1), 'import_conflict'),
                ('latest_independent', chain + edge(3, 3, 1) + edge(3, 3, 1, revision=2, kind='independent'), None),
                ('foreign_cycle', edge(1, 1, 2, tenant='10000000-0000-4000-8000-000000000099') +
                    edge(2, 2, 1, tenant='10000000-0000-4000-8000-000000000099'), None)):
            check = 'SELECT ' + call + ';' if code is None else (
                'DO $check$ BEGIN BEGIN PERFORM ' + call + "; RAISE EXCEPTION 'mirror_cycle_missing_rejection'; EXCEPTION WHEN SQLSTATE '22023' THEN IF SQLERRM<>'" + code + "' THEN RAISE; END IF; END; END $check$;")
            with self.subTest(case=label):
                self.sql('BEGIN;' + self._plan_seed(plan) + self._preview_seed(plan) + rows + check + 'ROLLBACK;')

    def _reference_case(self, plan, *, baseline=None, code=None, stages=None):
        from copy import deepcopy
        from kurafolio.ingestion.codec import digest
        plan = deepcopy(plan)
        decisions = {'version': 1, 'operation_id': '10000000-0000-4000-8000-000000000099',
            'expected_set_revision': '1', **{k: plan[k] for k in ('mappings', 'new_entities', 'authorities', 'parents')}}
        plan['decision_digest'] = digest(decisions)
        seed = self._plan_seed(plan, decisions=decisions, stages=stages) + self._preview_seed(plan)
        if baseline:
            seed += self._accepted_basis_seed(baseline)
        call = "wl_ingestion._references_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] + "','" + plan['preview_id'] + "')"
        check = 'SELECT ' + call + ';' if code is None else (
            'DO $check$ BEGIN BEGIN PERFORM ' + call + "; RAISE EXCEPTION 'reference_expected_rejection'; EXCEPTION WHEN SQLSTATE '22023' THEN IF SQLERRM<>'" + code + "' THEN RAISE; END IF; END; END $check$;")
        self.sql('BEGIN;' + seed + check + 'ROLLBACK;')

    def test_plan_reference_entry_group_binding_and_void_need_source_authority(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import digest
        for name in ('branch-equal_value_explicit_correction-plan.json', 'branch-fresh_duplicate_only-plan.json'):
            plan = deepcopy(ORACLE[name])
            plan['facts'][0]['economic_group_id'] = '80000000-0000-4000-8000-000000000099'
            if plan['heads']:
                plan['heads'][0]['prior_revision_id'] = None
                plan['heads'][0]['key_digest'] = digest({'version': 1, 'tenant_id': plan['tenant_id'],
                    'portfolio_id': plan['portfolio_id'], 'economic_group_id': plan['facts'][0]['economic_group_id']})
            with self.subTest(vector=name):
                self._reference_case(plan, baseline='plan-first-use.json', code='import_conflict')
        plan = deepcopy(ORACLE['branch-equal_value_explicit_correction-plan.json'])
        plan['facts'][0]['action'] = 'void'
        plan['heads'][0]['active'] = False
        self._reference_case(plan, baseline='plan-first-use.json', code='import_conflict')

    def test_plan_reference_entry_historical_snapshot_choice_covers_its_children(self):
        self._reference_case(ORACLE['snapshot-historical-t1-plan.json'])

    def test_plan_reference_entry_same_set_correction_path_reaches_current_head(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import digest
        plan = deepcopy(ORACLE['branch-equal_value_explicit_correction-plan.json'])
        minimal = deepcopy(ORACLE['branch-equal_value_explicit_correction-minimal.json'])
        minimal['records'][0]['identity']['revision'] = 'r3'
        stages = {digest(minimal): minimal}
        member = 'd0000000-0000-4000-8000-000000000099'
        next_id = 'b0000000-0000-4000-8000-000000000099'
        for name in ('inputs', 'pinned_sources', 'mappings', 'facts', 'parents'):
            extra = deepcopy(plan[name])
            for row in extra:
                row['member_id'] = member
                if name == 'inputs':
                    row['stage_digest'] = digest(minimal)
                if name == 'facts' and row['collection'] == 'records':
                    row['parent_revision_id'] = plan['facts'][0]['accepted_revision_id']
                    row['accepted_revision_id'] = next_id
                if name == 'parents':
                    row['parent_revision_id'] = plan['facts'][0]['accepted_revision_id']
                    row['reason'] = 'Explicit next correction in the same set'
            plan[name].extend(extra)
        plan['heads'][0]['next_revision_id'] = next_id
        self._reference_case(plan, baseline='plan-first-use.json', stages=stages)
        fork = deepcopy(plan)
        fork['facts'][3]['parent_revision_id'] = plan['facts'][0]['parent_revision_id']
        fork['parents'][1]['parent_revision_id'] = plan['facts'][0]['parent_revision_id']
        self._reference_case(fork, baseline='plan-first-use.json', stages=stages, code='import_conflict')
        foreign = deepcopy(plan)
        foreign['facts'][3]['economic_group_id'] = '80000000-0000-4000-8000-000000000099'
        foreign['heads'][0]['key_digest'] = digest({'version': 1, 'tenant_id': plan['tenant_id'],
            'portfolio_id': plan['portfolio_id'], 'economic_group_id': foreign['facts'][3]['economic_group_id']})
        self._reference_case(foreign, baseline='plan-first-use.json', stages=stages, code='import_conflict')

    def test_plan_reference_entry_overlapping_connections_require_explicit_choice(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import digest
        for choice in (None, 'independent', 'mirror'):
            plan = deepcopy(ORACLE['plan-native-first-use.json'])
            first = plan['inputs'][0]['member_id']
            second = '20000000-0000-4000-8000-000000000099'
            for name in ('inputs', 'pinned_sources', 'mappings', 'facts'):
                extra = deepcopy(plan[name])
                for ordinal, row in enumerate(extra):
                    row['member_id'] = second
                    if name == 'pinned_sources':
                        row['connection_id'] = '20000000-0000-4000-8000-000000000098'
                    if name == 'facts':
                        row['accepted_revision_id'] = 'a0000000-0000-4000-8000-' + str(ordinal + 1).zfill(12)
                        if row['economic_group_id']:
                            row['economic_group_id'] = 'a0000000-0000-4000-8000-000000000099'
                plan[name].extend(extra)
            head = deepcopy(plan['heads'][0])
            head['next_revision_id'] = plan['facts'][2]['accepted_revision_id']
            head['key_digest'] = digest({'version': 1, 'tenant_id': plan['tenant_id'], 'portfolio_id': plan['portfolio_id'],
                'economic_group_id': plan['facts'][2]['economic_group_id']})
            plan['heads'].append(head)
            if choice:
                plan['authorities'] = [{'kind': choice, 'left': {'form': 'incoming', 'member_id': second,
                    'collection': 'records', 'local_id': '0'}, 'right': {'form': 'incoming', 'member_id': first,
                    'collection': 'records', 'local_id': '0'}, 'evidence_reference': 'Synthetic explicit stream choice'}]
                if choice == 'mirror':
                    plan['facts'][2]['action'] = 'mirror'
                    plan['heads'] = plan['heads'][:1]
            with self.subTest(choice=choice):
                self._reference_case(plan, code='import_conflict' if choice is None else None)

    def test_receipt_replay_exact_namespace_and_immutable_original_result(self):
        from kurafolio.ingestion.codec import encode
        receipt = ORACLE['receipt-first-use.json']
        tenant, portfolio = ORACLE['plan-first-use.json']['tenant_id'], ORACLE['plan-first-use.json']['portfolio_id']
        raw = encode(receipt)
        request = '1' * 64
        seed = "INSERT INTO wl_pg.instance_state VALUES(1,'" + receipt['origin_incarnation'] + "',0,true);"
        seed += "INSERT INTO wl_ingestion.receipts(tenant_id,portfolio_id,id,incarnation,restore_epoch,operation_id,operation_kind,request_digest,preview_id,accepted_plan_id,plan_digest,result_bytes,created_at) VALUES('" + tenant + "','" + portfolio + "','" + receipt['id'] + "','" + receipt['origin_incarnation'] + "',0,'" + receipt['operation_id'] + "','ACCEPT','" + request + "','" + receipt['preview_id'] + "','f0000000-0000-4000-8000-000000000002','" + receipt['plan_digest'] + "',decode('" + raw.hex() + "','hex'),'" + receipt['created_at']['token'] + "');"
        def call(*, user=tenant, operation=receipt['operation_id'], incarnation=receipt['origin_incarnation'], epoch=0, kind='ACCEPT', digest_=request):
            return "wl_ingestion._replay_v1('" + user + "','" + portfolio + "','" + incarnation + "'," + str(epoch) + ",'" + operation + "','" + kind + "','" + digest_ + "')"
        # No stage, preview, source or decisions row is needed to recover an
        # existing outcome. Live authentication is a required caller boundary.
        self.sql('BEGIN;' + seed + 'DO $check$ BEGIN IF wl_ingestion._canonical_v1(' + call() + ")<>decode('" + raw.hex() + "','hex') OR (SELECT count(*) FROM wl_ingestion.receipts)<>1 OR (SELECT count(*) FROM wl_ingestion.source_revisions)<>0 THEN RAISE EXCEPTION 'receipt_not_original'; END IF; END $check$;ROLLBACK;")
        for label, expression, code in (
                ('changed_kind', call(kind='CANCEL'), 'import_conflict'),
                ('changed_digest', call(digest_='2' * 64), 'import_conflict'),
                ('old_incarnation', call(incarnation='70000000-0000-4000-8000-000000000099'), 'instance_not_ready'),
                ('old_epoch', call(epoch=1), 'instance_not_ready'),
                ('invalid_kind', call(kind='CONFIRM'), 'import_invalid'),
                ('invalid_digest', call(digest_='ABC'), 'import_invalid')):
            with self.subTest(case=label):
                self.sql('BEGIN;' + seed + 'DO $check$ BEGIN BEGIN PERFORM ' + expression + "; RAISE EXCEPTION 'replay_expected_rejection'; EXCEPTION WHEN SQLSTATE '22023' THEN IF SQLERRM<>'" + code + "' THEN RAISE; END IF; END; END $check$;ROLLBACK;")
        for expression in (call(user='30000000-0000-4000-8000-000000000099'),
                call(operation='50000000-0000-4000-8000-000000000099')):
            self.sql('BEGIN;' + seed + 'DO $check$ BEGIN IF ' + expression + " IS NOT NULL THEN RAISE EXCEPTION 'foreign_or_missing_replay'; END IF; END $check$;ROLLBACK;")

    def test_receipt_replay_is_private_and_requires_initialized_current_realm(self):
        call = "wl_ingestion._replay_v1('30000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000002','70000000-0000-4000-8000-000000000002',0,'50000000-0000-4000-8000-000000000001','ACCEPT','" + '1' * 64 + "')"
        for seed in ('', "INSERT INTO wl_pg.instance_state VALUES(1,'70000000-0000-4000-8000-000000000002',0,false);"):
            self.sql('BEGIN;' + seed + 'DO $check$ BEGIN BEGIN PERFORM ' + call + "; RAISE EXCEPTION 'replay_not_ready'; EXCEPTION WHEN SQLSTATE '22023' THEN IF SQLERRM<>'instance_not_ready' THEN RAISE; END IF; END; END $check$;ROLLBACK;")
        self.assertEqual('0', self.sql("SELECT count(*) FROM pg_catalog.pg_proc p CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE "
            "p.oid='wl_ingestion._replay_v1(uuid,uuid,uuid,bigint,uuid,text,text)'::regprocedure "
            "AND a.grantee=0 AND a.privilege_type='EXECUTE'"))

    def test_append_only_guard_and_no_public_execution(self):
        from kurafolio.ingestion.codec import encode
        minimal = ORACLE['minimal-native.json']
        raw = encode(minimal)
        def literal(value):
            return "'" + value.replace("'", "''") + "'"
        values = [literal('30000000-0000-4000-8000-000000000001'),
            literal('40000000-0000-4000-8000-000000000001'),
            literal('50000000-0000-4000-8000-000000000001'), literal('minimal-evidence-v1'),
            'decode(' + literal(raw.hex()) + ",'hex')", literal(hashlib.sha256(raw).hexdigest()),
            literal(minimal['provenance']['raw_sha256']),
            literal(minimal['provenance']['discovery_sha256']),
            literal(minimal['provenance']['installation_id']), "'2026-02-02T13:00:00+00:00'::timestamptz"]
        insert = 'INSERT INTO wl_ingestion.accepted_inputs VALUES(' + ','.join(values) + ');'
        self.sql('BEGIN;' + insert + "DO $test$ BEGIN IF (SELECT count(*) FROM "
                 "wl_ingestion.accepted_inputs)<>1 THEN RAISE EXCEPTION 'insert_missing'; "
                 'END IF; END $test$;ROLLBACK;')
        for mutation in ('UPDATE wl_ingestion.accepted_inputs SET created_at=created_at',
                         'DELETE FROM wl_ingestion.accepted_inputs'):
            with self.subTest(mutation=mutation):
                self.sql('BEGIN;' + insert + 'DO $test$ BEGIN BEGIN ' + mutation +
                    "; RAISE EXCEPTION 'missing_append_only_guard'; EXCEPTION WHEN SQLSTATE '22023' "
                    "THEN IF SQLERRM<>'import_invalid' THEN RAISE; END IF; END; IF (SELECT count(*) "
                    "FROM wl_ingestion.accepted_inputs)<>1 THEN RAISE EXCEPTION 'evidence_changed'; "
                    'END IF; END $test$;ROLLBACK;')
        self.sql('CREATE ROLE wl007_synthetic_reader NOLOGIN;')
        self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_reader',"
                                     "'wl_ingestion._immutable_v1()','EXECUTE')"))
        self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_reader',"
                                     "'wl_ingestion._outbox_guard_v1()','EXECUTE')"))
        self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_reader',"
                                     "'wl_ingestion._guard_user_v1(text,uuid,bigint,jsonb,text)','EXECUTE')"))
        self.assertEqual('0', self.sql('SELECT count(*) FROM wl_ingestion.accepted_inputs'))

    def test_user_guard_on_constructed_markers_checks_live_auth_not_financial_truth(self):
        from kurafolio.data_sources import contract_v1 as contract
        from kurafolio.data_sources.catalog_v1 import catalog_digest
        from kurafolio.persistence import identity_schema
        catalog = contract.CatalogSnapshot(1, '0', (), (), ())
        catalog_bytes = contract.canonical(contract.primitive(catalog))
        expected_catalog = catalog_digest(catalog)
        user = '30000000-0000-4000-8000-000000000001'
        portfolio = '40000000-0000-4000-8000-000000000001'
        incarnation = '60000000-0000-4000-8000-000000000001'
        token = '1' * 64
        def literal(value):
            return "'" + value.replace("'", "''") + "'"
        # These rolled-back markers isolate the helper. They are deliberately
        # not an operator upgrade, installed full profile or initialization test.
        seed = f"""
INSERT INTO wl_pg.alembic_version VALUES('0004_ingestion');
INSERT INTO wl_pg.instance_state VALUES(1,'{incarnation}',0,true);
INSERT INTO wl_pg.tenant_roots VALUES('{user}','{portfolio}');
INSERT INTO wl_pg.portfolios(tenant_id,portfolio_id) VALUES('{user}','{portfolio}');
INSERT INTO wl_identity.users(id,portfolio_id,username,username_key,argon_hash,enabled,
 credential_version,credential_incarnation,credential_epoch,created_at)
VALUES('{user}','{portfolio}','SyntheticGuard','syntheticguard','synthetic-unused-hash',
 true,1,'{incarnation}',0,pg_catalog.clock_timestamp()-interval '2 minutes');
INSERT INTO wl_identity.instance_auth_state VALUES(1,'{'2' * 64}',
 pg_catalog.clock_timestamp()-interval '1 minute',true,'{user}');
INSERT INTO wl_identity.sessions
SELECT '{token}','authenticated','{user}'::uuid,1,n,n,n+interval '43200 seconds',
 '{incarnation}'::uuid,0,false FROM (SELECT pg_catalog.clock_timestamp()-interval '1 minute' AS n) q;
INSERT INTO wl_sources.catalog_state VALUES(1,0,'{expected_catalog}',
 decode('{catalog_bytes.hex()}','hex'),pg_catalog.clock_timestamp());
INSERT INTO wl_ingestion.instance_state VALUES(1,pg_catalog.convert_to('[]','UTF8'),
 pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('[]','UTF8')),'hex'),
 '{'3' * 64}',true);
"""
        realm = identity_schema.realm()
        check = f"""
DO $test$ DECLARE st wl_pg.instance_state%ROWTYPE;result jsonb;
BEGIN
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1;
 result:=wl_ingestion._guard_user_v1('{token}','{user}',1,{realm},'{expected_catalog}');
 IF result->>'ok'<>'true' OR result#>>'{{value,tenant_id}}'<>'{user}' OR
  result#>>'{{value,portfolio_id}}'<>'{portfolio}' OR
  pg_catalog.current_setting('ledger.tenant_id',true)<>'{user}' OR
  pg_catalog.current_setting('ledger.portfolio_id',true)<>'{portfolio}' THEN
  RAISE EXCEPTION 'expected_live_scope';
 END IF;
 IF (SELECT count(*) FROM wl_ingestion.source_revisions)<>0 THEN
  RAISE EXCEPTION 'auth_guard_created_financial_fact';
 END IF;
END $test$;
"""
        self.sql('BEGIN;' + seed + check + 'ROLLBACK;')
        mutations = [
            ("UPDATE wl_ingestion.instance_state SET ready=false;", 'instance_not_ready'),
            ("UPDATE wl_pg.instance_state SET ready=false;", 'instance_not_ready'),
            ("UPDATE wl_pg.alembic_version SET version_num='0003_source_lifecycle';", 'instance_not_ready'),
            ("DELETE FROM wl_pg.alembic_version;", 'instance_not_ready'),
            ("UPDATE wl_identity.instance_auth_state SET bootstrap_closed=false,admin_user_id=NULL;", 'instance_not_ready'),
            ("UPDATE wl_identity.instance_auth_state SET last_observed_at=pg_catalog.clock_timestamp()+interval '1 day';", 'instance_not_ready'),
            ("UPDATE wl_identity.users SET enabled=false;", 'authentication_required'),
            ("UPDATE wl_identity.users SET credential_version=2;", 'credentials_changed'),
            ("UPDATE wl_identity.users SET credential_epoch=1;", 'authentication_required'),
            ("UPDATE wl_identity.sessions SET revoked=true;", 'session_changed'),
            ("UPDATE wl_identity.sessions SET credential_version=2;", 'session_changed'),
            ("UPDATE wl_identity.sessions SET created_at=created_at-interval '13 hours',last_activity=last_activity-interval '13 hours',expires_at=expires_at-interval '13 hours';", 'session_changed'),
            ("DELETE FROM wl_sources.catalog_state;", 'source_catalog_unavailable'),
        ]
        for mutation, code in mutations:
            assertion = check[:check.index(" IF result->>'ok'")] + f"""
 IF result IS DISTINCT FROM pg_catalog.jsonb_build_object('ok',false,'code','{code}') THEN
  RAISE EXCEPTION 'expected_fixed_auth_rejection';
 END IF;
END $test$;
"""
            with self.subTest(mutation=mutation, code=code):
                self.sql('BEGIN;' + seed + mutation + assertion + 'ROLLBACK;')
        for substituted, code in (
            (f"'{token}','{user}',2,{realm},'{expected_catalog}'", 'credentials_changed'),
            (f"'{token}','{user}',1,'{{}}'::jsonb,'{expected_catalog}'", 'instance_not_ready'),
            (f"'{token}','{user}',1,{realm},'{'0' * 64}'", 'source_catalog_unavailable')):
            assertion = ("DO $test$ DECLARE st wl_pg.instance_state%ROWTYPE;result jsonb; BEGIN "
                "SELECT * INTO st FROM wl_pg.instance_state WHERE id=1; "
                "result:=wl_ingestion._guard_user_v1(" + substituted + "); "
                "IF result IS DISTINCT FROM pg_catalog.jsonb_build_object('ok',false,'code'," +
                literal(code) + ") THEN RAISE EXCEPTION 'expected_fixed_auth_rejection'; END IF; END $test$;")
            with self.subTest(code=code, substituted=substituted):
                self.sql('BEGIN;' + seed + assertion + 'ROLLBACK;')

    def event_insert(self, value, *, row=None, raw=None):
        from kurafolio.ingestion.codec import encode
        row = value if row is None else row
        raw = encode(value) if raw is None else raw
        def literal(token):
            return "'" + token.replace("'", "''") + "'"
        values = [literal(row['tenant_id']), literal(row['portfolio_id']),
            literal('50000000-0000-4000-8000-000000000001'), literal(row['receipt_id']),
            '1', literal('facts.accepted.v1'), literal(row['accepted_generation']),
            literal(row['plan_digest']), 'decode(' + literal(raw.hex()) + ",'hex')",
            literal(hashlib.sha256(raw).hexdigest()), "'2026-02-02T14:10:00+00:00'::timestamptz", 'NULL']
        return 'INSERT INTO wl_ingestion.outbox VALUES(' + ','.join(values) + ');'

    def event_rejected(self, value, original, *, raw=None, code='import_invalid', settings=''):
        statement = self.event_insert(value, row=original, raw=raw)
        self.sql('BEGIN;' + settings + 'DO $test$ BEGIN BEGIN ' + statement +
            "RAISE EXCEPTION 'missing_outbox_guard'; EXCEPTION WHEN SQLSTATE '22023' "
            "THEN IF SQLERRM<> '" + code + "' THEN RAISE; END IF; END; IF (SELECT count(*) "
            "FROM wl_ingestion.outbox)<>0 THEN RAISE EXCEPTION 'invalid_outbox_inserted'; "
            'END IF; END $test$;ROLLBACK;')

    def test_outbox_literal_events_and_closed_rehashed_mutants(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import encode
        events = [x['event'] for x in ORACLE['effect-oracles.json']['cases'] if x.get('event')]
        self.assertEqual(3, len(events))
        for event in events:
            self.sql('BEGIN;' + self.event_insert(event) + 'ROLLBACK;')
        original = events[0]
        for field, value in [('version', True), ('type', 'unknown'), ('tenant_id', None),
                ('tenant_id', '00000000-0000-0000-0000-000000000000'),
                ('receipt_id', '50000000-0000-4000-8000-000000000001'),
                ('plan_digest', '0' * 64), ('accepted_generation', '3'),
                ('mapping_generation', '01'), ('mapping_generation', '9223372036854775808'),
                ('mapping_generation', 1), ('changed_head_keys', ['wrong']),
                ('changed_revision_ids', [None]), ('extra', 'not_in_the_contract')]:
            altered = deepcopy(original)
            altered[field] = value
            with self.subTest(field=field, value=value):
                self.event_rejected(altered, original)
        for token in ('2026-02-30T14:10:00+00:00', '2026-02-02T24:10:00+00:00',
                      '2026-02-02T14:10:60+00:00', '2026-02-02T14:10:00-00:00',
                      '2026-02-02T14:10:00+24:00', '2026-02-02T14:10:00.1234567+00:00'):
            altered = deepcopy(original)
            altered['accepted_at']['token'] = token
            with self.subTest(token=token):
                self.event_rejected(altered, original)
        for field, value in [('fractional_digits', 1), ('zone', '../invalid'),
                             ('zone', True), ('extra', None)]:
            altered = deepcopy(original)
            altered['accepted_at'][field] = value
            with self.subTest(time_field=field):
                self.event_rejected(altered, original)
        self.event_rejected(original, original, raw=json.dumps(original, indent=2).encode())
        raw = encode(original).replace(b'"version":1', b'"version":1,"version":1')
        self.event_rejected(original, original, raw=raw)
        for raw, code in ((b'\xff', 'import_invalid'), (b'[]', 'import_invalid'),
                          (b'[' * 33 + b'0' + b']' * 33, 'import_limit'),
                          (b'x' * (4194304 + 1), 'import_limit')):
            with self.subTest(raw_bytes=len(raw), code=code):
                self.event_rejected(original, original, raw=raw, code=code)

    def test_canonical_aggregation_preserves_exact_unicode_and_large_array_bytes(self):
        from kurafolio.ingestion.codec import encode
        for value in ({'\u53f0\u7063': 'value', '\u00e9': [True, False, None], 'A': {'z': -1, 'a': 0}},
                      {}, [], ['x'] * 40000, {'heads': ['a' * 64] * 40000}):
            raw = encode(value)
            text = raw.decode().replace("'", "''")
            actual = self.sql("SELECT pg_catalog.encode(wl_ingestion._canonical_v1('" +
                              text + "'::jsonb),'hex')")
            self.assertEqual(raw.hex(), actual)

    def test_outbox_original_offset_and_zone_labels_do_not_change_the_clock(self):
        from copy import deepcopy
        original = next(x['event'] for x in ORACLE['effect-oracles.json']['cases'] if x.get('event'))
        for token in ('2026-02-02T14:10:00Z', '2026-02-03T14:09:00+23:59',
                      '2026-02-01T14:11:00-23:59'):
            value = deepcopy(original)
            value['accepted_at']['token'] = token
            value['accepted_at']['zone'] = 'America/Toronto'
            with self.subTest(token=token):
                self.sql('BEGIN;' + self.event_insert(value, row=original) + 'ROLLBACK;')

    def test_outbox_regex_is_independent_of_session_string_escaping(self):
        from copy import deepcopy
        original = next(x['event'] for x in ORACLE['effect-oracles.json']['cases'] if x.get('event'))
        settings = 'SET LOCAL standard_conforming_strings=off;'
        self.sql('BEGIN;' + settings + self.event_insert(original) + 'ROLLBACK;')
        value = deepcopy(original)
        value['accepted_at']['token'] = '2026-02-02T14:10:00X00+00:00'
        value['accepted_at']['fractional_digits'] = 2
        self.event_rejected(value, original, settings=settings)

    def test_outbox_updates_and_deletes_remain_unavailable(self):
        event = next(x['event'] for x in ORACLE['effect-oracles.json']['cases'] if x.get('event'))
        for mutation in ('UPDATE wl_ingestion.outbox SET dispatched_at=created_at',
                         'DELETE FROM wl_ingestion.outbox'):
            with self.subTest(mutation=mutation):
                self.sql('BEGIN;' + self.event_insert(event) + 'DO $test$ BEGIN BEGIN ' + mutation +
                    "; RAISE EXCEPTION 'missing_outbox_guard'; EXCEPTION WHEN SQLSTATE '22023' "
                    "THEN IF SQLERRM<>'import_invalid' THEN RAISE; END IF; END; IF (SELECT count(*) "
                    "FROM wl_ingestion.outbox)<>1 THEN RAISE EXCEPTION 'event_changed'; END IF; "
                    'END $test$;ROLLBACK;')

    # Synthetic control rows for the transition/head guards. Seeds are inserted
    # before the triggers in the same rolled-back transaction, so a test can
    # start from expired or mid-workflow states without a separate engine.
    T, P = '30000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000002'
    WORKER, DISABLED = 'c7000000-0000-4000-8000-000000000001', 'c7000000-0000-4000-8000-000000000002'
    INCARNATION = '70000000-0000-4000-8000-000000000002'

    class Expression(str):
        pass

    @classmethod
    def row(cls, table, values):
        def literal(v):
            if v is None:
                return 'NULL'
            if type(v) is bool:
                return 'true' if v else 'false'
            if type(v) is bytes:
                return "decode('" + v.hex() + "','hex')"
            if type(v) is cls.Expression:
                return v
            return "'" + str(v).replace("'", "''") + "'"
        return ('INSERT INTO wl_ingestion.' + table + '(' + ','.join(values) + ') VALUES(' +
                ','.join(literal(v) for v in values.values()) + ');')

    @classmethod
    def set_row(cls, set_id, state='RECEIVING', revision=1, created='now()', members=2, reserved=0,
                portfolio=None):
        e = cls.Expression
        return cls.row('sets', {'tenant_id': cls.T, 'portfolio_id': portfolio or cls.P, 'id': set_id,
            'actor_user_id': cls.T, 'creation_operation_id': 'c1' + set_id[2:], 'request_digest': 'a' * 64,
            'incarnation': cls.INCARNATION, 'restore_epoch': 0, 'realm_digest': 'b' * 64, 'state': state,
            'revision': revision, 'created_at': e(created), 'expires_at': e(created + "+interval '86400 seconds'"),
            'member_count': members, 'reserved_bytes': reserved, 'receipt_id': None, 'cleanup_state': 'not_needed'})

    @classmethod
    def member_row(cls, set_id, member_id, ordinal, state='waiting', fence=1, raw=None, stage=None):
        return cls.row('members', {'tenant_id': cls.T, 'portfolio_id': cls.P, 'set_id': set_id, 'id': member_id,
            'ordinal': ordinal, 'connection_id': '40000000-0000-4000-8000-000000000001',
            'connection_version': 'c' * 64, 'installation_id': 'd' * 64, 'format_version': '1',
            'context_digest': hashlib.sha256(b'{}').hexdigest(), 'context_bytes': b'{}',
            'raw_digest': raw, 'raw_bytes': 10 if raw else None, 'state': state, 'error_code': None,
            'stage_digest': stage, 'fence': fence, 'connection_generation': 1, 'enablement_generation': 1,
            'availability_generation': 1, 'wrapper_profile_digest': 'e' * 64, 'raw_deadline': None})

    @classmethod
    def lease_row(cls, lease_id, set_id, member_id, worker=None, state='offered', fence=1,
                  token=None, created='now()', expires="now()+interval '20 seconds'", kind='normalize'):
        e = cls.Expression
        return cls.row('leases', {'tenant_id': cls.T, 'portfolio_id': cls.P, 'id': lease_id, 'set_id': set_id,
            'member_id': member_id, 'work_kind': kind, 'attempt': 1, 'fence': fence,
            'worker_id': worker or cls.WORKER, 'token_digest': token, 'session_digest': 'f' * 64,
            'credential_version': 1, 'incarnation': cls.INCARNATION, 'restore_epoch': 0,
            'created_at': e(created), 'expires_at': e(expires), 'state': state,
            'claim_request_id': None, 'claim_request_digest': None, 'last_request_id': None,
            'last_request_digest': None, 'last_result_bytes': None})

    @classmethod
    def revision_row(cls, revision_id, change='original', parent=None, collection='records',
                     typed=None, number=0):
        from kurafolio.ingestion.codec import encode
        typed = encode(typed if typed is not None else {'record_type': 'activity', 'n': number})
        return cls.row('source_revisions', {'tenant_id': cls.T, 'portfolio_id': cls.P, 'id': revision_id,
            'source_key': hashlib.sha256(revision_id.encode()).hexdigest(), 'source_revision': '1',
            'financial_digest': hashlib.sha256(typed).hexdigest(), 'source_change': 'original',
            'accepted_change': change, 'parent_id': parent, 'input_id': 'f0000000-0000-4000-8000-000000000001',
            'collection': collection, 'local_id': str(number), 'typed_bytes': typed,
            'typed_digest': hashlib.sha256(typed).hexdigest(), 'created_at': '2026-02-02T13:00:00+00:00'})

    def guarded(self, seed, body):
        triggers = ''.join('CREATE TRIGGER ' + x['name'] + ' BEFORE INSERT OR UPDATE OR DELETE ON wl_ingestion.' +
            x['table'] + ' FOR EACH ROW EXECUTE FUNCTION wl_ingestion.' + x['function'] + '();'
            for x in schema.inventory()['triggers'] if x['function'] in {'_transition_v1', '_head_v1'})
        self.sql('BEGIN;' + seed + triggers + ''.join(body) + 'ROLLBACK;')

    @staticmethod
    def rejects(statement, message='import_invalid'):
        return ('DO $check$ BEGIN BEGIN ' + statement.rstrip(';') + "; RAISE EXCEPTION 'guard_missing'; "
                "EXCEPTION WHEN SQLSTATE '22023' THEN IF SQLERRM<>'" + message + "' THEN RAISE; END IF; "
                'END; END $check$;')

    def test_transition_guard_set_states_revisions_and_expiry(self):
        live, old, fresh = ('a1000000-0000-4000-8000-00000000000' + x for x in '123')
        where = " WHERE id='" + live + "'"
        root = self.row('roots', {'tenant_id': self.T, 'portfolio_id': self.P, 'accepted_generation': 0,
            'mapping_generation': 0, 'control_generation': 0})
        seed = root + self.set_row(old, 'NORMALIZING', created="now()-interval '2 days'")
        update = 'UPDATE wl_ingestion.sets SET '
        self.guarded(seed, [
            self.rejects(self.row('roots', {'tenant_id': self.P, 'portfolio_id': self.T,
                'accepted_generation': 1, 'mapping_generation': 0, 'control_generation': 0})),
            self.set_row(live),
            self.rejects(self.set_row(fresh, 'READY')),
            self.rejects(self.set_row(fresh, created="now()-interval '2 days'")),
            self.rejects(update + "state='READY'" + where),
            update + "state='NORMALIZING'" + where + ';',
            self.rejects(update + "state='COMMITTED',revision=2,receipt_id='" + fresh + "'" + where),
            self.rejects(update + "state='READY'" + where),
            self.rejects(update + "state='NEEDS_MAPPING',revision=2" + where),
            update + "state='READY',revision=2" + where + ';',
            update + "state='RECONCILING',revision=3" + where + ';',
            update + "state='READY',revision=4" + where + ';',
            self.rejects(update + "cleanup_state='pending'" + where),
            self.rejects(update + 'member_count=1' + where),
            self.rejects(update + "expires_at=expires_at+interval '1 second',created_at=created_at+interval '1 second'" + where),
            update + "state='COMMITTED',revision=5,receipt_id='" + fresh + "'" + where + ';',
            self.rejects(update + "state='CANCELLED',revision=6" + where),
            self.rejects(update + "receipt_id='" + old + "'" + where),
            update + "cleanup_state='pending'" + where + ';',
            update + "cleanup_state='complete'" + where + ';',
            self.rejects(update + "cleanup_state='pending'" + where),
            self.rejects('DELETE FROM wl_ingestion.sets' + where),
            # Expiry wins over every other live transition at the DB clock.
            self.rejects(update + "state='READY',revision=2 WHERE id='" + old + "'", 'import_expired'),
            self.rejects(update + "state='EXPIRED',revision=2 WHERE id='" + old + "'"),
            update + "state='EXPIRED' WHERE id='" + old + "';",
            self.set_row(fresh),
            self.rejects(update + "state='EXPIRED' WHERE id='" + fresh + "'", 'import_expired'),
            self.rejects('UPDATE wl_ingestion.roots SET accepted_generation=2'),
            'UPDATE wl_ingestion.roots SET accepted_generation=1,mapping_generation=1;',
            self.rejects('DELETE FROM wl_ingestion.roots'),
            "DO $test$ BEGIN IF (SELECT pg_catalog.string_agg(state||':'||revision||':'||cleanup_state,',' "
            "ORDER BY id) FROM wl_ingestion.sets)<>'COMMITTED:5:complete,EXPIRED:1:not_needed,RECEIVING:1:not_needed' "
            "THEN RAISE EXCEPTION 'unexpected_set_states'; END IF; END $test$;"])

    def test_transition_guard_member_fences_raw_binding_and_stale_leases(self):
        live, other = 'a2000000-0000-4000-8000-000000000001', 'a2000000-0000-4000-8000-000000000002'
        m0, m1, mx = ('b2000000-0000-4000-8000-00000000000' + x for x in '123')
        l0, l1, lx = ('d2000000-0000-4000-8000-00000000000' + x for x in '123')
        stage = hashlib.sha256(b'{}').hexdigest()
        member = 'UPDATE wl_ingestion.members SET '
        lease = 'UPDATE wl_ingestion.leases SET '
        at0, at1 = " WHERE id='" + m0 + "'", " WHERE id='" + m1 + "'"
        on0 = " WHERE id='" + l0 + "'"
        seed = (self.row('roots', {'tenant_id': self.T, 'portfolio_id': self.P, 'accepted_generation': 0,
                    'mapping_generation': 0, 'control_generation': 0}) +
            self.row('workers', {'id': self.WORKER, 'login_role': 'wl_worker', 'peer_identity': 'peer-a',
                'enabled': True, 'credential_epoch': 1}) +
            self.row('workers', {'id': self.DISABLED, 'login_role': 'wl_worker', 'peer_identity': 'peer-b',
                'enabled': False, 'credential_epoch': 1}) +
            self.set_row(live) + self.set_row(other) + self.member_row(other, mx, 0, 'receiving') +
            self.lease_row(lx, other, mx, created="now()-interval '2 minutes'",
                expires="now()-interval '100 seconds'"))
        stage_row = self.row('stages', {'tenant_id': self.T, 'portfolio_id': self.P, 'set_id': live,
            'member_id': m0, 'digest': stage, 'codec': 'minimal-evidence-v1', 'minimal_bytes': b'{}',
            'created_at': self.Expression('now()'), 'purge_at': self.Expression("now()+interval '86400 seconds'")})
        self.guarded(seed, [
            self.member_row(live, m0, 0),
            self.rejects(self.member_row(live, m1, 2)),
            self.rejects(self.member_row(live, m1, 1, 'admitted', raw='1' * 64, stage=stage)),
            self.lease_row(l0, live, m0),
            self.rejects(self.lease_row(l1, live, m0, expires="now()+interval '50 seconds'")),
            self.rejects(self.lease_row(l1, live, m0, state='active', token='2' * 64)),
            self.rejects(self.lease_row(l1, live, m0, fence=2)),
            self.rejects(self.lease_row(l1, live, m0, worker=self.DISABLED)),
            member + "state='receiving',raw_deadline=now()+interval '120 seconds'" + at0 + ';',
            member + "raw_digest='" + '1' * 64 + "',raw_bytes=10" + at0 + ';',
            self.rejects(member + "raw_digest='" + '3' * 64 + "'" + at0),
            lease + "token_digest='" + '2' * 64 + "',expires_at=now()+interval '60 seconds'" + on0 + ';',
            self.rejects(lease + "expires_at=now()+interval '90 seconds'" + on0),
            lease + "state='active',claim_request_id='" + l1 + "',claim_request_digest='" + '4' * 64 + "'" + on0 + ';',
            self.rejects(lease + "worker_id='" + self.DISABLED + "'" + on0),
            member + "state='normalizing'" + at0 + ';',
            self.rejects(member + "state='admitted',stage_digest='" + stage + "'" + at0),
            self.rejects(stage_row.replace("+interval '86400 seconds'", "+interval '86399 seconds'")),
            stage_row,
            member + "state='admitted',stage_digest='" + stage + "'" + at0 + ';',
            self.rejects(member + 'connection_generation=2' + at0),
            self.rejects(member + "state='committed'" + at0),
            self.rejects(member + 'context_bytes=NULL' + at0),
            lease + "state='finished'" + on0 + ';',
            self.rejects(lease + "state='active'" + on0),
            self.rejects('DELETE FROM wl_ingestion.leases' + on0),
            # A reupload attempt advances the fence before replacing raw bindings.
            self.member_row(live, m1, 1),
            member + "state='receiving',raw_deadline=now()+interval '120 seconds',raw_digest='" + '5' * 64 + "',raw_bytes=10" + at1 + ';',
            member + "state='reupload_required'" + at1 + ';',
            self.rejects(member + "state='receiving',raw_digest='" + '6' * 64 + "'" + at1),
            self.rejects(member + "state='receiving'" + at1),
            self.rejects(member + "state='receiving',fence=3,raw_digest='" + '6' * 64 + "'" + at1),
            member + "state='receiving',fence=2,raw_digest='" + '6' * 64 + "'" + at1 + ';',
            self.rejects(self.lease_row(l1, live, m1, fence=1)),
            self.lease_row(l1, live, m1, fence=2),
            self.rejects(lease + "state='active',token_digest='" + '7' * 64 + "',claim_request_id='" + l0 +
                "',claim_request_digest='" + '8' * 64 + "' WHERE id='" + lx + "'", 'import_expired'),
            lease + "state='expired' WHERE id='" + lx + "';",
            "DO $test$ BEGIN IF (SELECT pg_catalog.string_agg(state||':'||fence,',' ORDER BY ordinal) FROM "
            "wl_ingestion.members WHERE set_id='" + live + "')<>'admitted:1,receiving:2' THEN "
            "RAISE EXCEPTION 'unexpected_members'; END IF; END $test$;"])

    def test_transition_guard_transient_rows_pin_previews_and_purge_after_terminal(self):
        live, member, view, stale = ('a3000000-0000-4000-8000-00000000000' + x for x in '1234')
        from kurafolio.ingestion.codec import encode
        plan = encode({'synthetic': 'plan'})
        seed = (self.row('roots', {'tenant_id': self.T, 'portfolio_id': self.P, 'accepted_generation': 2,
                    'mapping_generation': 3, 'control_generation': 4}) +
            self.set_row(live, 'RECONCILING', revision=2, members=1) +
            self.member_row(live, member, 0, 'admitted', raw='1' * 64, stage=hashlib.sha256(b'{}').hexdigest()) +
            self.row('stages', {'tenant_id': self.T, 'portfolio_id': self.P, 'set_id': live, 'member_id': member,
                'digest': hashlib.sha256(b'{}').hexdigest(), 'codec': 'minimal-evidence-v1', 'minimal_bytes': b'{}',
                'created_at': self.Expression('now()'), 'purge_at': self.Expression("now()+interval '86400 seconds'")}))
        def decision(revision):
            return self.row('decisions', {'tenant_id': self.T, 'portfolio_id': self.P, 'set_id': live,
                'revision': revision, 'request_digest': '9' * 64, 'canonical_bytes': b'{}',
                'digest': hashlib.sha256(b'{}').hexdigest(), 'created_at': self.Expression('now()'),
                'purge_at': self.Expression("now()+interval '86400 seconds'")})
        def preview(preview_id, plan_bytes=plan, set_revision=3, accepted=2):
            return self.row('previews', {'tenant_id': self.T, 'portfolio_id': self.P, 'id': preview_id,
                'set_id': live, 'set_revision': set_revision, 'decision_revision': 1, 'plan_bytes': plan_bytes,
                'plan_digest': hashlib.sha256(plan_bytes).hexdigest() if plan_bytes else None,
                'expected_accepted_generation': accepted, 'expected_mapping_generation': 3,
                'expected_control_generation': 4, 'incarnation': self.INCARNATION, 'restore_epoch': 0,
                'realm_digest': 'b' * 64, 'expires_at': self.Expression("now()+interval '86400 seconds'"),
                'created_at': self.Expression('now()'), 'purge_at': self.Expression("now()+interval '86400 seconds'"),
                'review_bytes': b'{}', 'review_digest': hashlib.sha256(b'{}').hexdigest()})
        update = "UPDATE wl_ingestion.sets SET "
        self.guarded(seed, [
            decision(1), self.rejects(decision(3)),
            self.rejects('UPDATE wl_ingestion.decisions SET created_at=created_at'),
            update + "state='READY',revision=3;",
            self.rejects(decision(2)),
            self.rejects(preview(stale, accepted=1)),
            self.rejects(preview(stale, plan_bytes=None)),
            self.rejects(preview(stale, set_revision=2)),
            preview(view),
            self.rejects('UPDATE wl_ingestion.previews SET created_at=created_at'),
            self.rejects('DELETE FROM wl_ingestion.previews'),
            self.rejects('DELETE FROM wl_ingestion.decisions'),
            self.rejects('DELETE FROM wl_ingestion.stages'),
            update + "state='CANCELLED',revision=4;",
            self.rejects(preview(stale, set_revision=4)),
            'DELETE FROM wl_ingestion.previews;DELETE FROM wl_ingestion.decisions;DELETE FROM wl_ingestion.stages;',
            "DO $test$ BEGIN IF (SELECT count(*) FROM wl_ingestion.previews)+(SELECT count(*) FROM "
            "wl_ingestion.decisions)+(SELECT count(*) FROM wl_ingestion.stages)<>0 OR (SELECT count(*) FROM "
            "wl_ingestion.members)<>1 THEN RAISE EXCEPTION 'unexpected_purge'; END IF; END $test$;"])

    def test_transition_guard_quota_windows_readiness_and_worker_epochs(self):
        e = self.Expression
        def quota(bucket, window, used):
            return self.row('quotas', {'tenant_id': self.T, 'portfolio_id': self.P, 'bucket': bucket,
                'window_start': e(window), 'used_count': used, 'reserved_bytes': 0, 'lease_count': 0,
                'outstanding_sets': 0})
        seed = (quota('raw', "now()-interval '10 minutes'", 5) + quota('read', "now()-interval '1 minute'", 5) +
            self.row('instance_state', {'id': 1, 'wrapper_catalog_bytes': b'{}',
                'wrapper_catalog_digest': hashlib.sha256(b'{}').hexdigest(), 'runtime_profile_digest': 'a' * 64,
                'ready': True}) +
            self.row('workers', {'id': self.WORKER, 'login_role': 'wl_worker', 'peer_identity': 'peer-a',
                'enabled': True, 'credential_epoch': 1}))
        q = 'UPDATE wl_ingestion.quotas SET '
        w = 'UPDATE wl_ingestion.workers SET '
        self.guarded(seed, [
            quota('control', 'now()', 0), self.rejects(quota('storage', 'now()', 1)),
            self.rejects(quota('storage', "now()+interval '1 minute'", 0)),
            self.rejects(q + "used_count=4 WHERE bucket='raw'"),
            self.rejects(q + "window_start=now(),used_count=0,reserved_bytes=1 WHERE bucket='raw'"),
            q + "window_start=now(),used_count=0 WHERE bucket='raw';",
            self.rejects(q + "window_start=now(),used_count=0 WHERE bucket='read'"),
            q + "reserved_bytes=10,lease_count=1,used_count=6 WHERE bucket='read';",
            q + "reserved_bytes=0,lease_count=0 WHERE bucket='read';",
            self.rejects("DELETE FROM wl_ingestion.quotas WHERE bucket='read'"),
            self.row('instance_budgets', {'bucket': 'raw', 'window_start': e('now()'), 'used_count': 0,
                'reserved_bytes': 0, 'lease_count': 0, 'outstanding_sets': 0}),
            self.rejects("UPDATE wl_ingestion.instance_budgets SET used_count=0,window_start=window_start-interval '1 second'"),
            # Instance rows have no scope columns; an ordinary held-count change is allowed.
            'UPDATE wl_ingestion.instance_budgets SET used_count=1,lease_count=1;',
            self.rejects("UPDATE wl_ingestion.instance_budgets SET bucket='read'"),
            self.rejects("UPDATE wl_ingestion.instance_state SET runtime_profile_digest='" + 'b' * 64 + "'"),
            'UPDATE wl_ingestion.instance_state SET ready=false;',
            "UPDATE wl_ingestion.instance_state SET runtime_profile_digest='" + 'b' * 64 + "';",
            self.rejects('DELETE FROM wl_ingestion.instance_state'),
            w + "peer_identity='peer-c',credential_epoch=2;",
            self.rejects(w + 'credential_epoch=1'),
            self.rejects(w + "peer_identity='peer-d'"),
            w + 'enabled=false;',
            self.rejects('DELETE FROM wl_ingestion.workers'),
            "DO $test$ BEGIN IF (SELECT pg_catalog.string_agg(bucket||':'||used_count,',' ORDER BY bucket) "
            "FROM wl_ingestion.quotas)<>'control:0,raw:0,read:6' THEN RAISE EXCEPTION 'unexpected_quotas'; "
            'END IF; END $test$;'])

    def test_head_guard_activity_chains_descend_without_forks_or_cycles(self):
        ids = {name: 'e7000000-0000-4000-8000-0000000000' + str(10 + index)
               for index, name in enumerate(('A', 'B', 'C', 'Z', 'D', 'H', 'N', 'X', 'Y', 'A2', 'B2', 'C2', 'P', 'P1', 'P2'))}
        groups = {name: 'e8000000-0000-4000-8000-00000000000' + str(index) for index, name in enumerate('1234567', 1)}
        seed = ''.join((
            self.revision_row(ids['A'], number=1),
            self.revision_row(ids['B'], 'correction', ids['A'], number=2),
            self.revision_row(ids['C'], 'void', ids['B'], number=3),
            self.revision_row(ids['Z'], 'correction', ids['C'], number=4),
            self.revision_row(ids['D'], number=5),
            self.revision_row(ids['H'], 'historical', number=6),
            self.revision_row(ids['N'], collection='snapshots', typed={'kind': 'snapshot'}, number=7),
            self.revision_row(ids['X'], 'correction', ids['Y'], number=8),
            self.revision_row(ids['Y'], 'correction', ids['X'], number=9),
            self.revision_row(ids['A2'], number=10),
            self.revision_row(ids['B2'], 'correction', ids['A2'], number=11),
            self.revision_row(ids['C2'], 'correction', ids['B2'], number=12),
            self.revision_row(ids['P'], number=13),
            self.revision_row(ids['P1'], 'correction', ids['P'], number=14),
            self.revision_row(ids['P2'], 'correction', ids['P'], number=15)))
        def head(group, target, active=True):
            return self.row('activity_heads', {'tenant_id': self.T, 'portfolio_id': self.P,
                'economic_group_id': groups[group], 'revision_id': ids[target], 'active': active})
        def move(group, target, active=True):
            return ("UPDATE wl_ingestion.activity_heads SET revision_id='" + ids[target] + "',active=" +
                    str(active).lower() + " WHERE economic_group_id='" + groups[group] + "'")
        self.guarded(seed, [
            self.rejects(head('1', 'A', False)), head('1', 'A'),
            self.rejects(head('2', 'H')), self.rejects(head('2', 'N')),
            self.rejects(head('3', 'B'), 'import_conflict'),
            self.rejects(head('4', 'X'), 'import_conflict'),
            head('2', 'D'),
            self.rejects(move('1', 'A', False)),
            self.rejects(move('1', 'D'), 'import_conflict'),
            self.rejects("UPDATE wl_ingestion.activity_heads SET economic_group_id='" + groups['5'] +
                "' WHERE economic_group_id='" + groups['1'] + "'"),
            move('1', 'B') + ';',
            self.rejects(move('1', 'A'), 'import_conflict'),
            move('1', 'C', False) + ';',
            self.rejects(move('1', 'Z'), 'import_conflict'),
            self.rejects('DELETE FROM wl_ingestion.activity_heads'),
            # A same-set correction path may advance one head over several steps.
            head('5', 'A2'), move('5', 'C2') + ';',
            # A second group may not head the parent or a sibling of another group's head.
            head('6', 'P1'),
            self.rejects(head('7', 'P'), 'import_conflict'),
            self.rejects(head('7', 'P2'), 'import_conflict'),
            "DO $test$ BEGIN IF (SELECT pg_catalog.string_agg(revision_id::text||':'||active,',' ORDER BY "
            "economic_group_id) FROM wl_ingestion.activity_heads)<>'" + ids['C'] + ':false,' + ids['D'] +
            ':true,' + ids['C2'] + ':true,' + ids['P1'] + ":true' THEN RAISE EXCEPTION 'unexpected_heads'; END IF; END $test$;"])

    def test_head_guard_snapshot_key_scope_complete_base_and_order(self):
        from kurafolio.ingestion.codec import encode
        effects = ORACLE['snapshot-history-effects.json']
        preimage = effects['head_preimage']
        self.assertEqual(effects['head_digest'], hashlib.sha256(encode(preimage)).hexdigest())
        ids = {name: 'e9000000-0000-4000-8000-0000000000' + str(10 + index)
               for index, name in enumerate(('S1', 'S2', 'S3', 'S4', 'S5', 'R'))}
        snapshot = {'kind': 'snapshot'}
        seed = ''.join((
            self.revision_row(ids['S1'], collection='snapshots', typed=snapshot, number=1),
            self.revision_row(ids['S2'], collection='snapshots', typed=snapshot, number=2),
            self.revision_row(ids['S3'], collection='snapshots', typed=snapshot, number=3),
            self.revision_row(ids['S4'], 'correction', ids['S3'], collection='snapshots', typed=snapshot, number=4),
            self.revision_row(ids['S5'], 'correction', ids['S1'], collection='snapshots', typed=snapshot, number=5),
            self.revision_row(ids['R'], number=6)))
        def head(scope, latest, base, account=preimage['account_id'], digest=None):
            key = dict(preimage, account_id=account, instrument_scope=scope)
            return self.row('snapshot_heads', {'tenant_id': self.T, 'portfolio_id': self.P,
                'key_digest': digest or hashlib.sha256(encode(key)).hexdigest(), 'account_id': account,
                'account_version': 'a' * 64, 'fact_kind': 'holdings', 'scope_bytes': encode(scope),
                'latest_revision_id': ids[latest], 'complete_base_revision_id': base and ids[base]})
        scope = preimage['instrument_scope']
        other = 'e9000000-0000-4000-8000-0000000000ff'
        move = "UPDATE wl_ingestion.snapshot_heads SET "
        def target(latest, base):
            return (move + "latest_revision_id='" + ids[latest] + "',complete_base_revision_id=" +
                    ("'" + ids[base] + "'" if base else 'NULL'))
        self.guarded(seed, [
            self.rejects(head(scope, 'S1', 'S1', digest=hashlib.sha256(encode(dict(preimage, account_id=other))).hexdigest())),
            self.rejects(head(scope, 'R', None)),
            self.rejects(head(scope, 'S1', 'S2'), 'import_conflict'),
            self.rejects(head({'tag': 'all', 'category': 'CASH', 'instrument_ids': []}, 'S1', None)),
            self.rejects(head({'tag': 'instruments', 'category': None, 'instrument_ids': [other]}, 'S1', None)),
            self.rejects(head({'tag': 'category', 'category': 'CASH', 'instrument_ids': [], 'extra': 1}, 'S1', None)),
            head(scope, 'S1', 'S1'),
            target('S2', 'S1') + ';',
            self.rejects(target('S2', 'S2'), 'import_conflict'),
            target('S3', 'S3') + ';',
            self.rejects(target('S5', 'S3'), 'import_conflict'),
            target('S4', 'S3') + ';',
            self.rejects(target('S3', 'S3'), 'import_conflict'),
            self.rejects(move + "account_id='" + other + "'"),
            self.rejects(move + "scope_bytes=decode('" + encode({'tag': 'category', 'category': 'CASH',
                'instrument_ids': []}).hex() + "','hex')"),
            self.rejects('DELETE FROM wl_ingestion.snapshot_heads'),
            "DO $test$ BEGIN IF (SELECT key_digest||':'||latest_revision_id||':'||complete_base_revision_id "
            "FROM wl_ingestion.snapshot_heads)<>'" + effects['head_digest'] + ':' + ids['S4'] + ':' + ids['S3'] +
            "' THEN RAISE EXCEPTION 'unexpected_snapshot_head'; END IF; END $test$;"])

    # Acceptance effects. A base Plan is accepted through _effects_v1 itself,
    # then the case Plan; each step first passes _references_v1 against the
    # rows the previous acceptance actually wrote. The caller-owned receipt row
    # and set/member state changes are outside _effects_v1 and these checks.
    COUNTED = ('accepted_inputs', 'accepted_plans', 'activity_heads', 'audit', 'authority_links', 'lineage',
               'mappings', 'outbox', 'snapshot_heads', 'source_revisions')
    RESULT_FIELDS = ('accepted_generation', 'mapping_generation', 'new_facts', 'historical_facts',
                     'duplicates', 'no_change', 'plan_digest', 'preview_id')

    @classmethod
    def effects_call(cls, plan, receipt):
        return ("wl_ingestion._effects_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] + "','" +
                plan['preview_id'] + "','" + receipt + "')")

    @classmethod
    def references_call(cls, plan):
        return ("SELECT wl_ingestion._references_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] +
                "','" + plan['preview_id'] + "');")

    def later_plan_seed(self, plan):
        # The root already exists, and earlier acceptance may have created the
        # existing targets; only the case's own set/stage/decision rows are new.
        lines = [x for x in self._plan_seed(plan).split('\n') if not x.startswith('INSERT INTO wl_ingestion.roots')]
        return '\n'.join(x[:-1] + ' ON CONFLICT DO NOTHING;' if x.startswith('INSERT INTO wl_pg.') else x
                         for x in lines) + self._preview_seed(plan)

    def accept_after(self, base, plan, receipt, *, between='', references=True):
        counts = ("SELECT 'COUNTS '||pg_catalog.jsonb_build_object(" + ','.join(
            "'" + t + "',(SELECT count(*) FROM wl_ingestion." + t + ')' for t in self.COUNTED) +
            ",'foundation_accounts',(SELECT count(*) FROM wl_pg.accounts),'foundation_instruments',"
            "(SELECT count(*) FROM wl_pg.instruments),'foundation_issuers',(SELECT count(*) FROM wl_pg.issuers))::text;")
        heads = "".join(x for x in ['CREATE TRIGGER ' + t['name'] + ' BEFORE INSERT OR UPDATE OR DELETE ON wl_ingestion.' +
            t['table'] + ' FOR EACH ROW EXECUTE FUNCTION wl_ingestion._head_v1();'
            for t in schema.inventory()['triggers'] if t['function'] == '_head_v1'])
        if base is None:
            prefix = self._plan_seed(plan) + self._preview_seed(plan) + heads + between
        else:
            prefix = (self._plan_seed(base) + self._preview_seed(base) + heads + self.references_call(base) +
                'SELECT ' + self.effects_call(base, 'b0000000-0000-4000-8000-000000000001') + ';' +
                self.later_plan_seed(plan) + 'UPDATE wl_ingestion.roots SET control_generation=' +
                plan['expected_control_generation'] + ';' + between)
        script = ('BEGIN;' + prefix +
            (self.references_call(plan) if references else '') + counts +
            "SELECT 'RESULT '||" + self.effects_call(plan, receipt) + '::text;' + counts +
            "SELECT 'LINEAGE '||COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('source_revision_id',l.source_revision_id,"
            "'collection',l.collection,'local_id',l.local_id,'evidence_digest',l.evidence_digest,'input_digest',a.digest,"
            "'claim',pg_catalog.convert_from(l.source_claim_bytes,'UTF8')) ORDER BY l.collection,l.local_id),'[]')::text "
            "FROM wl_ingestion.lineage l JOIN wl_ingestion.accepted_inputs a ON a.id=l.input_id AND a.tenant_id=l.tenant_id "
            "WHERE a.digest='" + plan['inputs'][0]['stage_digest'] + "';"
            "SELECT 'EVENT '||COALESCE((SELECT pg_catalog.convert_from(payload_bytes,'UTF8') FROM wl_ingestion.outbox "
            "WHERE receipt_id='" + receipt + "'),'null');"
            "SELECT 'HEADS '||pg_catalog.jsonb_build_object('activity',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array("
            "economic_group_id,revision_id,active) ORDER BY economic_group_id),'[]') FROM wl_ingestion.activity_heads),"
            "'snapshot',(SELECT COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(key_digest,latest_revision_id,"
            "complete_base_revision_id) ORDER BY key_digest),'[]') FROM wl_ingestion.snapshot_heads))::text;"
            "SELECT 'LINKS '||COALESCE((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(id,revision,decision_kind) "
            "ORDER BY id,revision) FROM wl_ingestion.authority_links),'[]')::text;"
            "SELECT 'GENERATIONS '||pg_catalog.jsonb_build_array(accepted_generation,mapping_generation,control_generation)::text "
            "FROM wl_ingestion.roots;ROLLBACK;")
        out = {}
        for line in self.sql(script).splitlines():
            label, _, value = line.partition(' ')
            if label in {'COUNTS', 'RESULT', 'LINEAGE', 'EVENT', 'HEADS', 'LINKS', 'GENERATIONS'}:
                out.setdefault(label, []).append(json.loads(value))
        before, after = out['COUNTS']
        delta = {k: after[k] - before[k] for k in after}
        return out['RESULT'][0], delta, out

    def assert_effects(self, case, result, delta, out, receipt):
        self.assertEqual({k: receipt[k] for k in self.RESULT_FIELDS}, result)
        expected = {k: v for k, v in case['inserted_rows'].items() if k != 'receipts'}
        self.assertEqual(expected, delta)
        self.assertEqual([receipt['accepted_generation'], receipt['mapping_generation']],
                         [str(x) for x in out['GENERATIONS'][0][:2]])

    def test_effects_branch_oracles_write_exact_rows_lineage_heads_and_events(self):
        cases = {x['name']: x for x in ORACLE['effect-oracles.json']['cases']}
        for name in ('fresh_duplicate_only', 'new_equal_meaning_revision', 'equal_value_explicit_correction',
                     'mapping_only_existing_issuer'):
            case = cases[name]
            plan = ORACLE[case['input_files']['plan']]
            base = ORACLE[case['prestate']['accepted_plan_file']]
            receipt = case['expected_receipt']
            with self.subTest(case=name):
                result, delta, out = self.accept_after(base, plan, receipt['id'])
                self.assert_effects(case, result, delta, out, receipt)
                self.assertEqual(case['new_input_digest'], plan['inputs'][0]['stage_digest'])
                self.assertEqual([{'source_revision_id': x['source_revision_id'], 'collection': x['collection'],
                    'local_id': x['local_id'], 'evidence_digest': x['evidence_digest'],
                    'input_digest': x['input_digest'], 'claim': x['source_claim_bytes_utf8']}
                    for x in sorted(case['expected_lineage'], key=lambda x: (x['collection'], x['local_id']))],
                    out['LINEAGE'][0])
                event = out['EVENT'][0]
                if case['event'] is None:
                    self.assertIsNone(event)
                else:
                    self.assertEqual({k: v for k, v in case['event'].items() if k != 'accepted_at'},
                                     {k: v for k, v in event.items() if k != 'accepted_at'})
                    self.assertEqual(('instant', None, 0), (event['accepted_at']['tag'],
                        event['accepted_at']['zone'], event['accepted_at']['fractional_digits']))
                if name == 'equal_value_explicit_correction':
                    head = plan['heads'][0]
                    self.assertIn([plan['facts'][0]['economic_group_id'], head['next_revision_id'], True],
                                  out['HEADS'][0]['activity'])

    def test_effects_authority_only_appends_the_existing_link_revision(self):
        from kurafolio.ingestion.codec import encode, digest
        case = next(x for x in ORACLE['effect-oracles.json']['cases'] if x['name'] == 'authority_only_explicit_mirror')
        prestate = ORACLE['authority-only-prestate.json']
        base, plan = ORACLE[prestate['base_plan']], ORACLE['authority-only-plan.json']
        peer = prestate['peer_revision']
        typed = encode(peer['typed'])
        scope = "'" + plan['tenant_id'] + "','" + plan['portfolio_id'] + "'"
        # The second accepted stream reuses the base input bytes, so its revision
        # points at the one retained input row for that digest.
        between = ("INSERT INTO wl_ingestion.source_revisions(tenant_id,portfolio_id,id,source_key,source_revision,"
            "financial_digest,source_change,accepted_change,parent_id,input_id,collection,local_id,typed_bytes,typed_digest,"
            "created_at) SELECT " + scope + ",'" + peer['id'] + "','" + peer['source_key_digest'] + "','r1','" +
            peer['financial_digest'] + "','original','original',NULL,a.id,'records','0',decode('" + typed.hex() +
            "','hex'),'" + digest(peer['typed']) + "','2026-02-02T13:00:00+00:00' FROM wl_ingestion.accepted_inputs a;"
            "INSERT INTO wl_ingestion.activity_heads VALUES(" + scope + ",'" + peer['economic_group_id'] + "','" +
            peer['id'] + "',true);"
            "INSERT INTO wl_ingestion.authority_links SELECT " + scope + ",'" + prestate['prior_link_id'] + "',1,'" +
            prestate['prior_authority']['left']['accepted_revision_id'] + "','" + peer['id'] + "','independent','" +
            prestate['prior_authority']['evidence_reference'] + "','" + digest(prestate['prior_authority']) +
            "',p.id FROM wl_ingestion.accepted_plans p;"
            "UPDATE wl_ingestion.roots SET accepted_generation=2,mapping_generation=2;")
        receipt = case['expected_receipt']
        # The peer stream has no accepted Plan of its own, so this case checks the
        # write path only; reference checks for authority links are covered above.
        result, delta, out = self.accept_after(base, plan, receipt['id'], between=between, references=False)
        self.assert_effects(case, result, delta, out, receipt)
        self.assertEqual([[prestate['prior_link_id'], 1, 'independent'],
                          [prestate['prior_link_id'], int(case['authority_link_revision']), 'mirror']], out['LINKS'][0])
        self.assertEqual(sorted([[base['facts'][0]['economic_group_id'], prestate['two_authoritative_head_targets'][0], True],
            [peer['economic_group_id'], peer['id'], True]]), sorted(out['HEADS'][0]['activity']))
        self.assertEqual({k: v for k, v in case['event'].items() if k != 'accepted_at'},
                         {k: v for k, v in out['EVENT'][0].items() if k != 'accepted_at'})

    def test_effects_snapshot_history_keeps_t2_current_and_stores_no_zero_rows(self):
        effects = ORACLE['snapshot-history-effects.json']
        seed, history = effects['sequence']
        base, plan = ORACLE[seed['input_plan']], ORACLE[history['input_plan']]
        result, delta, out = self.accept_after(base, plan, history['expected_receipt']['id'])
        self.assert_effects(history, result, delta, out, history['expected_receipt'])
        self.assertEqual([[effects['head_digest'], history['head_target_after'], history['head_complete_base_after']]],
                         out['HEADS'][0]['snapshot'])
        self.assertEqual(['historical_only'], [x[2] for x in out['LINKS'][0]])

    def test_effects_first_use_seeds_entities_mappings_and_one_snapshot_head(self):
        effects = ORACLE['snapshot-history-effects.json']
        seed = effects['sequence'][0]
        plan = ORACLE[seed['input_plan']]
        result, delta, out = self.accept_after(None, plan, seed['expected_receipt']['id'])
        self.assert_effects(seed, result, delta, out, seed['expected_receipt'])
        self.assertEqual([[effects['head_digest'], seed['head_target_after'], seed['head_complete_base_after']]],
                         out['HEADS'][0]['snapshot'])

    def test_effects_rejects_one_source_identity_mapped_to_two_targets(self):
        from copy import deepcopy
        from kurafolio.ingestion.codec import digest
        from kurafolio.ingestion.mapping import proposed_body
        plan = deepcopy(ORACLE['plan-first-use.json'])
        member = plan['inputs'][0]['member_id']
        minimal = deepcopy(next(v for v in ORACLE.values() if type(v) is dict and 'provenance' in v
                                and 'accounts' in v and digest(v) == plan['inputs'][0]['stage_digest']))
        # A BTC twin that differs only by its free-text descriptor shares one
        # mapping identity, but the Plan proposes a second instrument for it.
        btc = next(a for a in minimal['assets'] if a['kind'] == 'CRYPTO')
        twin = dict(btc, local_id=str(len(minimal['assets'])), source_descriptor=btc['source_descriptor'] + ' twin')
        minimal['assets'].append(twin)
        twin_id = '40000000-0000-4000-8000-0000000000c1'
        body = proposed_body(minimal, 'instrument', twin['local_id'], twin_id, plan['tenant_id'],
                             plan['portfolio_id'], plan['mappings'])
        plan['mappings'].append({'entity_kind': 'instrument', 'local_id': twin['local_id'], 'member_id': member,
                                 'target': {'id': twin_id, 'mode': 'proposed', 'version': digest(body)}})
        plan['new_entities'].append({'id': twin_id, 'kind': 'instrument', 'local_id': twin['local_id'],
                                     'member_id': member, 'version': digest(body)})
        plan['inputs'][0]['stage_digest'] = digest(minimal)
        decisions = {'version': 1, 'operation_id': '10000000-0000-4000-8000-0000000000c1',
                     'expected_set_revision': '1', **{k: plan[k] for k in ('mappings', 'new_entities', 'authorities', 'parents')}}
        plan['decision_digest'] = digest(decisions)
        seed = (self._plan_seed(plan, decisions=decisions, stages={digest(minimal): minimal}) +
                self._preview_seed(plan))
        call = self.effects_call(plan, 'b0000000-0000-4000-8000-0000000000bb')
        # The Plan itself validates; only the single accepted write refuses it.
        self.sql('BEGIN;' + seed + 'SELECT ' + self.references_call(plan)[len('SELECT '):] +
                 self.rejects('PERFORM ' + call, 'import_conflict') +
                 "DO $check$ BEGIN IF (SELECT count(*) FROM wl_ingestion.mappings)+(SELECT count(*) FROM "
                 "wl_ingestion.accepted_plans)<>0 THEN RAISE EXCEPTION 'twin_mapped'; END IF; END $check$;ROLLBACK;")

    def test_effects_never_applies_an_accepted_plan_twice_and_is_private(self):
        plan = ORACLE['plan-first-use.json']
        first = self.effects_call(plan, 'b0000000-0000-4000-8000-000000000001')
        again = self.effects_call(plan, 'b0000000-0000-4000-8000-0000000000aa')
        self.sql('BEGIN;' + self._plan_seed(plan) + self._preview_seed(plan) + "UPDATE wl_ingestion.sets SET state='RECONCILING';" +
            self.rejects('PERFORM ' + first, 'import_stale') + "DO $test$ BEGIN IF (SELECT count(*) FROM "
            "wl_ingestion.accepted_plans)<>0 THEN RAISE EXCEPTION 'reconciling_accepted'; END IF; END $test$;ROLLBACK;")
        self.sql('BEGIN;' + self._plan_seed(plan) + self._preview_seed(plan) + 'SELECT ' + first + ';' +
            # The advanced generations make the same Plan stale. If a caller
            # skipped that check, the retained Plan digest still blocks reuse.
            self.rejects('PERFORM ' + again, 'import_stale') +
            'SAVEPOINT forced;UPDATE wl_ingestion.roots SET accepted_generation=0,mapping_generation=0;' +
            self.rejects('PERFORM ' + again, 'import_conflict') + 'ROLLBACK TO SAVEPOINT forced;' +
            "DO $test$ BEGIN IF (SELECT count(*) FROM wl_ingestion.accepted_plans)<>1 OR (SELECT count(*) FROM "
            "wl_ingestion.source_revisions)<>3 OR (SELECT accepted_generation FROM wl_ingestion.roots)<>1 THEN "
            "RAISE EXCEPTION 'effects_applied_twice'; END IF; END $test$;ROLLBACK;")
        self.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE "
                 "rolname='wl007_synthetic_guard_reader') THEN CREATE ROLE wl007_synthetic_guard_reader NOLOGIN; "
                 'END IF; END $role$;')
        self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_guard_reader',"
            "'wl_ingestion._effects_v1(uuid,uuid,uuid,uuid)','EXECUTE')"))

    # Authenticated acceptance. Identity, catalog and source rows are rolled-back
    # synthetic markers like the user-guard test; source rows bypass their own
    # insert guards because the fixed installation IDs have no descriptor bytes.
    SESSION = '1' * 64

    def accept_seed(self, *, expires_in_hours=12, availability='ACTIVE', installations=None):
        from copy import deepcopy
        import datetime
        from kurafolio.ingestion.codec import encode, digest
        plan = deepcopy(ORACLE['plan-first-use.json'])
        expires = (datetime.datetime.now(datetime.timezone.utc) +
                   datetime.timedelta(hours=expires_in_hours)).replace(microsecond=0)
        plan['expires_at']['token'] = expires.isoformat()
        pin = plan['pinned_sources'][0]
        tenant, portfolio = plan['tenant_id'], plan['portfolio_id']
        catalog = encode({'availability': [{'availability_generation': pin['availability_generation'],
                                            'installation_id': pin['installation_id'], 'status': availability}]})
        wrappers = encode([{'installation_id': pin['installation_id'], 'profile_digest': pin['wrapper_profile_digest']}])
        seed = f"""
INSERT INTO wl_pg.alembic_version VALUES('0004_ingestion');
INSERT INTO wl_pg.instance_state VALUES(1,'{self.INCARNATION}',0,true);
INSERT INTO wl_pg.tenant_roots VALUES('{tenant}','{portfolio}');
INSERT INTO wl_pg.portfolios(tenant_id,portfolio_id) VALUES('{tenant}','{portfolio}');
INSERT INTO wl_identity.users(id,portfolio_id,username,username_key,argon_hash,enabled,
 credential_version,credential_incarnation,credential_epoch,created_at)
VALUES('{tenant}','{portfolio}','SyntheticAccept','syntheticaccept','synthetic-unused-hash',
 true,1,'{self.INCARNATION}',0,pg_catalog.clock_timestamp()-interval '2 minutes');
INSERT INTO wl_identity.instance_auth_state VALUES(1,'{'2' * 64}',
 pg_catalog.clock_timestamp()-interval '1 minute',true,'{tenant}');
INSERT INTO wl_identity.sessions
SELECT '{self.SESSION}','authenticated','{tenant}'::uuid,1,n,n,n+interval '43200 seconds',
 '{self.INCARNATION}'::uuid,0,false FROM (SELECT pg_catalog.clock_timestamp()-interval '1 minute' AS n) q;
INSERT INTO wl_sources.catalog_state VALUES(1,0,'{hashlib.sha256(catalog).hexdigest()}',
 decode('{catalog.hex()}','hex'),pg_catalog.clock_timestamp());
INSERT INTO wl_ingestion.instance_state VALUES(1,decode('{wrappers.hex()}','hex'),
 '{hashlib.sha256(wrappers).hexdigest()}','{'3' * 64}',true);
SET LOCAL session_replication_role=replica;
INSERT INTO wl_sources.lifecycle_roots VALUES('{tenant}','{portfolio}',1,pg_catalog.clock_timestamp());
INSERT INTO wl_sources.enablements VALUES('{tenant}','{portfolio}','synthetic.qa','FILE_IMPORT','synthetic.qa',
 '{pin['installation_id']}',true,1,{pin['enablement_generation']},pg_catalog.clock_timestamp(),pg_catalog.clock_timestamp());
INSERT INTO wl_pg.connections VALUES('{tenant}','{portfolio}','{pin['connection_id']}','{pin['connection_version']}',
 '{{}}','synthetic.qa','{hashlib.sha256(b'synthetic.qa').hexdigest()}','FILE_IMPORT',{pin['connection_generation']});
INSERT INTO wl_sources.connection_lifecycle VALUES('{tenant}','{portfolio}','{pin['connection_id']}',
 '{pin['connection_version']}','synthetic.qa','synthetic.qa','FILE_IMPORT','{pin['installation_id']}','Synthetic',NULL,
 true,1,pg_catalog.clock_timestamp(),pg_catalog.clock_timestamp());
SET LOCAL session_replication_role=origin;
CREATE TABLE wl_sources.synthetic_installation_ids(id text PRIMARY KEY);
ALTER TABLE wl_ingestion.accepted_inputs DROP CONSTRAINT accepted_inputs_installation_fk;
ALTER TABLE wl_ingestion.accepted_inputs ADD CONSTRAINT accepted_inputs_installation_fk FOREIGN KEY(installation_id)
 REFERENCES wl_sources.synthetic_installation_ids(id) DEFERRABLE INITIALLY DEFERRED;
""" + ''.join("INSERT INTO wl_sources.synthetic_installation_ids VALUES('" + x + "');"
              for x in ([pin['installation_id']] if installations is None else installations))
        # The accepted input FK keeps its name and is still checked inside acceptance;
        # only its target is a synthetic ID table for these rolled-back markers.
        return plan, seed + self._plan_seed(plan) + self._preview_seed(plan), hashlib.sha256(catalog).hexdigest()

    def accept_statement(self, label, payload, catalog_digest, *, session=None):
        from kurafolio.persistence import identity_schema
        payload_text = json.dumps(payload).replace("'", "''")
        return ("DO $accept$ DECLARE st wl_pg.instance_state%ROWTYPE;r jsonb; BEGIN "
            "SELECT * INTO st FROM wl_pg.instance_state WHERE id=1; "
            "r:=wl_ingestion.accept_preview_v1('" + (session or self.SESSION) + "','" +
            ORACLE['plan-first-use.json']['tenant_id'] + "',1," + identity_schema.realm() + ",'" + catalog_digest +
            "','" + payload_text + "'::jsonb); "
            "PERFORM pg_catalog.set_config('test." + label + "',r::text,true); END $accept$;"
            "SELECT '" + label.upper() + " '||pg_catalog.current_setting('test." + label + "');")

    STATE = ("SELECT 'STATE '||pg_catalog.jsonb_build_object('set',(SELECT pg_catalog.jsonb_build_array(state,revision,"
             "receipt_id,cleanup_state) FROM wl_ingestion.sets),'members',(SELECT pg_catalog.jsonb_agg(state) FROM "
             "wl_ingestion.members),'receipts',(SELECT count(*) FROM wl_ingestion.receipts),'audit',(SELECT count(*) FROM "
             "wl_ingestion.audit),'outbox',(SELECT count(*) FROM wl_ingestion.outbox),'revisions',(SELECT count(*) FROM "
             "wl_ingestion.source_revisions),'generations',(SELECT pg_catalog.jsonb_build_array(accepted_generation,"
             "mapping_generation) FROM wl_ingestion.roots))::text;")

    def run_labelled(self, script):
        out = {}
        for line in self.sql('BEGIN;' + script + 'ROLLBACK;').splitlines():
            label, _, value = line.partition(' ')
            if label.isupper() and value.startswith(('{', '[')):
                out[label] = json.loads(value)
        return out

    def test_accept_preview_commits_once_and_replays_the_exact_receipt(self):
        from kurafolio.ingestion.codec import digest
        plan, seed, catalog = self.accept_seed()
        operation = '50000000-0000-4000-8000-000000000001'
        payload = {'operation_id': operation, 'preview_id': plan['preview_id'], 'preview_digest': digest(plan)}
        out = self.run_labelled(seed +
            self.accept_statement('first', payload, catalog) + self.STATE +
            self.accept_statement('again', payload, catalog) +
            self.accept_statement('changed', dict(payload, preview_digest='0' * 64), catalog) +
            self.accept_statement('fresh', dict(payload, operation_id='50000000-0000-4000-8000-000000000002'), catalog) +
            self.accept_statement('wrongplan', dict(payload, operation_id='50000000-0000-4000-8000-000000000005',
                                                    preview_digest='0' * 64), catalog) +
            # Cleanup may purge the preview; its permanent receipt still answers.
            'DELETE FROM wl_ingestion.previews;' +
            self.accept_statement('purged', dict(payload, operation_id='50000000-0000-4000-8000-000000000006'), catalog) +
            self.accept_statement('purgedwrong', dict(payload, operation_id='50000000-0000-4000-8000-000000000007',
                                                      preview_digest='0' * 64), catalog) +
            self.STATE.replace("'STATE '", "'AFTER '"))
        first = out['FIRST']
        self.assertTrue(first['ok'])
        receipt = first['value']
        oracle = ORACLE['receipt-first-use.json']
        for field in ('accepted_generation', 'mapping_generation', 'new_facts', 'historical_facts', 'duplicates',
                      'no_change', 'kind', 'operation_id', 'preview_id', 'origin_restore_epoch'):
            self.assertEqual(oracle[field], receipt[field], field)
        self.assertEqual((digest(plan), self.INCARNATION), (receipt['plan_digest'], receipt['origin_incarnation']))
        self.assertEqual(('instant', None, 0), (receipt['created_at']['tag'], receipt['created_at']['zone'],
                                               receipt['created_at']['fractional_digits']))
        self.assertEqual(first, out['AGAIN'])
        self.assertEqual({'ok': False, 'code': 'import_operation_conflict'}, out['CHANGED'])
        self.assertEqual(first, out['FRESH'])
        self.assertEqual({'ok': False, 'code': 'import_stale'}, out['WRONGPLAN'])
        self.assertEqual(first, out['PURGED'])
        self.assertEqual({'ok': False, 'code': 'not_found'}, out['PURGEDWRONG'])
        expected = {'set': ['COMMITTED', int(plan['expected_set_revision']) + 1, receipt['id'], 'pending'],
                    'members': ['committed'], 'receipts': 1, 'audit': 1, 'outbox': 1, 'revisions': 3,
                    'generations': [1, 1]}
        self.assertEqual(expected, out['STATE'])
        self.assertEqual(expected, out['AFTER'])

    def test_accept_preview_rejects_stale_sources_and_requests_without_writing(self):
        from kurafolio.ingestion.codec import digest
        plan, seed, catalog = self.accept_seed()
        payload = {'operation_id': '50000000-0000-4000-8000-000000000003', 'preview_id': plan['preview_id'],
                   'preview_digest': digest(plan)}
        replica = 'SET LOCAL session_replication_role=replica;'
        origin = 'SET LOCAL session_replication_role=origin;'
        cases = (
            ('disabled_connection', replica + 'UPDATE wl_sources.connection_lifecycle SET enabled=false;' + origin, payload, 'source_unavailable'),
            ('disabled_source', replica + 'UPDATE wl_sources.enablements SET enabled=false;' + origin, payload, 'source_unavailable'),
            ('enablement_generation', replica + 'UPDATE wl_sources.enablements SET generation=generation+1;' + origin, payload, 'import_stale'),
            ('connection_generation', replica + 'UPDATE wl_pg.connections SET generation=generation+1;' + origin, payload, 'import_stale'),
            ('wrapper_removed', "UPDATE wl_ingestion.instance_state SET wrapper_catalog_bytes=pg_catalog.convert_to('[]','UTF8'),"
                "wrapper_catalog_digest=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('[]','UTF8')),'hex');", payload, 'source_unavailable'),
            ('wrapper_not_top_level', "UPDATE wl_ingestion.instance_state i SET wrapper_catalog_bytes=q.b,"
                "wrapper_catalog_digest=pg_catalog.encode(pg_catalog.sha256(q.b),'hex') FROM (SELECT pg_catalog.convert_to("
                "'{\"revoked\":'||pg_catalog.convert_from(wrapper_catalog_bytes,'UTF8')||'}','UTF8') AS b "
                "FROM wl_ingestion.instance_state) q;", payload, 'source_unavailable'),
            ('needs_mapping', "UPDATE wl_ingestion.sets SET state='NEEDS_MAPPING';", payload, 'import_mapping_required'),
            ('wrong_digest', '', dict(payload, preview_digest='0' * 64), 'import_stale'),
            ('unknown_preview', '', dict(payload, preview_id='20000000-0000-4000-8000-0000000000ff'), 'not_found'),
            ('extra_field', '', dict(payload, facts=[]), 'import_invalid'),
            ('revoked_session', 'UPDATE wl_identity.sessions SET revoked=true;', payload, 'session_changed'),
        )
        for name, mutation, request, code in cases:
            with self.subTest(case=name):
                out = self.run_labelled(seed + mutation + self.accept_statement('result', request, catalog) + self.STATE)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                self.assertEqual((0, 0, 0, [0, 0]), (out['STATE']['receipts'], out['STATE']['revisions'],
                                                     out['STATE']['outbox'], out['STATE']['generations']))
                self.assertEqual('READY' if name != 'needs_mapping' else 'NEEDS_MAPPING', out['STATE']['set'][0])
        # A deferred reference that would fail at COMMIT is proven inside the call.
        plan, seed, catalog = self.accept_seed(installations=[])
        out = self.run_labelled(seed + self.accept_statement('result', dict(payload, preview_digest=digest(plan)), catalog)
                                + self.STATE)
        self.assertEqual({'ok': False, 'code': 'import_conflict'}, out['RESULT'])
        self.assertEqual((0, 0, 0), (out['STATE']['receipts'], out['STATE']['revisions'], out['STATE']['audit']))
        # A revoked catalog installation is unavailable even with a valid digest.
        plan, seed, catalog = self.accept_seed(availability='REVOKED')
        payload = dict(payload, preview_digest=digest(plan))
        out = self.run_labelled(seed + self.accept_statement('result', payload, catalog) + self.STATE)
        self.assertEqual({'ok': False, 'code': 'source_unavailable'}, out['RESULT'])

    def test_accept_preview_expiry_wins_and_fences_the_set(self):
        from kurafolio.ingestion.codec import digest
        plan, seed, catalog = self.accept_seed(expires_in_hours=-1)
        payload = {'operation_id': '50000000-0000-4000-8000-000000000004', 'preview_id': plan['preview_id'],
                   'preview_digest': digest(plan)}
        out = self.run_labelled(seed + self.accept_statement('result', payload, catalog) + self.STATE)
        self.assertEqual({'ok': False, 'code': 'import_expired'}, out['RESULT'])
        self.assertEqual({'set': ['EXPIRED', int(plan['expected_set_revision']), None, 'pending'], 'members': ['expired'],
                          'receipts': 0, 'audit': 0, 'outbox': 0, 'revisions': 0, 'generations': [0, 0]}, out['STATE'])

    def test_accept_preview_is_not_public(self):
        self.assertEqual('0', self.sql("SELECT count(*) FROM pg_catalog.pg_proc p CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE "
            "p.oid='wl_ingestion.accept_preview_v1(text,uuid,bigint,jsonb,text,jsonb)'::regprocedure "
            "AND a.grantee=0 AND a.privilege_type='EXECUTE'"))

    def test_transition_and_head_guards_have_no_public_execution(self):
        self.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE "
                 "rolname='wl007_synthetic_guard_reader') THEN CREATE ROLE wl007_synthetic_guard_reader NOLOGIN; "
                 'END IF; END $role$;')
        for name in ('_transition_v1', '_head_v1'):
            with self.subTest(function=name):
                self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_guard_reader',"
                    "'wl_ingestion." + name + "()','EXECUTE')"))
                self.assertEqual('true|search_path=pg_catalog, pg_temp', self.sql("SELECT prosecdef::text||'|'||"
                    "pg_catalog.array_to_string(proconfig,',') FROM pg_catalog.pg_proc WHERE "
                    "oid='wl_ingestion." + name + "()'::regprocedure"))

    # Quota and purge helpers run inside the same rolled-back guarded
    # transaction. Seeds precede the triggers, so aged windows need no clock.
    P2 = '30000000-0000-4000-8000-000000000003'

    def quota_call(self, bucket, count, size=0, portfolio=None):
        return ("SELECT wl_ingestion._quota_v1('" + self.T + "','" + (portfolio or self.P) + "','" + bucket +
                "'," + str(count) + ',' + str(size) + ');')

    def quota_state(self, expected, where=''):
        return ("DO $test$ BEGIN IF (SELECT pg_catalog.string_agg(portfolio_id::text||'/'||bucket||':'||used_count||"
                "':'||lease_count||':'||outstanding_sets||':'||reserved_bytes,',' ORDER BY portfolio_id,bucket) FROM "
                "wl_ingestion.quotas " + where + ")IS DISTINCT FROM '" + expected + "' THEN RAISE EXCEPTION "
                "'unexpected_quotas'; END IF; END $test$;")

    def test_quota_rates_slots_and_storage_are_shared_and_released_once(self):
        e = self.Expression
        def aged(table, bucket, used, minutes):
            values = {'bucket': bucket, 'window_start': e("now()-interval '" + str(minutes) + " minutes'"),
                'used_count': used, 'reserved_bytes': 0, 'lease_count': 0, 'outstanding_sets': 0}
            if table == 'quotas':
                values = {'tenant_id': self.T, 'portfolio_id': self.P, **values}
            return self.row(table, values)
        seed = (aged('quotas', 'control', 30, 10) + aged('instance_budgets', 'control', 300, 10) +
                aged('quotas', 'read', 60, 1) + aged('instance_budgets', 'read', 60, 1))
        full = schema.SET_RESERVATION_BYTES
        others = ['30000000-0000-4000-8000-00000000001' + str(x) for x in range(4)]
        self.guarded(seed, [
            # An aged window resets only the attempt count; a current one stays exhausted.
            self.quota_call('control', 1),
            self.rejects(self.quota_call('read', 1), 'import_busy'),
            self.rejects(self.quota_call('read', 2)), self.rejects(self.quota_call('control', -1)),
            self.rejects(self.quota_call('control', 1, 1)), self.rejects(self.quota_call('unknown', 1)),
            self.rejects(self.quota_call('raw', 0)), self.rejects(self.quota_call('raw', 1, 5)),
            self.rejects(self.quota_call('storage', 0, 0)), self.rejects(self.quota_call('storage', 1, -1)),
            self.rejects(self.quota_call('storage', -1, 1)), self.rejects(self.quota_call('storage', 1, full + 1)),
            self.rejects("SELECT wl_ingestion._quota_v1(NULL,'" + self.P + "','read',1,0)"),
            # One concurrent raw slot per user; release is once, and attempts stay counted.
            self.quota_call('raw', 1), self.rejects(self.quota_call('raw', 1), 'import_busy'),
            self.quota_call('raw', -1), self.rejects(self.quota_call('raw', -1)),
            *[self.quota_call('raw', x) for x in (1, -1) * 9],
            self.rejects(self.quota_call('raw', 1), 'import_busy'),
            # Four instance raw slots are shared across portfolios.
            *[self.quota_call('raw', 1, portfolio=x) for x in others],
            self.rejects(self.quota_call('raw', 1, portfolio=self.P2), 'import_busy'),
            *[self.quota_call('raw', -1, portfolio=x) for x in others],
            # Eight outstanding sets and their worst-case bytes per user.
            *[self.quota_call('storage', 1, full) for _ in range(8)],
            self.rejects(self.quota_call('storage', 1, full), 'import_limit'),
            self.rejects(self.quota_call('storage', 0, 1), 'import_limit'),
            self.quota_call('storage', -1, -full),
            self.rejects(self.quota_call('storage', -1, -full, portfolio=self.P2)),
            self.quota_state(self.P + '/control:1:0:0:0,' + self.P + '/raw:10:0:0:0,' + self.P + '/read:60:0:0:0,' +
                             self.P + '/storage:0:0:7:' + str(7 * full), "WHERE portfolio_id='" + self.P + "'"),
            "DO $test$ BEGIN IF (SELECT pg_catalog.string_agg(bucket||':'||used_count||':'||lease_count||':'||"
            "outstanding_sets||':'||reserved_bytes,',' ORDER BY bucket) FROM wl_ingestion.instance_budgets)<>"
            "'control:1:0:0:0,raw:14:0:0:0,read:60:0:0:0,storage:0:0:7:" + str(7 * full) + "' THEN "
            "RAISE EXCEPTION 'unexpected_instance_budgets'; END IF; END $test$;"])

    def test_quota_instance_storage_bound_spans_portfolios(self):
        full = schema.SET_RESERVATION_BYTES
        portfolios = ['30000000-0000-4000-8000-0000000002' + format(x, '02d') for x in range(8)]
        body = [self.quota_call('storage', 1, full, portfolio=x) for x in portfolios for _ in range(8)]
        body.append(self.rejects(self.quota_call('storage', 1, full), 'import_limit'))
        body.append(self.quota_call('storage', -1, -full, portfolio=portfolios[0]))
        body.append(self.quota_call('storage', 1, full))
        self.guarded('', body)

    def test_purge_removes_only_transient_rows_and_releases_storage_once(self):
        live, done, member, other, lease, missing = ('a5000000-0000-4000-8000-00000000000' + x for x in '123456')
        digest = hashlib.sha256(b'{}').hexdigest()
        full = schema.SET_RESERVATION_BYTES
        e = self.Expression
        def transient(set_id, member_id):
            return (self.row('stages', {'tenant_id': self.T, 'portfolio_id': self.P, 'set_id': set_id,
                    'member_id': member_id, 'digest': digest, 'codec': 'minimal-evidence-v1', 'minimal_bytes': b'{}',
                    'created_at': e('now()'), 'purge_at': e("now()+interval '86400 seconds'")}) +
                self.row('decisions', {'tenant_id': self.T, 'portfolio_id': self.P, 'set_id': set_id,
                    'revision': 1, 'request_digest': '9' * 64, 'canonical_bytes': b'{}', 'digest': digest,
                    'created_at': e('now()'), 'purge_at': e("now()+interval '86400 seconds'")}))
        seed = (self.row('roots', {'tenant_id': self.T, 'portfolio_id': self.P, 'accepted_generation': 0,
                    'mapping_generation': 0, 'control_generation': 0}) +
            self.set_row(live, 'RECONCILING', revision=2, members=1, reserved=full) +
            self.member_row(live, member, 0, 'admitted', raw='1' * 64, stage=digest) + transient(live, member) +
            self.lease_row(lease, live, member) +
            self.set_row(done, 'CANCELLED', revision=2, members=1, reserved=full) +
            self.member_row(done, other, 0, 'cancelled') + transient(done, other))
        purge = "SELECT wl_ingestion._purge_v1('" + self.T + "','" + self.P + "','{}');"
        counts = ("DO $test$ BEGIN IF (SELECT pg_catalog.string_agg(s.id::text||':'||s.cleanup_state||':'||"
                  "(SELECT count(*) FROM wl_ingestion.stages g WHERE g.set_id=s.id)||':'||(SELECT count(*) FROM "
                  "wl_ingestion.decisions d WHERE d.set_id=s.id)||':'||(SELECT count(*) FROM wl_ingestion.members m "
                  "WHERE m.set_id=s.id AND m.context_bytes IS NOT NULL),',' ORDER BY s.id) FROM wl_ingestion.sets s)"
                  "<>'{}' THEN RAISE EXCEPTION 'unexpected_purge_state'; END IF; END $test$;")
        self.guarded(seed, [
            self.quota_call('storage', 1, full),
            self.rejects(purge.format(live)),
            self.rejects(purge.format(missing), 'not_found'),
            "UPDATE wl_ingestion.sets SET state='CANCELLED',revision=3 WHERE id='" + live + "';",
            "UPDATE wl_ingestion.members SET state='cancelled' WHERE id='" + member + "';",
            # Live work may still own a child or raw slot; cleanup fails closed.
            self.rejects(purge.format(live), 'import_busy'),
            "UPDATE wl_ingestion.leases SET state='cancelled' WHERE id='" + lease + "';",
            purge.format(live),
            counts.replace('{}', live + ':complete:0:0:0,' + done + ':not_needed:1:1:1'),
            self.quota_state(self.P + '/storage:0:0:0:0'),
            # Repeating a completed purge releases nothing a second time.
            purge.format(live), self.quota_state(self.P + '/storage:0:0:0:0'),
            # A set whose reservation is already gone rolls back its whole purge.
            self.rejects(purge.format(done)),
            counts.replace('{}', live + ':complete:0:0:0,' + done + ':not_needed:1:1:1'),
            "DO $test$ BEGIN IF (SELECT count(*) FROM wl_ingestion.sets)<>2 OR (SELECT count(*) FROM "
            "wl_ingestion.members)<>2 OR (SELECT count(*) FROM wl_ingestion.leases)<>1 THEN "
            "RAISE EXCEPTION 'purge_removed_control_rows'; END IF; END $test$;"])

    def test_quota_and_purge_have_no_public_execution(self):
        self.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE "
                 "rolname='wl007_synthetic_guard_reader') THEN CREATE ROLE wl007_synthetic_guard_reader NOLOGIN; "
                 'END IF; END $role$;')
        for signature in ('_quota_v1(uuid,uuid,text,bigint,bigint)', '_purge_v1(uuid,uuid,uuid)'):
            with self.subTest(function=signature):
                self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_guard_reader',"
                    "'wl_ingestion." + signature + "','EXECUTE')"))
                self.assertEqual('true|search_path=pg_catalog, pg_temp', self.sql("SELECT prosecdef::text||'|'||"
                    "pg_catalog.array_to_string(proconfig,',') FROM pg_catalog.pg_proc WHERE "
                    "oid='wl_ingestion." + signature + "'::regprocedure"))


    # cancel_set_v1 runs on the accept fixtures with the real transition guard,
    # so every set, member and lease change it makes is checked.
    def cancel_statement(self, label, payload, catalog_digest, *, session=None):
        return self.accept_statement(label, payload, catalog_digest, session=session).replace(
            'accept_preview_v1', 'cancel_set_v1').replace('$accept$', '$cancel$')

    TRANSITION_TRIGGERS = ''.join('CREATE TRIGGER ' + x['name'] + ' BEFORE INSERT OR UPDATE OR DELETE ON wl_ingestion.' +
        x['table'] + ' FOR EACH ROW EXECUTE FUNCTION wl_ingestion._transition_v1();'
        for x in schema.inventory()['triggers'] if x['function'] == '_transition_v1')

    CANCEL_STATE = ("SELECT 'CSTATE '||pg_catalog.jsonb_build_object('set',(SELECT pg_catalog.jsonb_build_array(state,"
        "revision,receipt_id,cleanup_state) FROM wl_ingestion.sets),'fences',(SELECT pg_catalog.jsonb_agg("
        "pg_catalog.jsonb_build_array(state,fence)) FROM wl_ingestion.members),'leases',(SELECT pg_catalog.jsonb_agg(state) "
        "FROM wl_ingestion.leases),'receipts',(SELECT pg_catalog.jsonb_agg(operation_kind ORDER BY operation_kind) FROM "
        "wl_ingestion.receipts),'audit',(SELECT pg_catalog.jsonb_agg(action ORDER BY action) FROM wl_ingestion.audit),"
        "'generations',(SELECT pg_catalog.jsonb_build_array(accepted_generation,mapping_generation,control_generation) "
        "FROM wl_ingestion.roots))::text;")

    def cancel_seed(self, **kwargs):
        plan, seed, catalog = self.accept_seed(**kwargs)
        lease = self.lease_row('a6000000-0000-4000-8000-000000000001', plan['set_id'], None, kind='prepare').replace(
            "'" + self.T + "'", "'" + plan['tenant_id'] + "'").replace("'" + self.P + "'", "'" + plan['portfolio_id'] + "'")
        worker = self.row('workers', {'id': self.WORKER, 'login_role': 'wl_worker', 'peer_identity': 'peer-a',
                                      'enabled': True, 'credential_epoch': 1})
        return plan, seed + worker + lease + self.TRANSITION_TRIGGERS, catalog

    def test_cancel_wins_once_fences_work_and_replays_its_receipt(self):
        from kurafolio.ingestion.codec import digest
        plan, seed, catalog = self.cancel_seed()
        revision = plan['expected_set_revision']
        payload = {'operation_id': '51000000-0000-4000-8000-000000000001', 'set_id': plan['set_id'],
                   'expected_set_revision': revision}
        confirm = {'operation_id': '51000000-0000-4000-8000-000000000002', 'preview_id': plan['preview_id'],
                   'preview_digest': digest(plan)}
        out = self.run_labelled(seed + self.cancel_statement('first', payload, catalog) + self.CANCEL_STATE +
            self.cancel_statement('again', payload, catalog) +
            self.cancel_statement('reused', dict(payload, expected_set_revision=str(int(revision) + 1)), catalog) +
            self.cancel_statement('fresh', dict(payload, operation_id='51000000-0000-4000-8000-000000000003'), catalog) +
            self.accept_statement('confirm', confirm, catalog) + self.CANCEL_STATE.replace("'CSTATE '", "'CAFTER '"))
        first = out['FIRST']
        self.assertTrue(first['ok'], first)
        value = first['value']
        self.assertEqual(('CANCELLED', str(int(revision) + 1), 'pending', None, plan['set_id']),
                         (value['state'], value['revision'], value['cleanup_state'], value['receipt_id'], value['id']))
        self.assertEqual(['cancelled'], [m['state'] for m in value['members']])
        self.assertEqual(plan['preview_id'], value['preview_id'])
        self.assertEqual(('instant', 6), (value['expires_at']['tag'], value['expires_at']['fractional_digits']))
        expected = {'set': ['CANCELLED', int(revision) + 1, None, 'pending'], 'fences': [['cancelled', 2]],
                    'leases': ['cancelled'], 'receipts': ['CANCEL'], 'audit': ['CANCELLED'],
                    'generations': [0, 0, int(plan['expected_control_generation']) + 1]}
        self.assertEqual(expected, out['CSTATE'])
        self.assertEqual(first, out['AGAIN'])
        self.assertEqual({'ok': False, 'code': 'import_operation_conflict'}, out['REUSED'])
        self.assertEqual({'ok': False, 'code': 'import_stale'}, out['FRESH'])
        # A cancellation that won first leaves acceptance nothing to write.
        self.assertEqual({'ok': False, 'code': 'import_stale'}, out['CONFIRM'])
        self.assertEqual(expected, out['CAFTER'])

    def test_cancel_after_acceptance_returns_the_committed_set_unchanged(self):
        from kurafolio.ingestion.codec import digest
        plan, seed, catalog = self.cancel_seed()
        confirm = {'operation_id': '51000000-0000-4000-8000-000000000004', 'preview_id': plan['preview_id'],
                   'preview_digest': digest(plan)}
        payload = {'operation_id': '51000000-0000-4000-8000-000000000005', 'set_id': plan['set_id'],
                   'expected_set_revision': plan['expected_set_revision']}
        out = self.run_labelled(seed + self.accept_statement('confirm', confirm, catalog) +
                                self.cancel_statement('cancel', payload, catalog) + self.CANCEL_STATE)
        self.assertTrue(out['CONFIRM']['ok'], out['CONFIRM'])
        self.assertTrue(out['CANCEL']['ok'], out['CANCEL'])
        self.assertEqual(('COMMITTED', out['CONFIRM']['value']['id']),
                         (out['CANCEL']['value']['state'], out['CANCEL']['value']['receipt_id']))
        self.assertEqual((['ACCEPT'], ['ACCEPTED'], [1, 1, int(plan['expected_control_generation'])]), (out['CSTATE']['receipts'], out['CSTATE']['audit'],
                                                                 out['CSTATE']['generations']))

    def test_cancel_rejects_stale_expired_and_malformed_requests_without_writing(self):
        plan, seed, catalog = self.cancel_seed()
        payload = {'operation_id': '51000000-0000-4000-8000-000000000006', 'set_id': plan['set_id'],
                   'expected_set_revision': plan['expected_set_revision']}
        cases = (
            ('old_revision', dict(payload, expected_set_revision=str(int(plan['expected_set_revision']) - 1)), '', 'import_stale'),
            ('unknown_set', dict(payload, set_id='20000000-0000-4000-8000-0000000000ff'), '', 'not_found'),
            ('extra_field', dict(payload, reason='x'), '', 'import_invalid'),
            ('zero_revision', dict(payload, expected_set_revision='0'), '', 'import_invalid'),
            ('number_revision', dict(payload, expected_set_revision=int(plan['expected_set_revision'])), '', 'import_invalid'),
            ('revoked_session', payload, 'UPDATE wl_identity.sessions SET revoked=true;', 'session_changed'),
        )
        for name, request, mutation, code in cases:
            with self.subTest(case=name):
                out = self.run_labelled(seed + mutation + self.cancel_statement('result', request, catalog) + self.CANCEL_STATE)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                self.assertEqual({'set': ['READY', int(plan['expected_set_revision']), None, 'not_needed'],
                                  'fences': [['admitted', 1]], 'leases': ['offered'], 'receipts': None, 'audit': None,
                                  'generations': [0, 0, int(plan['expected_control_generation'])]}, out['CSTATE'])
        plan, seed, catalog = self.cancel_seed(expires_in_hours=-1)
        out = self.run_labelled(seed + self.cancel_statement('result', dict(payload, set_id=plan['set_id']), catalog) +
                                self.CANCEL_STATE)
        self.assertEqual({'ok': False, 'code': 'import_expired'}, out['RESULT'])
        self.assertEqual({'set': ['EXPIRED', int(plan['expected_set_revision']), None, 'pending'],
                          'fences': [['expired', 2]], 'leases': ['cancelled'], 'receipts': None, 'audit': None,
                          'generations': [0, 0, int(plan['expected_control_generation'])]}, out['CSTATE'])

    def test_cancel_is_not_public(self):
        self.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE "
                 "rolname='wl007_synthetic_guard_reader') THEN CREATE ROLE wl007_synthetic_guard_reader NOLOGIN; "
                 'END IF; END $role$;')
        self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_guard_reader',"
            "'wl_ingestion.cancel_set_v1(text,uuid,bigint,jsonb,text,jsonb)','EXECUTE')"))

    # decide_set_v1 and the one-ID reads run on the same READY accept fixture.
    def gateway_statement(self, function, label, payload, catalog_digest, *, session=None):
        return self.accept_statement(label, payload, catalog_digest, session=session).replace(
            'accept_preview_v1', function).replace('$accept$', '$gateway$')

    def decide_payload(self, plan, operation='52000000-0000-4000-8000-000000000001', **changes):
        from copy import deepcopy
        decisions = deepcopy(ORACLE['decisions-first-use.json'])
        decisions.update({'operation_id': operation, 'expected_set_revision': plan['expected_set_revision']})
        decisions.update(changes)
        return {'set_id': plan['set_id'], 'decisions': decisions}

    DECIDE_STATE = ("SELECT 'DSTATE '||pg_catalog.jsonb_build_object('set',(SELECT pg_catalog.jsonb_build_array(state,"
        "revision,cleanup_state) FROM wl_ingestion.sets),'decisions',(SELECT pg_catalog.jsonb_agg(revision ORDER BY revision) "
        "FROM wl_ingestion.decisions),'leases',(SELECT pg_catalog.jsonb_agg(state) FROM wl_ingestion.leases),"
        "'receipts',(SELECT pg_catalog.jsonb_agg(operation_kind ORDER BY operation_kind) FROM wl_ingestion.receipts),"
        "'audit',(SELECT pg_catalog.jsonb_agg(action ORDER BY action) FROM wl_ingestion.audit),'control',"
        "(SELECT control_generation FROM wl_ingestion.roots),'previews',(SELECT count(*) FROM wl_ingestion.previews))::text;")

    def test_decide_appends_one_revision_fences_preparation_and_replays(self):
        from kurafolio.ingestion.codec import digest, encode
        plan, seed, catalog = self.cancel_seed()
        payload = self.decide_payload(plan)
        revision, control = int(plan['expected_set_revision']), int(plan['expected_control_generation'])
        confirm = {'operation_id': '52000000-0000-4000-8000-000000000009', 'preview_id': plan['preview_id'],
                   'preview_digest': digest(plan)}
        out = self.run_labelled(seed + self.DECIDE_STATE.replace("'DSTATE '", "'DBEFORE '") +
            self.gateway_statement('decide_set_v1', 'first', payload, catalog) + self.DECIDE_STATE +
            self.gateway_statement('decide_set_v1', 'again', payload, catalog) +
            self.gateway_statement('decide_set_v1', 'reused', self.decide_payload(plan, mappings=[]), catalog) +
            self.gateway_statement('decide_set_v1', 'fresh', self.decide_payload(
                plan, '52000000-0000-4000-8000-000000000002'), catalog) +
            self.accept_statement('confirm', confirm, catalog) +
            self.gateway_statement('read_set_v1', 'read', {'set_id': plan['set_id']}, catalog) +
            "SELECT 'RID '||pg_catalog.jsonb_build_object('id',(SELECT id FROM wl_ingestion.receipts))::text;" +
            "SELECT 'STORED '||pg_catalog.jsonb_build_object('match',(SELECT canonical_bytes FROM wl_ingestion.decisions ORDER BY revision DESC LIMIT 1)="
            "decode('" + encode(payload['decisions']).hex() + "','hex'))::text;" +
            self.DECIDE_STATE.replace("'DSTATE '", "'DAFTER '"))
        first = out['FIRST']
        self.assertTrue(first['ok'], first)
        self.assertEqual(('RECONCILING', str(revision + 1)), (first['value']['state'], first['value']['revision']))
        before = out['DBEFORE']['decisions'] or []
        expected = {'set': ['RECONCILING', revision + 1, 'not_needed'],
                    'decisions': before + [(before[-1] if before else 0) + 1], 'leases': ['cancelled'],
                    'receipts': ['DECISIONS'], 'audit': ['DECIDED'], 'control': control + 1, 'previews': 1}
        self.assertEqual(expected, out['DSTATE'])
        self.assertEqual(first, out['AGAIN'])
        self.assertEqual({'ok': False, 'code': 'import_operation_conflict'}, out['REUSED'])
        self.assertEqual({'ok': False, 'code': 'import_stale'}, out['FRESH'])
        # The earlier READY preview can no longer be confirmed.
        self.assertEqual({'ok': False, 'code': 'import_stale'}, out['CONFIRM'])
        self.assertEqual(first, out['READ'])
        self.assertEqual({'match': True}, out['STORED'])
        self.assertEqual(expected, out['DAFTER'])

    def test_decide_rejects_stale_expired_oversized_and_malformed_requests_without_writing(self):
        plan, seed, catalog = self.cancel_seed()
        good = self.decide_payload(plan)
        unknown = self.decide_payload(plan)
        unknown['decisions']['note'] = 'x'
        bad_mapping = self.decide_payload(plan)
        bad_mapping['decisions']['mappings'][0]['entity_kind'] = 'wallet'
        cases = (
            ('old_revision', self.decide_payload(plan, expected_set_revision=str(int(plan['expected_set_revision']) - 1)),
             '', 'import_stale'),
            ('unknown_set', dict(good, set_id='20000000-0000-4000-8000-0000000000ff'), '', 'not_found'),
            ('unknown_field', unknown, '', 'import_invalid'),
            ('bad_mapping_kind', bad_mapping, '', 'import_invalid'),
            ('too_many_mappings', self.decide_payload(plan, mappings=good['decisions']['mappings'] * 129), '', 'import_invalid'),
            ('extra_top_level', dict(good, facts=[]), '', 'import_invalid'),
            ('reconciling', good, "UPDATE wl_ingestion.sets SET state='RECONCILING',revision=revision+1;", 'import_stale'),
            ('rejected', good, "SET LOCAL session_replication_role=replica;UPDATE wl_ingestion.sets SET state='REJECTED';"
             'SET LOCAL session_replication_role=origin;', 'import_stale'),
            # Retained transient bytes already fill the fixed set reservation.
            ('reservation_full', good, "SET LOCAL session_replication_role=replica;UPDATE wl_ingestion.sets SET "
             "reserved_bytes=(SELECT sum(octet_length(review_bytes)+octet_length(plan_bytes)) FROM wl_ingestion.previews)+"
             "(SELECT COALESCE(sum(octet_length(canonical_bytes)),0) FROM wl_ingestion.decisions)+"
             "(SELECT COALESCE(sum(octet_length(minimal_bytes)),0) FROM wl_ingestion.stages)+"
             "(SELECT COALESCE(sum(octet_length(context_bytes)),0) FROM wl_ingestion.members);"
             'SET LOCAL session_replication_role=origin;', 'import_limit'),
            ('revoked_session', good, 'UPDATE wl_identity.sessions SET revoked=true;', 'session_changed'),
        )
        for name, request, mutation, code in cases:
            with self.subTest(case=name):
                out = self.run_labelled(seed + mutation + self.DECIDE_STATE.replace("'DSTATE '", "'BEFORE '") +
                    self.gateway_statement('decide_set_v1', 'result', request, catalog) + self.DECIDE_STATE)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                self.assertEqual(out['BEFORE'], out['DSTATE'])
                self.assertEqual((None, None), (out['DSTATE']['receipts'], out['DSTATE']['audit']))
        plan, seed, catalog = self.cancel_seed(expires_in_hours=-1)
        out = self.run_labelled(seed + self.gateway_statement('decide_set_v1', 'result', self.decide_payload(plan), catalog)
                                + self.DECIDE_STATE)
        self.assertEqual({'ok': False, 'code': 'import_expired'}, out['RESULT'])
        self.assertEqual(['EXPIRED', int(plan['expected_set_revision']), 'pending'], out['DSTATE']['set'])

    def test_read_set_and_receipt_stay_in_scope_and_rebuild_control_receipts(self):
        from kurafolio.ingestion.codec import digest
        plan, seed, catalog = self.cancel_seed()
        cancel = {'operation_id': '52000000-0000-4000-8000-000000000003', 'set_id': plan['set_id'],
                  'expected_set_revision': plan['expected_set_revision']}
        out = self.run_labelled(seed + self.gateway_statement('read_set_v1', 'before', {'set_id': plan['set_id']}, catalog) +
            self.cancel_statement('cancel', cancel, catalog) +
            "DO $r$ BEGIN PERFORM pg_catalog.set_config('test.rid',(SELECT id::text FROM wl_ingestion.receipts),true); END $r$;" +
            "SELECT 'RID '||pg_catalog.jsonb_build_object('id',pg_catalog.current_setting('test.rid'))::text;" +
            self.gateway_statement('read_set_v1', 'missing', {'set_id': '20000000-0000-4000-8000-0000000000ff'}, catalog) +
            self.gateway_statement('read_set_v1', 'bad', {'set_id': plan['set_id'], 'x': 1}, catalog) +
            self.gateway_statement('read_receipt_v1', 'nomatch', {'receipt_id': '20000000-0000-4000-8000-0000000000ff'}, catalog) +
            self.gateway_statement('read_set_v1', 'revoked', {'set_id': plan['set_id']}, catalog,
                                   session='0' * 64))
        before = out['BEFORE']
        self.assertTrue(before['ok'], before)
        self.assertEqual(('READY', plan['expected_set_revision'], plan['preview_id'], None),
                         (before['value']['state'], before['value']['revision'], before['value']['preview_id'],
                          before['value']['receipt_id']))
        self.assertEqual({'ok': False, 'code': 'not_found'}, out['MISSING'])
        self.assertEqual({'ok': False, 'code': 'import_invalid'}, out['BAD'])
        self.assertEqual({'ok': False, 'code': 'not_found'}, out['NOMATCH'])
        self.assertFalse(out['REVOKED']['ok'])
        rid = out['RID']['id']
        out = self.run_labelled(seed + self.cancel_statement('cancel', cancel, catalog) +
            self.gateway_statement('read_receipt_v1', 'receipt', {'receipt_id': '__RID__'}, catalog).replace(
                "'{\"receipt_id\": \"__RID__\"}'::jsonb",
                "pg_catalog.jsonb_build_object('receipt_id',(SELECT id::text FROM wl_ingestion.receipts))"))
        receipt = out['RECEIPT']
        self.assertTrue(receipt['ok'], receipt)
        value = receipt['value']
        self.assertEqual(('CANCEL', cancel['operation_id'], None, None, True, '0', self.INCARNATION),
                         (value['kind'], value['operation_id'], value['preview_id'], value['plan_digest'],
                          value['no_change'], value['new_facts'], value['origin_incarnation']))
        self.assertEqual(['accepted_generation', 'created_at', 'duplicates', 'historical_facts', 'id', 'kind',
                          'mapping_generation', 'new_facts', 'no_change', 'operation_id', 'origin_incarnation',
                          'origin_restore_epoch', 'plan_digest', 'preview_id'], sorted(value))
        self.assertTrue(rid)
        # An ACCEPT receipt is read back exactly as stored.
        confirm = {'operation_id': '52000000-0000-4000-8000-000000000004', 'preview_id': plan['preview_id'],
                   'preview_digest': digest(plan)}
        out = self.run_labelled(seed + self.accept_statement('confirm', confirm, catalog) +
            self.gateway_statement('read_receipt_v1', 'receipt', {'receipt_id': '__RID__'}, catalog).replace(
                "'{\"receipt_id\": \"__RID__\"}'::jsonb",
                "pg_catalog.jsonb_build_object('receipt_id',(SELECT id::text FROM wl_ingestion.receipts))"))
        self.assertEqual(out['CONFIRM'], out['RECEIPT'])

    def test_decide_and_reads_are_not_public(self):
        self.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE "
                 "rolname='wl007_synthetic_guard_reader') THEN CREATE ROLE wl007_synthetic_guard_reader NOLOGIN; "
                 'END IF; END $role$;')
        for name in ('decide_set_v1', 'read_set_v1', 'read_receipt_v1'):
            with self.subTest(function=name):
                self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_guard_reader',"
                    "'wl_ingestion." + name + "(text,uuid,bigint,jsonb,text,jsonb)','EXECUTE')"))

    # Paged reads: each call stores its result, and the next call reads the
    # previous `next` payload as its cursor inside the same transaction. The
    # API checks the MAC before this point; SQL rechecks every binding.
    def gateway_expression(self, function, label, payload_sql, catalog_digest, *, session=None):
        from kurafolio.persistence import identity_schema
        return ("DO $paged$ DECLARE st wl_pg.instance_state%ROWTYPE;r jsonb; BEGIN "
            "SELECT * INTO st FROM wl_pg.instance_state WHERE id=1; r:=wl_ingestion." + function + "('" +
            (session or self.SESSION) + "','" + ORACLE['plan-first-use.json']['tenant_id'] + "',1," +
            identity_schema.realm() + ",'" + catalog_digest + "'," + payload_sql + "); "
            "PERFORM pg_catalog.set_config('test." + label + "',r::text,true); END $paged$;"
            "SELECT '" + label.upper() + " '||pg_catalog.current_setting('test." + label + "');")

    @staticmethod
    def previous(label, path='{value,next}'):
        return "(pg_catalog.current_setting('test." + label + "')::jsonb#>'" + path + "')"

    def extra_sets(self, plan, count):
        rows = []
        for index in range(count):
            set_id = 'a7000000-0000-4000-8000-0000000000' + format(index, '02d')
            row = self.set_row(set_id, 'CANCELLED' if index % 2 else 'READY', revision=2, members=1,
                               created="now()-interval '" + str(index + 1) + " minutes'")
            rows.append(row.replace("'" + self.T + "'", "'" + plan['tenant_id'] + "'").replace(
                "'" + self.P + "'", "'" + plan['portfolio_id'] + "'"))
        return 'SET LOCAL session_replication_role=replica;' + ''.join(rows) + 'SET LOCAL session_replication_role=origin;'

    def test_read_sets_pages_newest_first_and_rechecks_every_cursor_binding(self):
        plan, seed, catalog = self.accept_seed()
        seed += self.extra_sets(plan, 4)
        def page(label, cursor='NULL::jsonb', limit='2', state='null'):
            return self.gateway_expression('read_sets_v1', label, "pg_catalog.jsonb_build_object('cursor'," + cursor +
                ",'limit','" + limit + "','state'," + state + "::jsonb)", catalog)
        def altered(field, value):
            return "pg_catalog.jsonb_set(" + self.previous('p1') + ",'{" + field + "}','" + value + "'::jsonb)"
        out = self.run_labelled(seed + page('p1') + page('p2', self.previous('p1')) + page('p3', self.previous('p2')) +
            page('all', limit='50') + page('cancelled', state="'\"CANCELLED\"'") +
            page('mixed', self.previous('p1'), state="'\"CANCELLED\"'") +
            page('realm', altered('realm_digest', '"' + '0' * 64 + '"')) +
            page('user', altered('user_id', '"10000000-0000-4000-8000-0000000000ff"')) +
            page('resource', altered('resource_id', '"10000000-0000-4000-8000-0000000000ff"')) +
            page('expired', altered('expires_at', '"2020-01-01T00:00:00.000000+00:00"')) +
            page('beyond', altered('expires_at', '"2999-01-01T00:00:00.000000+00:00"')) +
            page('position', altered('after_key', '"1:x"')) +
            page('zero', limit='0') + page('big', limit='51') +
            self.gateway_expression('read_sets_v1', 'extra', "'{\"cursor\":null,\"limit\":\"2\",\"state\":null,\"x\":1}'::jsonb", catalog))
        ids = [x['id'] for label in ('P1', 'P2', 'P3') for x in out[label]['value']['items']]
        everything = [x['id'] for x in out['ALL']['value']['items']]
        self.assertEqual(5, len(everything))
        self.assertEqual(everything, ids)
        self.assertEqual([2, 2, 1], [len(out[x]['value']['items']) for x in ('P1', 'P2', 'P3')])
        self.assertIsNone(out['P3']['value']['next'])
        self.assertIsNone(out['ALL']['value']['next'])
        nxt = out['P1']['value']['next']
        self.assertEqual((1, None, None, None, None), (nxt['version'], nxt['resource_id'], nxt['resource_revision'],
                                                      nxt['review_digest'], nxt['filter']))
        self.assertEqual(plan['tenant_id'], nxt['user_id'])
        self.assertEqual({'CANCELLED'}, {x['state'] for x in out['CANCELLED']['value']['items']})
        self.assertEqual(2, len(out['CANCELLED']['value']['items']))
        for label, code in (('MIXED', 'import_invalid'), ('REALM', 'import_invalid'), ('USER', 'import_invalid'),
                            ('RESOURCE', 'import_invalid'), ('EXPIRED', 'import_stale'), ('BEYOND', 'import_stale'),
                            ('POSITION', 'import_invalid'), ('ZERO', 'import_invalid'), ('BIG', 'import_invalid'),
                            ('EXTRA', 'import_invalid')):
            with self.subTest(case=label):
                self.assertEqual({'ok': False, 'code': code}, out[label])

    def review_seed(self, plan):
        from copy import deepcopy
        from kurafolio.ingestion.codec import encode
        document = deepcopy(ORACLE['mixed-set-review.json'])
        document.update(id=plan['preview_id'], set_id=plan['set_id'])
        raw = encode(document)
        return document, ("UPDATE wl_ingestion.previews SET review_bytes=decode('" + raw.hex() + "','hex'),review_digest='" +
                          hashlib.sha256(raw).hexdigest() + "';")

    def test_read_preview_pages_whole_review_rows_bound_to_the_exact_document(self):
        plan, seed, catalog = self.accept_seed()
        document, review = self.review_seed(plan)
        seed += review
        def page(label, cursor='NULL::jsonb', preview=None, limit='10'):
            return self.gateway_expression('read_preview_v1', label, "pg_catalog.jsonb_build_object('cursor'," + cursor +
                ",'limit','" + limit + "','preview_id','" + (preview or plan['preview_id']) + "')", catalog)
        out = self.run_labelled(seed + page('p1') + page('p2', self.previous('p1')) + page('p3', self.previous('p2')) +
            page('p4', self.previous('p3')) +
            page('digest', "pg_catalog.jsonb_set(" + self.previous('p1') + ",'{review_digest}','\"" + '0' * 64 + "\"'::jsonb)") +
            page('revision', "pg_catalog.jsonb_set(" + self.previous('p1') + ",'{resource_revision}','\"99\"'::jsonb)") +
            page('setcursor', "pg_catalog.jsonb_set(pg_catalog.jsonb_set(pg_catalog.jsonb_set(" + self.previous('p1') +
                 ",'{resource_id}','null'),'{resource_revision}','null'),'{review_digest}','null')") +
            page('missing', preview='20000000-0000-4000-8000-0000000000ff') +
            "SET LOCAL session_replication_role=replica;UPDATE wl_ingestion.sets SET state='RECONCILING',revision=revision+1;"
            "SET LOCAL session_replication_role=origin;" + page('stale') + page('oldcursor', self.previous('p1')))
        rows = [r for label in ('P1', 'P2', 'P3', 'P4') for r in out[label]['value']['page']['rows']]
        self.assertEqual(document['content']['rows'], rows)
        self.assertEqual([10, 10, 10, 5], [len(out[x]['value']['page']['rows']) for x in ('P1', 'P2', 'P3', 'P4')])
        self.assertIsNone(out['P4']['value']['next'])
        first = out['P1']['value']['page']
        self.assertEqual((plan['preview_id'], plan['set_id'], plan['expected_set_revision'], 'READY', True,
                          document['content_digest']),
                         (first['id'], first['set_id'], first['set_revision'], first['state'], first['can_confirm'],
                          first['content_digest']))
        self.assertEqual(sorted(['accepted_generation', 'can_confirm', 'content_digest', 'control_generation', 'expires_at',
            'id', 'mapping_generation', 'preview_digest', 'review_digest', 'rows', 'set_id', 'set_revision', 'state']),
            sorted(first))
        cursor = out['P1']['value']['next']
        self.assertEqual((plan['preview_id'], plan['expected_set_revision'], '10', None),
                         (cursor['resource_id'], cursor['resource_revision'], cursor['after_key'], cursor['filter']))
        self.assertLessEqual(cursor['expires_at'][:19], plan['expires_at']['token'][:19])
        for label, code in (('DIGEST', 'import_stale'), ('REVISION', 'import_stale'), ('SETCURSOR', 'import_stale'),
                            ('MISSING', 'not_found')):
            with self.subTest(case=label):
                self.assertEqual({'ok': False, 'code': code}, out[label])
        # A later set revision leaves the old preview readable but not confirmable.
        self.assertFalse(out['STALE']['value']['page']['can_confirm'])
        self.assertEqual('RECONCILING', out['STALE']['value']['page']['state'])
        self.assertTrue(out['OLDCURSOR']['ok'])

    def test_paged_reads_are_not_public(self):
        self.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE "
                 "rolname='wl007_synthetic_guard_reader') THEN CREATE ROLE wl007_synthetic_guard_reader NOLOGIN; "
                 'END IF; END $role$;')
        for name in ('read_sets_v1', 'read_preview_v1'):
            with self.subTest(function=name):
                self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_guard_reader',"
                    "'wl_ingestion." + name + "(text,uuid,bigint,jsonb,text,jsonb)','EXECUTE')"))

    # The worker guard maps the actual login (postgres in this disposable
    # container) to an enabled registry row; IDs and epochs are assertions only.
    WORKER_TOKEN = 'ab' * 32

    def worker_guard_statement(self, label, *, worker=None, token=None, epoch='1', realm=None, extra=''):
        realm_sql = ("pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(" + __import__(
            'kurafolio.persistence.identity_schema', fromlist=['realm']).realm() + ")),'hex')") if realm is None \
            else "'" + realm + "'"
        return ("DO $worker$ DECLARE st wl_pg.instance_state%ROWTYPE;r jsonb; BEGIN "
            "SELECT * INTO st FROM wl_pg.instance_state WHERE id=1; r:=wl_ingestion._guard_worker_v1('" +
            (worker or self.WORKER) + "','" + (token or self.WORKER_TOKEN) + "',pg_catalog.jsonb_build_object("
            "'realm_digest'," + realm_sql + ",'credential_epoch','" + epoch + "')" + extra + "); "
            "PERFORM pg_catalog.set_config('test." + label + "',r::text,true); END $worker$;"
            "SELECT '" + label.upper() + " '||pg_catalog.current_setting('test." + label + "');")

    def test_worker_guard_maps_the_actual_login_to_an_enabled_registry_row(self):
        plan, seed, catalog = self.accept_seed()
        seed += self.row('workers', {'id': self.WORKER, 'login_role': 'postgres', 'peer_identity': 'peer-a',
                                     'enabled': True, 'credential_epoch': 1})
        seed += self.row('workers', {'id': self.DISABLED, 'login_role': 'wl_worker', 'peer_identity': 'peer-b',
                                     'enabled': True, 'credential_epoch': 1})
        out = self.run_labelled(seed + self.worker_guard_statement('ok') +
            self.worker_guard_statement('unknown', worker='c7000000-0000-4000-8000-0000000000ff') +
            self.worker_guard_statement('otherlogin', worker=self.DISABLED) +
            self.worker_guard_statement('epoch', epoch='2') +
            self.worker_guard_statement('realm', realm='0' * 64) +
            self.worker_guard_statement('token', token='AB' * 32) +
            self.worker_guard_statement('shorttoken', token='ab') +
            "UPDATE wl_ingestion.workers SET enabled=false WHERE id='" + self.WORKER + "';" +
            self.worker_guard_statement('disabled') +
            "UPDATE wl_ingestion.workers SET enabled=true WHERE id='" + self.WORKER + "';" +
            'UPDATE wl_ingestion.instance_state SET ready=false;' + self.worker_guard_statement('notready') +
            'UPDATE wl_ingestion.instance_state SET ready=true;' +
            "UPDATE wl_pg.alembic_version SET version_num='0003_source_lifecycle';" + self.worker_guard_statement('version'))
        value = out['OK']['value']
        self.assertTrue(out['OK']['ok'], out['OK'])
        self.assertEqual((self.WORKER, '1', self.INCARNATION, '0', hashlib.sha256(bytes.fromhex(self.WORKER_TOKEN)).hexdigest()),
                         (value['worker_id'], value['credential_epoch'], value['incarnation'], value['restore_epoch'],
                          value['token_digest']))
        self.assertRegex(value['realm_digest'], '^[0-9a-f]{64}$')
        for label, code in (('UNKNOWN', 'authentication_required'), ('OTHERLOGIN', 'authentication_required'),
                            ('EPOCH', 'credentials_changed'), ('REALM', 'instance_not_ready'),
                            ('TOKEN', 'import_invalid'), ('SHORTTOKEN', 'import_invalid'),
                            ('DISABLED', 'credentials_changed'), ('NOTREADY', 'instance_not_ready'),
                            ('VERSION', 'instance_not_ready')):
            with self.subTest(case=label):
                self.assertEqual({'ok': False, 'code': code}, out[label])

    def test_worker_guard_is_not_public(self):
        self.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE "
                 "rolname='wl007_synthetic_guard_reader') THEN CREATE ROLE wl007_synthetic_guard_reader NOLOGIN; "
                 'END IF; END $role$;')
        self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_guard_reader',"
            "'wl_ingestion._guard_worker_v1(uuid,text,jsonb)','EXECUTE')"))

    # Independent review of the PR #29 functions (WL-P0-007H). These are
    # reviewer-written negative cases that the developer tests did not cover.
    FOREIGN_T, FOREIGN_P = '30000000-0000-4000-8000-0000000000f1', '30000000-0000-4000-8000-0000000000f2'
    FOREIGN_SET = 'a8000000-0000-4000-8000-000000000001'
    FOREIGN_RECEIPT = 'a8000000-0000-4000-8000-000000000002'

    def foreign_rows(self):
        """One set and one control receipt in another tenant and portfolio."""
        e = self.Expression
        scoped = self.set_row(self.FOREIGN_SET, 'CANCELLED', revision=2, members=1) + self.row('receipts', {
            'tenant_id': self.T, 'portfolio_id': self.P, 'id': self.FOREIGN_RECEIPT, 'incarnation': self.INCARNATION,
            'restore_epoch': 0, 'operation_id': 'a8000000-0000-4000-8000-000000000003', 'operation_kind': 'CANCEL',
            'request_digest': 'a' * 64, 'preview_id': None, 'accepted_plan_id': None, 'plan_digest': None,
            'result_bytes': b'{}', 'created_at': e('now()')})
        scoped = scoped.replace("'" + self.T + "'", "'" + self.FOREIGN_T + "'").replace(
            "'" + self.P + "'", "'" + self.FOREIGN_P + "'")
        return 'SET LOCAL session_replication_role=replica;' + scoped + 'SET LOCAL session_replication_role=origin;'

    def internal_error(self, function, payload_sql, catalog):
        """A gateway call that must fail closed with internal_error, not return data."""
        from kurafolio.persistence import identity_schema
        return ("DO $failclosed$ DECLARE st wl_pg.instance_state%ROWTYPE; BEGIN "
            "SELECT * INTO st FROM wl_pg.instance_state WHERE id=1; BEGIN PERFORM wl_ingestion." + function + "('" +
            self.SESSION + "','" + ORACLE['plan-first-use.json']['tenant_id'] + "',1," + identity_schema.realm() +
            ",'" + catalog + "'," + payload_sql + "); RAISE EXCEPTION 'fail_closed_missing'; "
            "EXCEPTION WHEN SQLSTATE 'XX000' THEN IF SQLERRM<>'internal_error' THEN RAISE; END IF; END; END $failclosed$;")

    def test_review_reads_and_purge_never_reach_another_scope(self):
        # read_set_v1, read_sets_v1, read_receipt_v1, read_preview_v1 and _purge_v1.
        plan, seed, catalog = self.accept_seed()
        self.assertEqual((self.T, self.P), (plan['tenant_id'], plan['portfolio_id']))
        seed += self.foreign_rows()
        out = self.run_labelled(seed +
            self.gateway_statement('read_set_v1', 'set', {'set_id': self.FOREIGN_SET}, catalog) +
            self.gateway_expression('read_sets_v1', 'list', "'{\"cursor\":null,\"limit\":\"50\",\"state\":null}'::jsonb",
                                    catalog) +
            self.gateway_expression('read_sets_v1', 'cancelled',
                                    "'{\"cursor\":null,\"limit\":\"50\",\"state\":\"CANCELLED\"}'::jsonb", catalog) +
            self.gateway_statement('read_receipt_v1', 'receipt', {'receipt_id': self.FOREIGN_RECEIPT}, catalog) +
            # The same preview moved to another scope is no longer the caller's.
            "SET LOCAL session_replication_role=replica;UPDATE wl_ingestion.previews SET tenant_id='" + self.FOREIGN_T +
            "',portfolio_id='" + self.FOREIGN_P + "';SET LOCAL session_replication_role=origin;" +
            self.gateway_expression('read_preview_v1', 'preview', "pg_catalog.jsonb_build_object('cursor',NULL::jsonb,"
                                    "'limit','10','preview_id','" + plan['preview_id'] + "')", catalog) +
            self.rejects("SELECT wl_ingestion._purge_v1('" + self.T + "','" + self.P + "','" + self.FOREIGN_SET + "')",
                         'not_found') +
            "SELECT 'FOREIGN '||pg_catalog.jsonb_build_object('cleanup',(SELECT cleanup_state FROM wl_ingestion.sets "
            "WHERE id='" + self.FOREIGN_SET + "'))::text;")
        self.assertEqual({'ok': False, 'code': 'not_found'}, out['SET'])
        self.assertEqual([plan['set_id']], [x['id'] for x in out['LIST']['value']['items']])
        self.assertEqual([], out['CANCELLED']['value']['items'])
        self.assertEqual({'ok': False, 'code': 'not_found'}, out['RECEIPT'])
        self.assertEqual({'ok': False, 'code': 'not_found'}, out['PREVIEW'])
        self.assertEqual({'cleanup': 'not_needed'}, out['FOREIGN'])

    def test_review_cancel_and_decide_share_one_operation_namespace(self):
        # cancel_set_v1 and decide_set_v1: one operation ID cannot name two kinds,
        # and the replay check answers before the terminal-state check.
        plan, seed, catalog = self.cancel_seed()
        shared = '53000000-0000-4000-8000-0000000000a1'
        cancel = {'operation_id': shared, 'set_id': plan['set_id'],
                  'expected_set_revision': str(int(plan['expected_set_revision']) + 1)}
        out = self.run_labelled(seed + self.gateway_statement('decide_set_v1', 'decide',
            self.decide_payload(plan, shared), catalog) + self.CANCEL_STATE.replace("'CSTATE '", "'BEFORE '") +
            self.cancel_statement('cancel', cancel, catalog) + self.CANCEL_STATE)
        self.assertTrue(out['DECIDE']['ok'], out['DECIDE'])
        self.assertEqual({'ok': False, 'code': 'import_operation_conflict'}, out['CANCEL'])
        self.assertEqual(out['BEFORE'], out['CSTATE'])
        plan, seed, catalog = self.cancel_seed()
        cancel = {'operation_id': shared, 'set_id': plan['set_id'], 'expected_set_revision': plan['expected_set_revision']}
        out = self.run_labelled(seed + self.cancel_statement('cancel', cancel, catalog) +
            self.gateway_statement('decide_set_v1', 'decide', self.decide_payload(plan, shared), catalog) + self.CANCEL_STATE)
        self.assertTrue(out['CANCEL']['ok'], out['CANCEL'])
        self.assertEqual({'ok': False, 'code': 'import_operation_conflict'}, out['DECIDE'])
        self.assertEqual((['CANCEL'], ['CANCELLED']), (out['CSTATE']['receipts'], out['CSTATE']['audit']))

    def test_review_decide_refuses_sets_that_are_not_yet_reviewed(self):
        # decide_set_v1 before normalization finishes writes nothing.
        plan, seed, catalog = self.cancel_seed()
        for state in ('RECEIVING', 'NORMALIZING'):
            with self.subTest(state=state):
                mutation = ("SET LOCAL session_replication_role=replica;UPDATE wl_ingestion.sets SET state='" + state +
                            "';SET LOCAL session_replication_role=origin;")
                out = self.run_labelled(seed + mutation + self.DECIDE_STATE.replace("'DSTATE '", "'BEFORE '") +
                    self.gateway_statement('decide_set_v1', 'result', self.decide_payload(plan), catalog) +
                    self.DECIDE_STATE)
                self.assertEqual({'ok': False, 'code': 'import_stale'}, out['RESULT'])
                self.assertEqual(out['BEFORE'], out['DSTATE'])

    def test_review_reads_fail_closed_on_altered_stored_bytes(self):
        # read_receipt_v1 and read_preview_v1 never return bytes that fail their own checks.
        plan, seed, catalog = self.cancel_seed()
        cancel = {'operation_id': '53000000-0000-4000-8000-0000000000a2', 'set_id': plan['set_id'],
                  'expected_set_revision': plan['expected_set_revision']}
        receipt = "pg_catalog.jsonb_build_object('receipt_id',(SELECT id::text FROM wl_ingestion.receipts))"
        replica = 'SET LOCAL session_replication_role=replica;'
        origin = 'SET LOCAL session_replication_role=origin;'
        # Table checks already forbid these bytes; dropping a check inside the
        # rolled-back transaction shows the read rechecks instead of trusting it.
        # The check is dropped before any deferred write is pending.
        unchecked = 'ALTER TABLE wl_ingestion.receipts DROP CONSTRAINT receipts_values_ck;'
        for name, prepare, mutation in (
                ('noncanonical_result', unchecked, "UPDATE wl_ingestion.receipts SET result_bytes=convert_to('{ }','UTF8');"),
                ('missing_audit', '', 'DELETE FROM wl_ingestion.audit;')):
            with self.subTest(case=name):
                self.sql('BEGIN;' + prepare + seed + self.cancel_statement('cancel', cancel, catalog) + replica + mutation + origin +
                         self.internal_error('read_receipt_v1', receipt, catalog) + 'ROLLBACK;')
        document, review = self.review_seed(plan)
        page = "pg_catalog.jsonb_build_object('cursor',NULL::jsonb,'limit','10','preview_id','" + plan['preview_id'] + "')"
        for name, prepare, mutation in (
                ('review_digest', 'ALTER TABLE wl_ingestion.previews DROP CONSTRAINT previews_values_ck;',
                 "UPDATE wl_ingestion.previews SET review_digest='" + '0' * 64 + "';"),
                ('other_document_id', '', "UPDATE wl_ingestion.previews SET review_bytes=convert_to(replace(convert_from("
                 "review_bytes,'UTF8'),'" + plan['preview_id'] + "','" + self.FOREIGN_SET + "'),'UTF8'),review_digest="
                 "encode(sha256(convert_to(replace(convert_from(review_bytes,'UTF8'),'" + plan['preview_id'] + "','" +
                 self.FOREIGN_SET + "'),'UTF8')),'hex');")):
            with self.subTest(case=name):
                self.sql('BEGIN;' + prepare + seed + replica + review + mutation + origin +
                         self.internal_error('read_preview_v1', page, catalog) + 'ROLLBACK;')

    def test_review_paged_cursors_reject_other_versions_shapes_and_positions(self):
        # read_sets_v1 and read_preview_v1 cursor bindings beyond the developer cases.
        plan, seed, catalog = self.accept_seed()
        document, review = self.review_seed(plan)
        seed += self.extra_sets(plan, 4) + review
        def sets(label, cursor):
            return self.gateway_expression('read_sets_v1', label, "pg_catalog.jsonb_build_object('cursor'," + cursor +
                                           ",'limit','2','state',NULL::jsonb)", catalog)
        def preview(label, cursor):
            return self.gateway_expression('read_preview_v1', label, "pg_catalog.jsonb_build_object('cursor'," + cursor +
                                           ",'limit','10','preview_id','" + plan['preview_id'] + "')", catalog)
        def altered(label, field, value):
            return "pg_catalog.jsonb_set(" + self.previous(label) + ",'{" + field + "}','" + value + "'::jsonb)"
        out = self.run_labelled(seed + sets('s1', 'NULL::jsonb') + preview('v1', 'NULL::jsonb') +
            sets('version', altered('s1', 'version', '2')) +
            sets('extra', "(" + self.previous('s1') + "||'{\"x\":1}'::jsonb)") +
            sets('missing', "(" + self.previous('s1') + "-'filter')") +
            sets('scalar', "'\"opaque\"'::jsonb") +
            sets('portfolio', altered('s1', 'portfolio_id', '"' + self.P2 + '"')) +
            sets('previewcursor', self.previous('v1')) +
            preview('setcursor', self.previous('s1')) +
            preview('beyond', altered('v1', 'after_key', '"999"')) +
            preview('zero', altered('v1', 'after_key', '"0"')))
        self.assertTrue(out['S1']['ok'] and out['V1']['ok'], (out['S1'], out['V1']))
        for label, code in (('VERSION', 'import_invalid'), ('EXTRA', 'import_invalid'), ('MISSING', 'import_invalid'),
                            ('SCALAR', 'import_invalid'), ('PORTFOLIO', 'import_invalid'),
                            ('PREVIEWCURSOR', 'import_invalid'), ('SETCURSOR', 'import_stale'),
                            ('BEYOND', 'import_stale'), ('ZERO', 'import_stale')):
            with self.subTest(case=label):
                self.assertEqual({'ok': False, 'code': code}, out[label])

    def test_review_read_preview_serves_an_empty_review_document(self):
        # read_preview_v1: ReviewContent.rows has no minimum, so an empty review is a
        # valid document. Its first page is empty (WL-P0-007I); a cursor past the
        # end is still stale.
        from kurafolio.ingestion.codec import encode
        from kurafolio.persistence import identity_schema
        plan, seed, catalog = self.accept_seed()
        document, _ = self.review_seed(plan)
        document['content']['rows'] = []
        raw = encode(document)
        seed += ("UPDATE wl_ingestion.previews SET review_bytes=decode('" + raw.hex() + "','hex'),review_digest='" +
                 hashlib.sha256(raw).hexdigest() + "';")
        # Every binding matches except the position, which no empty review can reach.
        cursor = ("pg_catalog.jsonb_build_object('version',1,'user_id','" + plan['tenant_id'] + "','portfolio_id','" +
                  plan['portfolio_id'] + "','realm_digest',pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(" +
                  identity_schema.realm() + ")),'hex'),'resource_id','" + plan['preview_id'] + "','resource_revision','" +
                  plan['expected_set_revision'] + "','review_digest','" + hashlib.sha256(raw).hexdigest() +
                  "','filter',NULL::text,'after_key','1','expires_at',pg_catalog.to_char((pg_catalog.clock_timestamp()+"
                  "interval '60 seconds') AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US')||'+00:00')")
        def page(label, cursor_sql):
            return self.gateway_expression('read_preview_v1', label, "pg_catalog.jsonb_build_object('cursor'," +
                cursor_sql + ",'limit','10','preview_id','" + plan['preview_id'] + "')", catalog)
        out = self.run_labelled(seed + page('page', 'NULL::jsonb') + page('beyond', cursor))
        self.assertTrue(out['PAGE']['ok'], out['PAGE'])
        self.assertEqual(([], None), (out['PAGE']['value']['page']['rows'], out['PAGE']['value']['next']))
        self.assertEqual({'ok': False, 'code': 'import_stale'}, out['BEYOND'])

    def test_review_quota_refuses_releases_beyond_what_is_held(self):
        # _quota_v1: a release larger than the reservation, or in another scope,
        # fails without changing any counter.
        self.guarded('', [
            self.quota_call('storage', 1, 1000), self.quota_call('raw', 1),
            self.rejects(self.quota_call('storage', -1, -2000)),
            self.rejects(self.quota_call('storage', 0, -1001)),
            self.rejects(self.quota_call('storage', -1, -1000, portfolio=self.P2)),
            self.rejects(self.quota_call('raw', -1, portfolio=self.P2)),
            self.rejects(self.quota_call('RAW', 1)),
            self.rejects("SELECT wl_ingestion._quota_v1('" + self.T + "','00000000-0000-0000-0000-000000000000','raw',1,0)"),
            self.quota_state(self.P + '/raw:1:1:0:0,' + self.P + '/storage:0:0:1:1000'),
            "DO $test$ BEGIN IF (SELECT pg_catalog.string_agg(bucket||':'||used_count||':'||lease_count||':'||"
            "outstanding_sets||':'||reserved_bytes,',' ORDER BY bucket) FROM wl_ingestion.instance_budgets)<>"
            "'raw:1:1:0:0,storage:0:0:1:1000' THEN RAISE EXCEPTION 'unexpected_instance_budgets'; END IF; END $test$;"])

    def test_review_worker_guard_rejects_malformed_requests(self):
        # _guard_worker_v1: request shape is checked before any registry lookup.
        plan, seed, catalog = self.accept_seed()
        seed += self.row('workers', {'id': self.WORKER, 'login_role': 'postgres', 'peer_identity': 'peer-a',
                                     'enabled': True, 'credential_epoch': 1})
        out = self.run_labelled(seed +
            self.worker_guard_statement('noepoch', extra="-'credential_epoch'") +
            self.worker_guard_statement('numberepoch', extra="||'{\"credential_epoch\":1}'::jsonb") +
            self.worker_guard_statement('zeroepoch', epoch='0') +
            self.worker_guard_statement('leadingzero', epoch='01') +
            self.worker_guard_statement('norealm', extra="-'realm_digest'") +
            self.worker_guard_statement('upperrealm', realm='A' * 64) +
            self.worker_guard_statement('zeroworker', worker='00000000-0000-0000-0000-000000000000'))
        for label in ('NOEPOCH', 'NUMBEREPOCH', 'ZEROEPOCH', 'LEADINGZERO', 'NOREALM', 'UPPERREALM', 'ZEROWORKER'):
            with self.subTest(case=label):
                self.assertEqual({'ok': False, 'code': 'import_invalid'}, out[label])

    # create_set_v1 builds each member context in the database (owner Option A).
    FORMAT = 'synthetic-csv-v1'
    IMAGE_DIGEST = '83125eb1979a26b9249616951138ab5afc27bd21a215bb5b4612b235acd3c34f'

    def create_seed(self, *, projection='parser2-minimal-v1', profiles=1, formats=None, quota_sets=0, availability='ACTIVE'):
        from kurafolio.ingestion.codec import encode
        plan, seed, catalog = self.accept_seed(availability=availability)
        pin = plan['pinned_sources'][0]
        profile = {'version': 1, 'installation_id': pin['installation_id'], 'image_digest': self.IMAGE_DIGEST,
                   'distribution': 'synthetic-qa', 'entry_point': 'synthetic_qa.discovery:entry', 'wrapper_sha256': 'c' * 64,
                   'projection': projection, 'format_versions': formats or [self.FORMAT],
                   'profile_digest': pin['wrapper_profile_digest'], 'identity_policy': 'provider_scoped_stable'}
        wrappers = encode([profile] * profiles)
        seed += ("UPDATE wl_ingestion.instance_state SET wrapper_catalog_bytes=decode('" + wrappers.hex() +
                 "','hex'),wrapper_catalog_digest='" + hashlib.sha256(wrappers).hexdigest() + "';")
        if quota_sets:
            for table, scope in (('instance_budgets', {}), ('quotas', {'tenant_id': plan['tenant_id'],
                                                                      'portfolio_id': plan['portfolio_id']})):
                seed += self.row(table, {**scope, 'bucket': 'storage', 'window_start': self.Expression('now()'),
                    'used_count': 0, 'reserved_bytes': quota_sets * schema.SET_RESERVATION_BYTES, 'lease_count': 0,
                    'outstanding_sets': quota_sets})
        return plan, pin, seed + self.TRANSITION_TRIGGERS, catalog

    def create_payload(self, pin, operation='53000000-0000-4000-8000-000000000001', count=1, **member):
        selection = {'connection_id': pin['connection_id'], 'installation_id': pin['installation_id'],
                     'format_version': self.FORMAT, 'declared_bytes': None, **member}
        return {'operation_id': operation, 'members': [selection] * count}

    CREATE_STATE = ("SELECT 'CREATED '||pg_catalog.jsonb_build_object('sets',(SELECT count(*) FROM wl_ingestion.sets),"
        "'members',(SELECT count(*) FROM wl_ingestion.members),'receipts',(SELECT pg_catalog.jsonb_agg(operation_kind ORDER BY "
        "operation_kind) FROM wl_ingestion.receipts),'audit',(SELECT pg_catalog.jsonb_agg(action ORDER BY action) FROM "
        "wl_ingestion.audit),'storage',(SELECT pg_catalog.jsonb_build_array(outstanding_sets,reserved_bytes) FROM "
        "wl_ingestion.quotas WHERE bucket='storage'),'instance',(SELECT pg_catalog.jsonb_build_array(outstanding_sets,"
        "reserved_bytes) FROM wl_ingestion.instance_budgets WHERE bucket='storage'))::text;")

    MEMBER_CONTEXT = ("SELECT 'CONTEXT '||pg_catalog.jsonb_build_object('context',pg_catalog.convert_from(m.context_bytes,"
        "'UTF8')::jsonb,'digest_ok',m.context_digest=pg_catalog.encode(pg_catalog.sha256(m.context_bytes),'hex'),"
        "'canonical',m.context_bytes=wl_ingestion._canonical_v1(pg_catalog.convert_from(m.context_bytes,'UTF8')::jsonb),"
        "'id',m.id::text,'pins',pg_catalog.jsonb_build_array(m.connection_generation,m.enablement_generation,"
        "m.availability_generation,m.wrapper_profile_digest,m.fence,m.state),'realm',s.realm_digest,'expiry',"
        "EXTRACT(EPOCH FROM s.expires_at-s.created_at)::text,'reserved',s.reserved_bytes)::text "
        "FROM wl_ingestion.members m JOIN wl_ingestion.sets s ON s.id=m.set_id WHERE s.state='RECEIVING' ORDER BY m.ordinal LIMIT 1;")

    def test_create_reserves_once_pins_sources_and_builds_the_parser_context(self):
        from kurafolio.persistence import identity_schema
        plan, pin, seed, catalog = self.create_seed()
        payload = self.create_payload(pin)
        realm = ("DO $realm$ DECLARE st wl_pg.instance_state%ROWTYPE; BEGIN SELECT * INTO st FROM wl_pg.instance_state "
                 "WHERE id=1; PERFORM pg_catalog.set_config('test.realm',pg_catalog.jsonb_build_object('d',pg_catalog.encode("
                 "pg_catalog.sha256(wl_ingestion._canonical_v1(" + identity_schema.realm() + ")),'hex'))::text,true); "
                 "END $realm$;SELECT 'REALM '||pg_catalog.current_setting('test.realm');")
        out = self.run_labelled(seed + self.gateway_statement('create_set_v1', 'first', payload, catalog) +
            self.CREATE_STATE + self.MEMBER_CONTEXT + realm +
            self.gateway_statement('create_set_v1', 'again', payload, catalog) +
            self.gateway_statement('create_set_v1', 'reused', self.create_payload(pin, count=2), catalog) +
            self.gateway_statement('create_set_v1', 'second', self.create_payload(
                pin, '53000000-0000-4000-8000-000000000002', count=2, declared_bytes=10485760), catalog) +
            self.CREATE_STATE.replace("'CREATED '", "'AFTER '"))
        first = out['FIRST']
        self.assertTrue(first['ok'], first)
        value = first['value']
        self.assertEqual(('RECEIVING', '1', 'not_needed', None, None), (value['state'], value['revision'],
            value['cleanup_state'], value['preview_id'], value['receipt_id']))
        self.assertEqual([('waiting', 0, pin['connection_id'], self.FORMAT)],
                         [(m['state'], m['ordinal'], m['connection_id'], m['format_version']) for m in value['members']])
        self.assertEqual({'sets': 2, 'members': 2, 'receipts': ['CREATE'], 'audit': ['CREATED'],
                          'storage': [1, schema.SET_RESERVATION_BYTES], 'instance': [1, schema.SET_RESERVATION_BYTES]},
                         out['CREATED'])
        context = out['CONTEXT']
        self.assertTrue(context['digest_ok'] and context['canonical'])
        self.assertEqual([int(pin['connection_generation']), int(pin['enablement_generation']),
                          int(pin['availability_generation']), pin['wrapper_profile_digest'], 1, 'waiting'], context['pins'])
        self.assertEqual((out['REALM']['d'], '86400.000000', schema.SET_RESERVATION_BYTES),
                         (context['realm'], context['expiry'], context['reserved']))
        child = context['context']
        self.assertEqual(sorted(['version', 'job_id', 'member_id', 'fence', 'installation_id', 'wrapper_profile_digest',
                                 'format_version', 'payload_kind', 'parser_context', 'image_digest']), sorted(child))
        self.assertEqual((1, context['id'], '1', 'parser_v2', self.IMAGE_DIGEST, pin['wrapper_profile_digest']),
                         (child['version'], child['member_id'], child['fence'], child['payload_kind'], child['image_digest'],
                          child['wrapper_profile_digest']))
        parser = child['parser_context']
        self.assertEqual((None, None, self.FORMAT, [], []), (parser['account_alias'], parser['source_timezone'],
            parser['format_selection'], parser['revisions'], parser['scope_revisions']))
        self.assertRegex(parser['evidence_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$')
        self.assertNotEqual(child['job_id'], parser['source_reference'])
        self.assertEqual(first, out['AGAIN'])
        self.assertEqual({'ok': False, 'code': 'import_operation_conflict'}, out['REUSED'])
        self.assertTrue(out['SECOND']['ok'], out['SECOND'])
        self.assertEqual([2, 2 * schema.SET_RESERVATION_BYTES], out['AFTER']['storage'])
        self.assertEqual(4, out['AFTER']['members'])

    def test_create_builds_an_ephemeral_native_namespace(self):
        plan, pin, seed, catalog = self.create_seed(projection='domain1-minimal-v1')
        out = self.run_labelled(seed + self.gateway_statement('create_set_v1', 'first', self.create_payload(pin), catalog) +
                                self.MEMBER_CONTEXT)
        self.assertTrue(out['FIRST']['ok'], out['FIRST'])
        child = out['CONTEXT']['context']
        self.assertEqual(('native_discovery_v1', 'synthetic.qa', '1'), (child['payload_kind'], child['provider_id'], child['fence']))
        self.assertEqual(('instant', None, 0), (child['evidence_at']['tag'], child['evidence_at']['zone'],
                                               child['evidence_at']['fractional_digits']))
        real = {plan['tenant_id'], plan['portfolio_id'], pin['connection_id']}
        self.assertFalse(real & set(child['namespace'].values()))
        self.assertEqual(3, len(set(child['namespace'].values())))

    def test_create_rejects_unavailable_sources_full_storage_and_bad_shapes_without_writing(self):
        before = {'sets': 1, 'members': 1, 'receipts': None, 'audit': None, 'storage': None, 'instance': None}
        replica = 'SET LOCAL session_replication_role=replica;'
        origin = 'SET LOCAL session_replication_role=origin;'
        plan, pin, seed, catalog = self.create_seed()
        good = self.create_payload(pin)
        cases = (
            ('disabled_connection', replica + 'UPDATE wl_sources.connection_lifecycle SET enabled=false;' + origin, good, 'source_unavailable'),
            ('disabled_source', replica + 'UPDATE wl_sources.enablements SET enabled=false;' + origin, good, 'source_unavailable'),
            ('unknown_connection', '', self.create_payload(pin, connection_id='40000000-0000-4000-8000-0000000000ff'), 'source_unavailable'),
            ('other_installation', '', self.create_payload(pin, installation_id='e' * 64), 'source_unavailable'),
            ('unreviewed_format', '', self.create_payload(pin, format_version='other-format'), 'source_unavailable'),
            ('five_members', '', self.create_payload(pin, count=5), 'import_invalid'),
            ('extra_field', '', dict(good, note='x'), 'import_invalid'),
            ('member_field', '', self.create_payload(pin, label='x'), 'import_invalid'),
            ('too_large', '', self.create_payload(pin, declared_bytes=10485761), 'import_invalid'),
            ('string_size', '', self.create_payload(pin, declared_bytes='5'), 'import_invalid'),
            ('control_format', '', self.create_payload(pin, format_version='bad\nformat'), 'import_invalid'),
            ('revoked_session', 'UPDATE wl_identity.sessions SET revoked=true;', good, 'session_changed'),
        )
        for name, mutation, request, code in cases:
            with self.subTest(case=name):
                out = self.run_labelled(seed + mutation + self.gateway_statement('create_set_v1', 'result', request, catalog) +
                                        self.CREATE_STATE)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                self.assertEqual(before, out['CREATED'])
        for label, kwargs, code, storage in (('two_profiles', {'profiles': 2}, 'source_unavailable', None),
                                             ('revoked_availability', {'availability': 'REVOKED'}, 'source_unavailable', None),
                                             ('storage_full', {'quota_sets': 8}, 'import_limit', [8, 8 * schema.SET_RESERVATION_BYTES])):
            with self.subTest(case=label):
                plan, pin, seed, catalog = self.create_seed(**kwargs)
                out = self.run_labelled(seed + self.gateway_statement('create_set_v1', 'result', self.create_payload(pin), catalog)
                                        + self.CREATE_STATE)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                self.assertEqual((1, None, storage), (out['CREATED']['sets'], out['CREATED']['receipts'], out['CREATED']['storage']))

    def test_create_then_cancel_and_purge_returns_the_reservation(self):
        plan, pin, seed, catalog = self.create_seed()
        cancel = ("pg_catalog.jsonb_build_object('operation_id','53000000-0000-4000-8000-000000000009','set_id',"
                  "(SELECT id::text FROM wl_ingestion.sets WHERE state='RECEIVING'),'expected_set_revision','1')")
        purge = ("SELECT wl_ingestion._purge_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] +
                 "',(SELECT id FROM wl_ingestion.sets WHERE state='CANCELLED'));")
        out = self.run_labelled(seed + self.gateway_statement('create_set_v1', 'create', self.create_payload(pin), catalog) +
            self.gateway_expression('cancel_set_v1', 'cancel', cancel, catalog) + purge + self.CREATE_STATE)
        self.assertTrue(out['CREATE']['ok'] and out['CANCEL']['ok'], out)
        self.assertEqual('CANCELLED', out['CANCEL']['value']['state'])
        self.assertEqual(([0, 0], [0, 0]), (out['CREATED']['storage'], out['CREATED']['instance']))

    def test_create_is_not_public(self):
        self.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE "
                 "rolname='wl007_synthetic_guard_reader') THEN CREATE ROLE wl007_synthetic_guard_reader NOLOGIN; "
                 'END IF; END $role$;')
        self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_guard_reader',"
            "'wl_ingestion.create_set_v1(text,uuid,bigint,jsonb,text,jsonb)','EXECUTE')"))

    # reserve_member_v1 runs on a set made by create_set_v1 under the real guard.
    NEW_MEMBER = "(SELECT m.id::text FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE x.state='RECEIVING' ORDER BY m.ordinal LIMIT 1)"
    NEW_SET = "(SELECT id::text FROM wl_ingestion.sets WHERE state='RECEIVING' LIMIT 1)"

    def reserve_seed(self, *, workers=1):
        plan, pin, seed, catalog = self.create_seed()
        for index in range(workers):
            seed += self.row('workers', {'id': 'c7100000-0000-4000-8000-00000000000' + str(index), 'login_role': 'wl_worker',
                                         'peer_identity': 'peer-' + str(index), 'enabled': True, 'credential_epoch': 1})
        seed += self.gateway_statement('create_set_v1', 'create', self.create_payload(pin), catalog)
        return plan, pin, seed, catalog

    def reserve_call(self, label, catalog, *, action='reserve', **fields):
        values = {'action': "'" + action + "'", 'set_id': self.NEW_SET, 'member_id': self.NEW_MEMBER}
        if action == 'reserve':
            values['expected_set_revision'] = "'1'"
        else:
            values.update(fence="(SELECT m.fence::text FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id "
                          "WHERE x.state='RECEIVING' ORDER BY m.ordinal LIMIT 1)", raw_sha256="'" + '5' * 64 + "'",
                          raw_bytes='1234', handoff_token_digest="'" + '6' * 64 + "'")
        values.update(fields)
        payload = 'pg_catalog.jsonb_build_object(' + ','.join("'" + k + "'," + v for k, v in values.items()) + ')'
        return self.gateway_expression('reserve_member_v1', label, payload, catalog)

    RESERVE_STATE = ("SELECT 'RSTATE '||pg_catalog.jsonb_build_object('member',(SELECT pg_catalog.jsonb_build_array(m.state,"
        "m.fence,m.raw_digest,m.raw_bytes,m.raw_deadline IS NOT NULL AND m.raw_deadline<=pg_catalog.clock_timestamp()+"
        "interval '120 seconds') FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE x.state='RECEIVING' "
        "LIMIT 1),'leases',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(l.state,l.fence,l.attempt,l.token_digest,"
        "l.expires_at-l.created_at<=interval '120 seconds') ORDER BY l.attempt) FROM wl_ingestion.leases l WHERE "
        "l.work_kind='normalize'),'raw',(SELECT pg_catalog.jsonb_build_array(used_count,lease_count) FROM wl_ingestion.quotas "
        "WHERE bucket='raw'))::text;")

    def test_reserve_then_bind_opens_one_bounded_attempt_and_hands_off_metadata(self):
        plan, pin, seed, catalog = self.reserve_seed()
        context = ("SELECT 'CTX '||pg_catalog.jsonb_build_object('job',pg_catalog.convert_from(m.context_bytes,'UTF8')::jsonb->>'job_id',"
                   "'digest',m.context_digest,'length',pg_catalog.octet_length(m.context_bytes),'realm',x.realm_digest)::text "
                   "FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE x.state='RECEIVING' ORDER BY m.ordinal LIMIT 1;")
        out = self.run_labelled(seed + self.reserve_call('reserve', catalog) + self.RESERVE_STATE +
            self.reserve_call('again', catalog) + self.RESERVE_STATE.replace("'RSTATE '", "'RAGAIN '") +
            self.reserve_call('wrongfence', catalog, action='bind', fence="'2'") +
            self.reserve_call('bind', catalog, action='bind') + self.RESERVE_STATE.replace("'RSTATE '", "'BOUND '") +
            context + self.reserve_call('rebind', catalog, action='bind'))
        self.assertTrue(out['CREATE']['ok'] and out['RESERVE']['ok'], out)
        reserved = out['RESERVE']['value']
        self.assertEqual(('reserve', '1'), (reserved['action'], reserved['fence']))
        self.assertEqual({'member': ['receiving', 1, None, None, True], 'leases': [['offered', 1, 1, None, True]],
                          'raw': [1, 1]}, out['RSTATE'])
        # The live attempt holds the user's only raw slot, so a second reserve is busy
        # before any member check and keeps no extra slot or attempt.
        self.assertEqual({'ok': False, 'code': 'import_busy'}, out['AGAIN'])
        self.assertEqual(out['RSTATE'], out['RAGAIN'])
        self.assertEqual({'ok': False, 'code': 'import_stale'}, out['WRONGFENCE'])
        handoff = out['BIND']['value']
        self.assertTrue(out['BIND']['ok'], out['BIND'])
        self.assertEqual((1, out['CTX']['job'], '1', '5' * 64, 1234, out['CTX']['digest'], out['CTX']['length'], out['CTX']['realm']),
                         (handoff['version'], handoff['job_id'], handoff['fence'], handoff['raw_sha256'], handoff['raw_bytes'],
                          handoff['context_sha256'], handoff['context_bytes'], handoff['realm_digest']))
        self.assertNotIn('handoff_token', handoff)
        self.assertEqual({'member': ['receiving', 1, '5' * 64, 1234, True], 'leases': [['offered', 1, 1, '6' * 64, True]],
                          'raw': [1, 1]}, out['BOUND'])
        self.assertEqual({'ok': False, 'code': 'import_conflict'}, out['REBIND'])

    def test_reupload_advances_the_fence_and_clears_old_raw_fields(self):
        plan, pin, seed, catalog = self.reserve_seed()
        replica = 'SET LOCAL session_replication_role=replica;'
        origin = 'SET LOCAL session_replication_role=origin;'
        out = self.run_labelled(seed + self.reserve_call('reserve', catalog) + self.reserve_call('bind', catalog, action='bind') +
            replica + "UPDATE wl_ingestion.members SET state='reupload_required';UPDATE wl_ingestion.leases SET state='cancelled';" +
            origin + "SELECT wl_ingestion._quota_v1('" + plan['tenant_id'] + "','" + plan['portfolio_id'] + "','raw',-1,0);" +
            self.reserve_call('again', catalog) + self.RESERVE_STATE)
        self.assertTrue(out['AGAIN']['ok'], out['AGAIN'])
        self.assertEqual('2', out['AGAIN']['value']['fence'])
        self.assertEqual({'member': ['receiving', 2, None, None, True],
                          'leases': [['cancelled', 1, 1, '6' * 64, True], ['offered', 2, 2, None, True]], 'raw': [2, 1]},
                         out['RSTATE'])

    def test_reserve_and_bind_refuse_without_keeping_a_slot(self):
        replica = 'SET LOCAL session_replication_role=replica;'
        origin = 'SET LOCAL session_replication_role=origin;'
        plan, pin, seed, catalog = self.reserve_seed()
        cases = (
            ('disabled_connection', replica + 'UPDATE wl_sources.connection_lifecycle SET enabled=false;' + origin, {}, 'source_unavailable'),
            ('enablement_generation', replica + 'UPDATE wl_sources.enablements SET generation=generation+1;' + origin, {}, 'import_stale'),
            ('wrong_revision', '', {'expected_set_revision': "'2'"}, 'import_stale'),
            ('unknown_member', '', {'member_id': "'40000000-0000-4000-8000-0000000000ff'"}, 'not_found'),
            ('expired', replica + "UPDATE wl_ingestion.sets SET created_at=created_at-interval '2 days',expires_at=expires_at-"
             "interval '2 days' WHERE state='RECEIVING';" + origin, {}, 'import_expired'),
            ('extra_field', '', {'note': "'x'"}, 'import_invalid'),
            ('revoked_session', 'UPDATE wl_identity.sessions SET revoked=true;', {}, 'session_changed'),
        )
        for name, mutation, fields, code in cases:
            with self.subTest(case=name):
                out = self.run_labelled(seed + mutation + self.reserve_call('result', catalog, **fields) + self.RESERVE_STATE)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                self.assertIsNone(out['RSTATE']['leases'])
                self.assertIn(out['RSTATE']['raw'], (None, [0, 0]))
        for workers in (0, 2):
            with self.subTest(workers=workers):
                plan, pin, seed, catalog = self.reserve_seed(workers=workers)
                out = self.run_labelled(seed + self.reserve_call('result', catalog) + self.RESERVE_STATE)
                self.assertEqual({'ok': False, 'code': 'import_runner_unavailable'}, out['RESULT'])
                self.assertIn(out['RSTATE']['raw'], (None, [0, 0]))
        plan, pin, seed, catalog = self.reserve_seed()
        late = replica + "UPDATE wl_ingestion.members SET raw_deadline=pg_catalog.clock_timestamp()-interval '1 second';" + origin
        for name, mutation, fields, code in (
                ('late', late, {}, 'import_reupload_required'),
                ('too_big', '', {'raw_bytes': '10485761'}, 'import_invalid'),
                ('string_size', '', {'raw_bytes': "'12'"}, 'import_invalid'),
                ('bad_digest', '', {'raw_sha256': "'XYZ'"}, 'import_invalid')):
            with self.subTest(case=name):
                out = self.run_labelled(seed + self.reserve_call('reserve', catalog) + mutation +
                                        self.reserve_call('result', catalog, action='bind', **fields) + self.RESERVE_STATE)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                self.assertEqual([None, None], out['RSTATE']['member'][2:4])

    def test_reserve_is_not_public(self):
        self.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE "
                 "rolname='wl007_synthetic_guard_reader') THEN CREATE ROLE wl007_synthetic_guard_reader NOLOGIN; "
                 'END IF; END $role$;')
        self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_guard_reader',"
            "'wl_ingestion.reserve_member_v1(text,uuid,bigint,jsonb,text,jsonb)','EXECUTE')"))

    # claim/renew run under the real worker guard; the disposable container's
    # login (postgres) is the registered worker.
    LEASE_MEMBER = ("(SELECT m.id::text FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id "
                    "WHERE x.state='RECEIVING' ORDER BY m.ordinal LIMIT 1)")

    def claim_seed(self, projection='parser2-minimal-v1', count=1):
        plan, pin, seed, catalog = self.create_seed(projection=projection)
        seed += self.row('workers', {'id': self.WORKER, 'login_role': 'postgres', 'peer_identity': 'peer-a',
                                     'enabled': True, 'credential_epoch': 1})
        seed += self.gateway_statement('create_set_v1', 'create', self.create_payload(pin, count=count), catalog)
        seed += self.reserve_call('reserve', catalog)
        seed += self.reserve_call('bind', catalog, action='bind', handoff_token_digest="'" + hashlib.sha256(
            bytes.fromhex(self.WORKER_TOKEN)).hexdigest() + "'")
        return plan, pin, seed, catalog

    def lease_call(self, function, label, *, token=None, data='NULL', drop=(), prelude='', **fields):
        from kurafolio.persistence import identity_schema
        values = {'version': '1', 'work_kind': "'normalize'",
                  'realm_digest': "pg_catalog.encode(pg_catalog.sha256(wl_ingestion._canonical_v1(" +
                                  identity_schema.realm() + ")),'hex')",
                  'credential_epoch': "'1'", 'set_id': self.NEW_SET, 'member_id': self.LEASE_MEMBER, 'fence': "'1'",
                  'job_id': "(SELECT pg_catalog.convert_from(m.context_bytes,'UTF8')::jsonb->>'job_id' FROM "
                            "wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE x.state='RECEIVING' ORDER BY m.ordinal LIMIT 1)",
                  'request_id': "'c0000000-0000-4000-8000-000000000002'"}
        if function == 'claim_member_v1':
            values.update(raw_digest="'" + '5' * 64 + "'", context_digest="(SELECT m.context_digest FROM "
                          "wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE x.state='RECEIVING' ORDER BY m.ordinal LIMIT 1)")
        values.update(fields)
        for key in drop:
            values.pop(key)
        request = 'pg_catalog.jsonb_build_object(' + ','.join("'" + k + "'," + v for k, v in values.items()) + ')'
        return ("DO $lease_call$ DECLARE st wl_pg.instance_state%ROWTYPE;r jsonb;ctx jsonb;doc jsonb;b bytea; BEGIN "
                "SELECT * INTO st FROM wl_pg.instance_state WHERE id=1;" + prelude + " r:=wl_ingestion." + function + "('" + self.WORKER + "','" +
                (token or self.WORKER_TOKEN) + "'," + request + "," + data + "); "
                "PERFORM pg_catalog.set_config('test." + label + "',r::text,true); END $lease_call$;"
                "SELECT '" + label.upper() + " '||pg_catalog.current_setting('test." + label + "');")

    LEASE_STATE = ("SELECT 'LSTATE '||pg_catalog.jsonb_build_object('member',(SELECT pg_catalog.jsonb_build_array(m.state,m.fence) "
        "FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE x.state='RECEIVING' ORDER BY m.ordinal LIMIT 1),"
        "'leases',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(l.state,l.claim_request_id,l.last_request_id,"
        "l.expires_at=pg_catalog.date_trunc('second',l.expires_at)) ORDER BY l.attempt) FROM wl_ingestion.leases l "
        "WHERE l.work_kind='normalize'),'pins',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('member_id',m.id,"
        "'connection_id',m.connection_id,'connection_version',m.connection_version,'connection_generation',"
        "m.connection_generation::text,'enablement_generation',m.enablement_generation::text,'availability_generation',"
        "m.availability_generation::text,'installation_id',m.installation_id,'wrapper_profile_digest',"
        "m.wrapper_profile_digest,'format_version',m.format_version,'context_digest',m.context_digest)) "
        "FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE x.state='RECEIVING'))::text;")

    def test_lease_functions_match_their_worker_declarations(self):
        declared = {x['name']: x for x in schema.inventory()['functions']}
        for name, ddl in (('claim_member_v1', schema.CLAIM_DDL), ('renew_member_v1', schema.RENEW_DDL),
                          ('admit_stage_v1', schema.ADMIT_DDL), ('finish_member_v1', schema.FINISH_DDL)):
            with self.subTest(function=name):
                self.assertEqual((['uuid', 'text', 'jsonb', 'bytea'], 'jsonb', 'ingestion_worker_only'),
                    (declared[name]['arguments'], declared[name]['returns'], declared[name]['execute']))
                self.assertIn('REVOKE ALL ON FUNCTION wl_ingestion.' + name + '(uuid,text,jsonb,bytea) FROM PUBLIC;', ddl)
                self.assertEqual(1, ddl.count('CREATE FUNCTION'))
                self.assertIn('wl_ingestion._guard_worker_v1(p_worker,p_token,p_request)', ddl)
                for fragment in ('GRANT ', 'DELETE ', 'MEMBER_PINS', 'UUID_RE', 'ACK_', 'STEP', 'SHAPE', 'KEYS', 'NAME',
                                 'HELD_BYTES', 'BYTES_EXPECTED', 'PINS', 'REPLAY', 'LIVE_STATES', 'CLEANED',
                                 'QUOTA_LOCKS', 'CODES', 'FINISH_ACK'):
                    self.assertNotIn(fragment, ddl)

    def test_claim_activates_the_bound_offer_once_and_renew_extends_it(self):
        from kurafolio.ingestion.codec import encode
        plan, pin, seed, catalog = self.claim_seed()
        renew_two = "'c0000000-0000-4000-8000-000000000003'"
        out = self.run_labelled(seed + self.LEASE_STATE.replace("'LSTATE '", "'BEFORE '") +
            self.lease_call('claim_member_v1', 'claim') + self.LEASE_STATE +
            self.lease_call('claim_member_v1', 'again') +
            self.lease_call('claim_member_v1', 'other', request_id="'c0000000-0000-4000-8000-000000000009'") +
            self.lease_call('renew_member_v1', 'renew') + self.lease_call('renew_member_v1', 'renewagain') +
            self.lease_call('renew_member_v1', 'renewtwo', request_id=renew_two) +
            self.LEASE_STATE.replace("'LSTATE '", "'AFTER '"))
        self.assertTrue(out['BIND']['ok'], out['BIND'])
        self.assertEqual(['receiving', 1], out['BEFORE']['member'])
        claim = out['CLAIM']
        self.assertTrue(claim['ok'], claim)
        ack = claim['value']
        self.assertEqual(sorted(['version', 'job_id', 'set_id', 'member_id', 'work_kind', 'fence', 'credential_epoch',
                                 'expires_at', 'outcome', 'source_fingerprint']), sorted(ack))
        self.assertEqual((1, 'normalize', '1', '1', 'claimed', 0, None),
                         (ack['version'], ack['work_kind'], ack['fence'], ack['credential_epoch'], ack['outcome'],
                          ack['expires_at']['fractional_digits'], ack['expires_at']['zone']))
        self.assertRegex(ack['expires_at']['token'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$')
        # The fingerprint is the canonical hash of the Plan pinned_sources entries.
        self.assertEqual(hashlib.sha256(encode(out['BEFORE']['pins'])).hexdigest(), ack['source_fingerprint'])
        self.assertEqual((['normalizing', 1], [['active', 'c0000000-0000-4000-8000-000000000002', None, True]]),
                         (out['LSTATE']['member'], out['LSTATE']['leases']))
        self.assertEqual(dict(ack, outcome='already_claimed'), out['AGAIN']['value'])
        self.assertEqual({'ok': False, 'code': 'import_conflict'}, out['OTHER'])
        renewed = out['RENEW']['value']
        self.assertEqual('renewed', renewed['outcome'])
        self.assertGreaterEqual(renewed['expires_at']['token'], ack['expires_at']['token'])
        self.assertEqual(out['RENEW'], out['RENEWAGAIN'])
        self.assertTrue(out['RENEWTWO']['ok'], out['RENEWTWO'])
        self.assertEqual([['active', 'c0000000-0000-4000-8000-000000000002', renew_two.strip("'"), True]],
                         out['AFTER']['leases'])

    def test_claim_and_renew_refuse_without_changing_the_offer(self):
        replica = 'SET LOCAL session_replication_role=replica;'
        origin = 'SET LOCAL session_replication_role=origin;'
        plan, pin, seed, catalog = self.claim_seed()
        unknown = "'40000000-0000-4000-8000-0000000000ff'"
        claim = 'claim_member_v1'
        cases = (
            ('wrong_token', '', claim, {'token': 'cd' * 32}, 'authentication_required'),
            ('raw_digest', '', claim, {'raw_digest': "'" + '7' * 64 + "'"}, 'import_stale'),
            ('context_digest', '', claim, {'context_digest': "'" + '7' * 64 + "'"}, 'import_stale'),
            ('job_id', '', claim, {'job_id': unknown}, 'import_stale'),
            ('old_fence', '', claim, {'fence': "'2'"}, 'import_stale'),
            ('unknown_set', '', claim, {'set_id': unknown}, 'not_found'),
            ('unknown_member', '', claim, {'member_id': unknown}, 'not_found'),
            ('extra_field', '', claim, {'note': "'x'"}, 'import_invalid'),
            ('missing_field', '', claim, {'drop': ('raw_digest',)}, 'import_invalid'),
            ('bytes', '', claim, {'data': "'\\x00'::bytea"}, 'import_invalid'),
            ('prepare_kind', '', claim, {'work_kind': "'prepare'"}, 'import_invalid'),
            ('epoch', '', claim, {'credential_epoch': "'2'"}, 'credentials_changed'),
            ('disabled_connection', replica + 'UPDATE wl_sources.connection_lifecycle SET enabled=false;' + origin,
             claim, {}, 'source_unavailable'),
            ('offer_expired', replica + "UPDATE wl_ingestion.leases SET created_at=created_at-interval '2 minutes',"
             "expires_at=pg_catalog.clock_timestamp()-interval '1 second';"
             + origin, claim, {}, 'import_stale'),
            ('set_expired', replica + "UPDATE wl_ingestion.sets SET created_at=created_at-interval '2 days',expires_at=expires_at-"
             "interval '2 days';" + origin, claim, {}, 'import_expired'),
            ('renew_unclaimed', '', 'renew_member_v1', {}, 'import_stale'),
        )
        for name, mutation, function, fields, code in cases:
            with self.subTest(case=name):
                out = self.run_labelled(seed + mutation + self.lease_call(function, 'result', **fields) + self.LEASE_STATE)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                if name != 'set_expired':
                    self.assertEqual(['receiving', 1], out['LSTATE']['member'])
                    self.assertEqual('offered', out['LSTATE']['leases'][0][0])
                    self.assertIsNone(out['LSTATE']['leases'][0][1])

    def test_renew_refuses_a_lapsed_or_foreign_lease(self):
        replica = 'SET LOCAL session_replication_role=replica;'
        origin = 'SET LOCAL session_replication_role=origin;'
        plan, pin, seed, catalog = self.claim_seed()
        seed += self.lease_call('claim_member_v1', 'claim')
        for name, mutation, fields, code in (
                ('lapsed', replica + "UPDATE wl_ingestion.leases SET created_at=created_at-interval '2 minutes',"
             "expires_at=pg_catalog.clock_timestamp()-interval '1 second';"
                 + origin, {}, 'import_stale'),
                ('wrong_token', '', {'token': 'cd' * 32}, 'authentication_required'),
                ('cancelled', replica + "UPDATE wl_ingestion.leases SET state='cancelled';" + origin, {}, 'import_stale'),
                ('disabled_source', replica + 'UPDATE wl_sources.enablements SET enabled=false;' + origin, {}, 'source_unavailable')):
            with self.subTest(case=name):
                out = self.run_labelled(seed + mutation + self.lease_call('renew_member_v1', 'result', **fields) +
                                        self.LEASE_STATE)
                self.assertTrue(out['CLAIM']['ok'], out['CLAIM'])
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                self.assertIsNone(out['LSTATE']['leases'][0][2])

    # admit_stage_v1 receives canonical minimal evidence rebound to the member's
    # database-built context, as a real child result would be.
    def admit_call(self, label, *, fixture='minimal-parser2.json', mutate='', **fields):
        from kurafolio.ingestion.codec import encode
        source = encode(ORACLE[fixture]).decode()
        assert '$fixture$' not in source
        member = ("FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE x.state='RECEIVING' ORDER BY m.ordinal LIMIT 1")
        prelude = ("SELECT pg_catalog.convert_from(m.context_bytes,'UTF8')::jsonb INTO ctx " + member + ";"
            "doc:=$fixture$" + source + "$fixture$::jsonb;"
            "doc:=pg_catalog.jsonb_set(doc,'{provenance,raw_sha256}',pg_catalog.to_jsonb('" + '5' * 64 + "'::text));"
            "doc:=pg_catalog.jsonb_set(doc,'{provenance,installation_id}',(SELECT pg_catalog.to_jsonb(m.installation_id) " + member + "));"
            "doc:=pg_catalog.jsonb_set(doc,'{provenance,wrapper_profile_digest}',(SELECT pg_catalog.to_jsonb("
            "m.wrapper_profile_digest) " + member + "));"
            "doc:=pg_catalog.jsonb_set(doc,'{provenance,image_digest}',ctx->'image_digest');"
            "IF ctx->>'payload_kind'='parser_v2' THEN "
            "doc:=pg_catalog.jsonb_set(doc,'{provenance,evidence_reference}',ctx#>'{parser_context,source_reference}');"
            "doc:=pg_catalog.jsonb_set(doc,'{provenance,evidence_at,token}',ctx#>'{parser_context,evidence_at}');"
            "ELSE doc:=pg_catalog.jsonb_set(doc,'{provenance,evidence_reference}',ctx->'evidence_reference');"
            "doc:=pg_catalog.jsonb_set(doc,'{provenance,evidence_at}',ctx->'evidence_at'); END IF;" + mutate +
            "b:=wl_ingestion._canonical_v1(doc);")
        values = {'raw_digest': "'" + '5' * 64 + "'", 'discovery_digest': "doc#>>'{provenance,discovery_sha256}'",
                  'stage_digest': "pg_catalog.encode(pg_catalog.sha256(b),'hex')", 'payload_bytes': 'pg_catalog.octet_length(b)',
                  'data': 'b'}
        values.update(fields)
        return self.lease_call('admit_stage_v1', label, prelude=prelude, **values)

    STAGE_STATE = ("SELECT 'SSTATE '||pg_catalog.jsonb_build_object('stages',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array("
        "g.codec,g.digest=pg_catalog.encode(pg_catalog.sha256(g.minimal_bytes),'hex'),g.purge_at=x.expires_at)) FROM "
        "wl_ingestion.stages g JOIN wl_ingestion.sets x ON x.id=g.set_id WHERE x.state='RECEIVING'),'member',(SELECT pg_catalog.jsonb_build_array("
        "m.state,m.stage_digest) FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE "
        "x.state='RECEIVING' ORDER BY m.ordinal LIMIT 1))::text;")

    def test_admit_stores_one_validated_stage_per_attempt(self):
        plan, pin, seed, catalog = self.claim_seed()
        out = self.run_labelled(seed + self.lease_call('claim_member_v1', 'claim') + self.admit_call('admit') +
            self.STAGE_STATE + self.admit_call('again') +
            self.admit_call('other', mutate="doc:=pg_catalog.jsonb_set(doc,'{provenance,adapter_version}','\"1.0.1\"');") +
            self.STAGE_STATE.replace("'SSTATE '", "'AFTER '"))
        self.assertTrue(out['CLAIM']['ok'], out['CLAIM'])
        admitted = out['ADMIT']
        self.assertTrue(admitted['ok'], admitted)
        ack = admitted['value']
        self.assertEqual(sorted(['version', 'job_id', 'fence', 'member_id', 'stage_digest', 'outcome']), sorted(ack))
        self.assertEqual((1, '1', 'admitted', out['CLAIM']['value']['job_id'], out['CLAIM']['value']['member_id']),
                         (ack['version'], ack['fence'], ack['outcome'], ack['job_id'], ack['member_id']))
        # The stage waits for finish; the member keeps normalizing without a stage digest.
        self.assertEqual({'stages': [['minimal-evidence-v1', True, True]], 'member': ['normalizing', None]}, out['SSTATE'])
        self.assertEqual(dict(ack, outcome='already_admitted'), out['AGAIN']['value'])
        self.assertEqual({'ok': False, 'code': 'import_conflict'}, out['OTHER'])
        self.assertEqual(out['SSTATE'], out['AFTER'])

    def test_admit_accepts_native_evidence_for_its_own_namespace_context(self):
        plan, pin, seed, catalog = self.claim_seed(projection='domain1-minimal-v1')
        out = self.run_labelled(seed + self.lease_call('claim_member_v1', 'claim') +
                                self.admit_call('admit', fixture='minimal-native.json') + self.STAGE_STATE)
        self.assertTrue(out['ADMIT']['ok'], out['ADMIT'])
        self.assertEqual(1, len(out['SSTATE']['stages']))

    def test_admit_refuses_mismatched_evidence_without_storing_it(self):
        plan, pin, seed, catalog = self.claim_seed()
        replica = 'SET LOCAL session_replication_role=replica;'
        origin = 'SET LOCAL session_replication_role=origin;'
        claimed = seed + self.lease_call('claim_member_v1', 'claim')
        other = "'" + '7' * 64 + "'"
        cases = (
            ('stage_digest', claimed, {'stage_digest': other}, 'import_invalid'),
            ('payload_bytes', claimed, {'payload_bytes': 'pg_catalog.octet_length(b)+1'}, 'import_invalid'),
            ('payload_string', claimed, {'payload_bytes': "'12'"}, 'import_invalid'),
            ('no_bytes', claimed, {'data': 'NULL'}, 'import_invalid'),
            ('request_raw', claimed, {'raw_digest': other}, 'import_stale'),
            ('discovery', claimed, {'discovery_digest': other}, 'import_invalid'),
            ('provenance_raw', claimed, {'mutate': "doc:=pg_catalog.jsonb_set(doc,'{provenance,raw_sha256}','\"" + '7' * 64 +
                                         "\"');"}, 'import_invalid'),
            ('evidence_reference', claimed, {'mutate': "doc:=pg_catalog.jsonb_set(doc,'{provenance,evidence_reference}',"
                                             "'\"70000000-0000-4000-8000-000000000001\"');"}, 'import_invalid'),
            ('image', claimed, {'mutate': "doc:=pg_catalog.jsonb_set(doc,'{provenance,image_digest}','\"" + 'e' * 64 +
                                "\"');"}, 'import_invalid'),
            ('not_minimal', claimed, {'mutate': "doc:=doc-'records';"}, 'import_invalid'),
            ('unclaimed', seed, {}, 'import_stale'),
            ('wrong_token', claimed, {'token': 'cd' * 32}, 'authentication_required'),
            ('reservation', claimed + replica + 'UPDATE wl_ingestion.sets SET reserved_bytes=2048;' + origin, {}, 'import_limit'),
        )
        for name, prefix, fields, code in cases:
            with self.subTest(case=name):
                out = self.run_labelled(prefix + self.admit_call('result', **fields) + self.STAGE_STATE)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                self.assertIsNone(out['SSTATE']['stages'])

    # finish_member_v1: the set may leave RECEIVING, so these find it by the
    # operation that created it.
    OWN = ("FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE "
           "x.creation_operation_id='53000000-0000-4000-8000-000000000001' ORDER BY m.ordinal LIMIT 1")
    PROOF = ("pg_catalog.jsonb_build_object('job_id',(SELECT pg_catalog.convert_from(m.context_bytes,'UTF8')::jsonb->>'job_id' "
             "OWN),'fence','1','state','STATE','launcher_instance_id','c0000000-0000-4000-8000-000000000003','proof_digest','" +
             '1' * 64 + "','checked_at','{\"tag\":\"instant\",\"token\":\"2026-02-02T13:00:10+00:00\",\"zone\":null,"
             "\"fractional_digits\":0}'::jsonb)")

    def proofs(self, *states):
        return 'pg_catalog.jsonb_build_array(' + ','.join(
            self.PROOF.replace('OWN', self.OWN).replace('STATE', state) for state in states) + ')'

    def finish_call(self, label, *, outcome='stage_admitted', error_code=None, proofs=('absent',), **fields):
        values = {'set_id': '(SELECT x.id::text ' + self.OWN + ')', 'member_id': '(SELECT m.id::text ' + self.OWN + ')',
                  'job_id': "(SELECT pg_catalog.convert_from(m.context_bytes,'UTF8')::jsonb->>'job_id' " + self.OWN + ')',
                  'outcome': "'" + outcome + "'", 'error_code': 'NULL::text' if error_code is None else "'" + error_code + "'",
                  'cleanup_proofs': self.proofs(*proofs), 'request_id': "'c0000000-0000-4000-8000-000000000007'"}
        values.update(fields)
        return self.lease_call('finish_member_v1', label, **values)

    FINISH_STATE = ("SELECT 'FSTATE '||pg_catalog.jsonb_build_object('set',(SELECT pg_catalog.jsonb_build_array(x.state,"
        "x.revision,x.cleanup_state) FROM wl_ingestion.sets x WHERE x.creation_operation_id='53000000-0000-4000-8000-000000000001'),"
        "'members',(SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(m.state,m.error_code,m.stage_digest IS NOT NULL,"
        "m.fence) ORDER BY m.ordinal) FROM wl_ingestion.members m JOIN wl_ingestion.sets x ON x.id=m.set_id WHERE "
        "x.creation_operation_id='53000000-0000-4000-8000-000000000001'),'leases',(SELECT pg_catalog.jsonb_agg(l.state "
        "ORDER BY l.attempt,l.created_at) FROM wl_ingestion.leases l WHERE l.work_kind='normalize'),'raw',(SELECT "
        "pg_catalog.jsonb_build_array(used_count,lease_count) FROM wl_ingestion.quotas WHERE bucket='raw'))::text;")

    def finish_seed(self, **kwargs):
        plan, pin, seed, catalog = self.claim_seed(**kwargs)
        return plan, pin, seed + self.lease_call('claim_member_v1', 'claim') + self.admit_call('admit'), catalog

    def test_finish_admits_the_stage_hands_the_set_on_and_releases_the_proven_slot(self):
        plan, pin, seed, catalog = self.finish_seed()
        out = self.run_labelled(seed + self.FINISH_STATE.replace("'FSTATE '", "'BEFORE '") + self.finish_call('finish') +
            self.FINISH_STATE + self.finish_call('again') +
            self.finish_call('other', request_id="'c0000000-0000-4000-8000-000000000008'"))
        self.assertTrue(out['ADMIT']['ok'], out['ADMIT'])
        self.assertEqual([1, 1], out['BEFORE']['raw'])
        finished = out['FINISH']
        self.assertTrue(finished['ok'], finished)
        self.assertEqual({'version': 1, 'job_id': out['CLAIM']['value']['job_id'], 'fence': '1',
                          'member_id': out['CLAIM']['value']['member_id'], 'state': 'admitted', 'cleanup_complete': True},
                         finished['value'])
        # Upload and preparation hand-offs keep the set revision.
        self.assertEqual({'set': ['NORMALIZING', 1, 'not_needed'], 'members': [['admitted', None, True, 1]],
                          'leases': ['finished'], 'raw': [1, 0]}, out['FSTATE'])
        self.assertEqual(finished, out['AGAIN'])
        self.assertEqual({'ok': False, 'code': 'import_stale'}, out['OTHER'])

    def test_finish_keeps_the_slot_until_cleanup_is_proven_and_waits_for_every_member(self):
        for label, proofs, raw in (('pending', ('absent', 'pending'), [1, 1]), ('failed', ('failed',), [1, 1]),
                                   ('none', (), [1, 1]), ('not_created', ('not_created', 'absent'), [1, 0])):
            with self.subTest(proofs=label):
                plan, pin, seed, catalog = self.finish_seed()
                out = self.run_labelled(seed + self.finish_call('finish', proofs=proofs) + self.FINISH_STATE)
                self.assertEqual(raw == [1, 0], out['FINISH']['value']['cleanup_complete'])
                self.assertEqual(raw, out['FSTATE']['raw'])
        plan, pin, seed, catalog = self.finish_seed(count=2)
        out = self.run_labelled(seed + self.finish_call('finish') + self.FINISH_STATE)
        self.assertTrue(out['FINISH']['ok'], out['FINISH'])
        self.assertEqual(['RECEIVING', 1, 'not_needed'], out['FSTATE']['set'])
        self.assertEqual([['admitted', None, True, 1], ['waiting', None, False, 1]], out['FSTATE']['members'])

    def test_finish_requests_a_reupload_that_starts_a_clean_attempt(self):
        plan, pin, seed, catalog = self.finish_seed()
        out = self.run_labelled(seed + self.finish_call('finish', outcome='reupload_required',
                                                        error_code='import_evidence_unsupported') + self.FINISH_STATE +
                                self.reserve_call('again', catalog) + self.FINISH_STATE.replace("'FSTATE '", "'AFTER '"))
        self.assertEqual('reupload_required', out['FINISH']['value']['state'])
        self.assertEqual({'set': ['RECEIVING', 1, 'not_needed'], 'members': [['reupload_required',
                          'import_evidence_unsupported', False, 1]], 'leases': ['finished'], 'raw': [1, 0]}, out['FSTATE'])
        self.assertTrue(out['AGAIN']['ok'], out['AGAIN'])
        self.assertEqual([['receiving', None, False, 2]], out['AFTER']['members'])
        self.assertEqual(['finished', 'offered'], out['AFTER']['leases'])

    def test_finish_rejection_rejects_the_whole_set(self):
        plan, pin, seed, catalog = self.claim_seed(count=2)
        seed += self.lease_call('claim_member_v1', 'claim')
        out = self.run_labelled(seed + self.finish_call('finish', outcome='rejected', error_code='import_invalid') +
                                self.FINISH_STATE + self.finish_call('again', outcome='rejected', error_code='import_invalid'))
        self.assertTrue(out['FINISH']['ok'], out['FINISH'])
        self.assertEqual(('rejected', True), (out['FINISH']['value']['state'], out['FINISH']['value']['cleanup_complete']))
        self.assertEqual({'set': ['REJECTED', 1, 'pending'], 'members': [['rejected', 'import_invalid', False, 1],
                          ['rejected', None, False, 1]], 'leases': ['finished'], 'raw': [1, 0]}, out['FSTATE'])
        self.assertEqual(out['FINISH'], out['AGAIN'])

    def test_finish_refuses_without_changing_the_attempt(self):
        replica = 'SET LOCAL session_replication_role=replica;'
        origin = 'SET LOCAL session_replication_role=origin;'
        plan, pin, seed, catalog = self.finish_seed()
        claimed_only = self.claim_seed()[2] + self.lease_call('claim_member_v1', 'claim')
        disabled = replica + 'UPDATE wl_sources.enablements SET enabled=false;' + origin
        cases = (
            ('no_stage', claimed_only, {}, 'import_invalid'),
            ('admitted_with_code', seed, {'error_code': 'import_invalid'}, 'import_invalid'),
            ('reupload_without_code', seed, {'outcome': 'reupload_required'}, 'import_invalid'),
            ('unknown_code', seed, {'outcome': 'rejected', 'error_code': 'made_up'}, 'import_invalid'),
            ('unknown_outcome', seed, {'outcome': 'committed'}, 'import_invalid'),
            ('four_proofs', seed, {'proofs': ('absent',) * 4}, 'import_invalid'),
            ('proof_fence', seed, {'cleanup_proofs': self.proofs('absent').replace("'fence','1'", "'fence','2'")}, 'import_invalid'),
            ('proof_job', seed, {'cleanup_proofs': self.proofs('absent').replace(
                "(SELECT pg_catalog.convert_from(m.context_bytes,'UTF8')::jsonb->>'job_id' " + self.OWN + ")",
                "'40000000-0000-4000-8000-0000000000ff'")}, 'import_invalid'),
            ('proof_state', seed, {'proofs': ('gone',)}, 'import_invalid'),
            ('unclaimed', self.claim_seed()[2], {}, 'import_stale'),
            ('wrong_token', seed, {'token': 'cd' * 32}, 'authentication_required'),
            ('old_fence', seed, {'fence': "'2'", 'cleanup_proofs': self.proofs('absent').replace("'fence','1'", "'fence','2'")},
             'import_stale'),
            ('disabled_source', seed + disabled, {}, 'source_unavailable'),
        )
        for name, prefix, fields, code in cases:
            with self.subTest(case=name):
                out = self.run_labelled(prefix + self.finish_call('result', **fields) + self.FINISH_STATE)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
                self.assertEqual(['RECEIVING', 1, 'not_needed'], out['FSTATE']['set'])
                unclaimed = name == 'unclaimed'
                self.assertEqual('receiving' if unclaimed else 'normalizing', out['FSTATE']['members'][0][0])
                self.assertEqual(['offered' if unclaimed else 'active'], out['FSTATE']['leases'])
                self.assertEqual([1, 1], out['FSTATE']['raw'])
        # A source change cannot block giving the file back for re-upload.
        out = self.run_labelled(seed + disabled + self.finish_call('result', outcome='reupload_required',
                                                                   error_code='source_unavailable') + self.FINISH_STATE)
        self.assertTrue(out['RESULT']['ok'], out['RESULT'])

    def test_normalize_work_keeps_the_uploaders_session_and_the_raw_deadline(self):
        replica = 'SET LOCAL session_replication_role=replica;'
        origin = 'SET LOCAL session_replication_role=origin;'
        revoked = 'UPDATE wl_identity.sessions SET revoked=true;'
        plan, pin, seed, catalog = self.claim_seed()
        claimed = seed + self.lease_call('claim_member_v1', 'claim')
        admitted = claimed + self.admit_call('admit')
        for name, prefix, call, code in (
                ('claim', seed + revoked, self.lease_call('claim_member_v1', 'result'), 'session_changed'),
                ('renew', claimed + revoked, self.lease_call('renew_member_v1', 'result'), 'session_changed'),
                ('admit', claimed + revoked, self.admit_call('result'), 'session_changed'),
                ('finish', admitted + revoked, self.finish_call('result'), 'session_changed'),
                ('raw_deadline', seed + replica + "UPDATE wl_ingestion.members SET raw_deadline=pg_catalog.clock_timestamp()"
                 "-interval '1 second' WHERE state='receiving';" + origin, self.lease_call('claim_member_v1', 'result'),
                 'import_reupload_required')):
            with self.subTest(case=name):
                out = self.run_labelled(prefix + call)
                self.assertEqual({'ok': False, 'code': code}, out['RESULT'])
        # Giving a file back for re-upload needs no live user session.
        out = self.run_labelled(admitted + revoked + self.finish_call('result', outcome='reupload_required',
                                                                      error_code='session_changed'))
        self.assertTrue(out['RESULT']['ok'], out['RESULT'])
        # A lease never outlives the member's raw deadline.
        near = (replica + "UPDATE wl_ingestion.members SET raw_deadline=pg_catalog.date_trunc('second',"
                "pg_catalog.clock_timestamp()+interval '8 seconds') WHERE state='receiving';" + origin)
        deadline = ("SELECT 'DEADLINE '||pg_catalog.jsonb_build_object('raw',pg_catalog.to_char(m.raw_deadline AT TIME ZONE "
                    "'UTC','YYYY-MM-DD\"T\"HH24:MI:SS')||'+00:00')::text FROM wl_ingestion.members m WHERE m.state='normalizing';")
        out = self.run_labelled(seed + near + self.lease_call('claim_member_v1', 'claim') + deadline +
                                self.lease_call('renew_member_v1', 'renew'))
        self.assertLessEqual(out['CLAIM']['value']['expires_at']['token'], out['DEADLINE']['raw'])
        self.assertLessEqual(out['RENEW']['value']['expires_at']['token'], out['DEADLINE']['raw'])

    def test_lease_functions_are_not_public(self):
        self.sql("DO $role$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_catalog.pg_roles WHERE "
                 "rolname='wl007_synthetic_guard_reader') THEN CREATE ROLE wl007_synthetic_guard_reader NOLOGIN; "
                 'END IF; END $role$;')
        for name in ('claim_member_v1', 'renew_member_v1', 'admit_stage_v1', 'finish_member_v1'):
            with self.subTest(function=name):
                self.assertEqual('f', self.sql("SELECT has_function_privilege('wl007_synthetic_guard_reader',"
                    "'wl_ingestion." + name + "(uuid,text,jsonb,bytea)','EXECUTE')"))

if __name__ == '__main__':
    unittest.main()
