"""Closed identity calls and immutable request principals; no import-time extras/I/O."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

from .context import Database, TenantContext, identifier
from .identity_schema import GATEWAY, SIGNATURES, TABLES

STATUS = {
    'authentication_required':401, 'anonymous_session_required':403, 'admin_required':403,
    'credentials_changed':409, 'session_changed':409, 'registration_rejected':400,
    'rate_limited':429, 'instance_not_ready':503, 'operator_not_found':404,
    'invite_not_active':409, 'setup_closed':409, 'setup_required':409,
    'setup_rejected':400, 'setup_already_armed':409, 'setup_not_active':409,
    'not_found':404, 'invite_already_issued':409,
}


class IdentityError(Exception):
    """A stable diagnostic, never a driver exception or bearer payload."""
    def __init__(self, code='instance_not_ready', *, uncertain=False, record_id=None):
        self.code = code if code in STATUS else 'instance_not_ready'
        self.status = STATUS[self.code]
        self.uncertain = uncertain
        self.record_id = record_id
        super().__init__(self.code)


def timestamp(value):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z', value):
        raise IdentityError()
    try:
        return datetime.fromisoformat(value[:-1]+'+00:00')
    except ValueError:
        raise IdentityError() from None


REALM_KEYS = ('database', 'database_oid', 'server_address', 'server_port', 'incarnation', 'epoch')


@dataclass(frozen=True, slots=True, repr=False)
class Principal:
    user_id: str
    portfolio_id: str
    username: str
    credential_version: int
    session_digest: str
    expires_at: datetime
    idle_expires_at: datetime
    authorized_at: datetime
    is_instance_admin: bool
    realm: tuple

    def __post_init__(self):
        try:
            identifier(self.user_id)
            identifier(self.portfolio_id)
            if (not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',self.username)
                    or type(self.credential_version) is not int or not 1<=self.credential_version<=9223372036854775807
                    or not re.fullmatch(r'[0-9a-f]{64}',self.session_digest)
                    or type(self.is_instance_admin) is not bool or len(self.realm)!=6
                    or self.authorized_at>=min(self.expires_at,self.idle_expires_at)
                    or any(t.tzinfo is None or t.utcoffset().total_seconds()!=0 for t in [self.expires_at,self.idle_expires_at,self.authorized_at])):
                raise ValueError()
        except Exception:
            raise IdentityError() from None

    def __repr__(self):
        return 'Principal(<private>)'

    @property
    def context(self):
        return TenantContext(self.user_id,self.portfolio_id)

    def matches_realm(self, row):
        return tuple(row[key] for key in REALM_KEYS)==self.realm

    @classmethod
    def from_value(cls,value):
        try:
            keys={'user_id','portfolio_id','username','credential_version','session_digest','expires_at','idle_expires_at','authorized_at','is_instance_admin','realm'}
            if type(value) is not dict or set(value)!=keys or set(value['realm'])!=set(REALM_KEYS):
                raise ValueError()
            realm=value['realm']
            if (type(realm['database']) is not str or not realm['database']
                    or type(realm['database_oid']) is not int or realm['database_oid']<=0
                    or type(realm['epoch']) is not int or not 0<=realm['epoch']<=9223372036854775807
                    or realm['server_address'] is not None and type(realm['server_address']) is not str
                    or realm['server_port'] is not None and (type(realm['server_port']) is not int or not 1<=realm['server_port']<=65535)):
                raise ValueError()
            identifier(realm['incarnation'])
            return cls(value['user_id'],value['portfolio_id'],value['username'],value['credential_version'],value['session_digest'],
                       timestamp(value['expires_at']),timestamp(value['idle_expires_at']),timestamp(value['authorized_at']),
                       value['is_instance_admin'],tuple(realm[key] for key in REALM_KEYS))
        except IdentityError:
            raise
        except Exception:
            raise IdentityError() from None


class IdentityStore:
    """Each expected business rejection commits its sampled clock before mapping."""
    def __init__(self, config, *, schema_mode="identity"):
        if schema_mode not in {"identity", "sources"}:
            raise IdentityError()
        self.database=Database(config,schema_mode=schema_mode)

    def close(self):
        self.database.close()

    def call(self,name,*arguments,before_commit=None):
        if name not in SIGNATURES or name=='_clock_timestamp_v1' or len(arguments)!=len(SIGNATURES[name]):
            raise IdentityError()
        from sqlalchemy import text
        types={'bigint':'int8','integer':'int4','boolean':'bool'}
        parameters={f'p{i}':value for i,value in enumerate(arguments)}
        slots=','.join(f'CAST(:p{i} AS pg_catalog.{types.get(kind,kind)})' for i,kind in enumerate(SIGNATURES[name]))
        statement=text(f'SELECT wl_identity.{name}({slots})')
        result=None
        try:
            with self.database.engine.connect() as conn:
                transaction=conn.begin()
                try:
                    result=conn.execute(statement,parameters).scalar_one()
                    if before_commit is not None and type(result) is dict and result.get('ok') is True:
                        before_commit(result['value'])
                except Exception:
                    transaction.rollback()
                    raise IdentityError() from None
                try:
                    transaction.commit()
                except Exception:
                    value=result.get('value',{}) if type(result) is dict else {}
                    record_id=next((value[k] for k in ['id','invite_id','setup_id'] if k in value),None)
                    if record_id is not None:
                        try:identifier(record_id)
                        except Exception:record_id=None
                    raise IdentityError(uncertain=True,record_id=record_id) from None
        except IdentityError:
            raise
        except Exception:
            raise IdentityError() from None
        if type(result) is not dict or type(result.get('ok')) is not bool:
            raise IdentityError()
        if result['ok']:
            if set(result)!={'ok','value'} or type(result['value']) is not dict:
                raise IdentityError()
            return result['value']
        if set(result)!={'ok','code'} or result['code'] not in STATUS:
            raise IdentityError()
        raise IdentityError(result['code'])

    def status(self):
        value=self.call('identity_status_v1')
        required=set(REALM_KEYS)|{'ready','schema_revision','key_digest','bootstrap_closed','admin_user_id'}
        if (set(value)!=required or value['schema_revision']!=self.database.revision or value['ready'] is not True
                or type(value['bootstrap_closed']) is not bool or value['bootstrap_closed']!=(value['admin_user_id'] is not None)
                or type(value['key_digest']) is not str or not re.fullmatch(r'[0-9a-f]{64}',value['key_digest'])):
            raise IdentityError()
        return value

    def session(self,digest,kind='any'):
        value=self.call('validate_session_v1',digest,kind)
        if value.get('kind')=='anonymous' and set(value)=={'kind','expires_at'}:
            timestamp(value['expires_at'])
            return None
        if value.get('kind')=='authenticated' and set(value)=={'kind','principal'}:
            return Principal.from_value(value['principal'])
        raise IdentityError()


def role_inventory(database, *, gateway, connection=None, role=None):
    """Inspect effective rights, including PUBLIC/column grants and memberships."""
    from .context import execute
    from contextlib import nullcontext
    class CatalogRole:
        # A metadata-only view for a trusted operator to inspect another fixed
        # runtime role without SET ROLE or requiring that role's password.
        def __init__(self, raw, name):
            if type(name) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{0,62}',name):
                raise IdentityError()
            self.raw,self.name=raw,name
        def execute(self,statement,parameters=None):
            from sqlalchemy import text
            sql=statement.text.replace('current_user','CAST(:inventory_role AS name)')
            return self.raw.execute(text(sql),{**(parameters or {}),'inventory_role':self.name})
    try:
        with (database.engine.begin() if connection is None else nullcontext(connection)) as checked:
            conn=CatalogRole(checked,role) if role is not None else checked
            role=execute(conn,"""SELECT current_user AS name,r.rolsuper,r.rolbypassrls,r.rolcreatedb,r.rolcreaterole,
              EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) AS member,
              EXISTS(SELECT 1 FROM pg_namespace WHERE nspname IN ('wl_identity','wl_pg') AND nspowner=r.oid)
                OR r.oid=(SELECT datdba FROM pg_database WHERE datname=current_database()) AS owns
              FROM pg_roles r WHERE rolname=current_user""").mappings().one()
            if any(role[key] for key in ['rolsuper','rolbypassrls','rolcreatedb','rolcreaterole','member','owns']):
                raise IdentityError()
            if execute(conn,"SELECT has_schema_privilege(current_user,'wl_identity','CREATE') OR has_schema_privilege(current_user,'wl_pg','CREATE')").scalar_one():
                raise IdentityError()
            function_rows=execute(conn,"""SELECT p.proname,has_function_privilege(current_user,p.oid,'EXECUTE') AS can_execute,
              p.prosecdef,p.proowner=n.nspowner AS owned,p.proconfig
              FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='wl_identity'""").mappings().all()
            if len(function_rows)!=22 or {r['proname'] for r in function_rows}!=set(SIGNATURES):
                raise IdentityError()
            for row in function_rows:
                if (row['can_execute']!=(gateway and row['proname'] in GATEWAY)
                        or not row['prosecdef'] or not row['owned']
                        or 'search_path=pg_catalog,pg_temp' not in [s.replace(' ','') for s in row['proconfig'] or []]):
                    raise IdentityError()
            objects=execute(conn,"""SELECT n.nspname,c.relname,c.relrowsecurity,c.relforcerowsecurity,
              has_table_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
              OR has_any_column_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE,REFERENCES') AS raw_access
              FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE c.relkind='r' AND n.nspname IN ('wl_identity','wl_pg')""").mappings().all()
            for row in objects:
                if (row['nspname']=='wl_identity' or gateway) and row['raw_access']:
                    raise IdentityError()
            identity=[r for r in objects if r['nspname']=='wl_identity']
            finance=[r for r in objects if r['nspname']=='wl_pg' and r['relname'] not in {'instance_state','alembic_version'}]
            if (len(identity)!=7 or {r['relname'] for r in identity}!=set(TABLES) or len(finance)!=22
                    or not all(r['relrowsecurity'] and r['relforcerowsecurity'] for r in finance)):
                raise IdentityError()
            if not gateway:
                updates={'portfolios':{'fact_generation'},'connections':{'generation'},
                         'repository_heads':{'batch_id','revision_key'},'outbox':{'dispatched_at'},
                         'jobs':{'status','attempt','fencing_token','worker_id','lease_expires_at',
                                 'available_at','error_code','cancel_requested','lease_seconds'}}
                for table in [r['relname'] for r in objects if r['nspname']=='wl_pg']:
                    relation='wl_pg.'+table
                    rights=execute(conn,"""SELECT has_table_privilege(current_user,:relation,'SELECT') AS readable,
                      has_table_privilege(current_user,:relation,'DELETE,TRUNCATE,REFERENCES,TRIGGER') AS excessive""",relation=relation).mappings().one()
                    if not rights['readable'] or rights['excessive']:
                        raise IdentityError()
                    columns=execute(conn,"""SELECT a.attname,
                      has_column_privilege(current_user,c.oid,a.attnum,'INSERT') AS writable,
                      has_column_privilege(current_user,c.oid,a.attnum,'UPDATE') AS changeable,
                      has_column_privilege(current_user,c.oid,a.attnum,'REFERENCES') AS referenceable
                      FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                      JOIN pg_attribute a ON a.attrelid=c.oid
                      WHERE n.nspname='wl_pg' AND c.relname=:table AND a.attnum>0 AND NOT a.attisdropped""",table=table).mappings().all()
                    insertable=table not in {'tenant_roots','portfolios','instance_state','alembic_version'}
                    for column in columns:
                        if (column['writable']!=insertable or column['changeable']!=(column['attname'] in updates.get(table,set()))
                                or column['referenceable']):
                            raise IdentityError()
            if database.schema_mode=='sources':
                from .source_store import source_role_inventory
                source_role_inventory(conn,gateway=gateway)
            return role['name']
    except IdentityError:
        raise
    except Exception:
        raise IdentityError() from None
