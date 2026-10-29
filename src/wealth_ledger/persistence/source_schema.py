"""Explicit sources-profile DDL; old migration/provider bytes remain immutable."""
from . import identity_schema as identity

REVISION = "0003_source_lifecycle"
TABLES = ("catalog_state", "installations", "lifecycle_roots", "enablements",
          "connection_lifecycle", "lifecycle_receipts", "lifecycle_audit")
TENANT_TABLES = TABLES[2:]
GATEWAY = ("sources_catalog_v1", "sources_connections_v1", "sources_connection_v1",
           "set_source_enablement_v1", "create_source_connection_v1", "update_source_connection_v1")
TRIGGERS = ("guard_enablement_update_v1", "guard_connection_update_v1")
ARGUMENTS = ("text", "uuid", "bigint", "jsonb", "text", "jsonb")


def signature(name):
    if name not in (*GATEWAY, *TRIGGERS):
        raise ValueError("Unknown source function")
    return "wl_sources." + name + "(" + (",".join(ARGUMENTS) if name in GATEWAY else "") + ")"


def identity_replacements():
    """Generate only reviewed function replacements, never mutate old providers."""
    import re
    source = identity.ddl()
    functions = re.findall(r"CREATE FUNCTION wl_identity\.[a-z_0-9]+\([^\n]*\) RETURNS pg_catalog\.jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS \$identity\$.*?\$identity\$;\nREVOKE ALL ON FUNCTION [^;]+;", source, re.S)
    if len(functions) != 21:
        raise ValueError("Identity provider changed")
    result = []
    for sql in functions:
        sql = sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1).replace("'0002_identity'", "'0003_source_lifecycle'")
        if sql.startswith("CREATE OR REPLACE FUNCTION wl_identity.consume_budget_v1("):
            replacements = {
                "'setup','invite_issue','invite_revoke','invite_read')": "'setup','invite_issue','invite_revoke','invite_read','source_read','source_write')",
                "'password_change','invite_issue','invite_revoke','invite_read') AND": "'password_change','invite_issue','invite_revoke','invite_read','source_read','source_write') AND",
                "p_operation LIKE 'invite_%' THEN": "(p_operation LIKE 'invite_%' OR p_operation IN ('source_read','source_write')) THEN",
                "p_operation IN ('anonymous','invite_read') THEN 300": "p_operation IN ('anonymous','invite_read','source_read','source_write') THEN 300",
                "lim:=CASE WHEN p_operation='anonymous' THEN": "lim:=CASE WHEN p_operation='source_read' THEN CASE WHEN bucket_key=p_operation||':instance' THEN 600 ELSE 60 END WHEN p_operation='source_write' THEN CASE WHEN bucket_key=p_operation||':instance' THEN 300 ELSE 30 END WHEN p_operation='anonymous' THEN",
            }
            for before, after in replacements.items():
                if sql.count(before) != 1:
                    raise ValueError("Identity budget provider changed")
                sql = sql.replace(before, after)
        result.append(sql)
    return "\n".join(result)


TABLE_DDL = r"""
CREATE SCHEMA wl_sources;
REVOKE ALL ON SCHEMA wl_sources FROM PUBLIC;
CREATE TABLE wl_sources.catalog_state(
 id smallint PRIMARY KEY CHECK(id=1),revision bigint NOT NULL CHECK(revision>=0),
 digest text NOT NULL CHECK(digest ~ '^[0-9a-f]{64}$'),bundle_bytes bytea NOT NULL,
 updated_at timestamptz NOT NULL CHECK(pg_catalog.isfinite(updated_at)),
 CHECK(octet_length(bundle_bytes)<=4194304),CHECK(digest=encode(sha256(bundle_bytes),'hex'))
);
CREATE TABLE wl_sources.installations(
 id text PRIMARY KEY CHECK(id ~ '^[0-9a-f]{64}$'),plugin_id text NOT NULL CHECK(plugin_id ~ '^[a-z][a-z0-9_.-]{0,63}$'),
 provider_id text NOT NULL CHECK(provider_id ~ '^[a-z][a-z0-9_.-]{0,63}$'),
 adapter_id text NOT NULL CHECK(adapter_id ~ '^[a-z][a-z0-9_.-]{0,63}$'),descriptor_bytes bytea NOT NULL,
 created_at timestamptz NOT NULL CHECK(pg_catalog.isfinite(created_at)),UNIQUE(id,plugin_id,provider_id),
 CHECK(octet_length(descriptor_bytes)<=16384),CHECK(id=encode(sha256(descriptor_bytes),'hex')),
 CHECK((convert_from(descriptor_bytes,'UTF8')::jsonb->>'plugin_id')=plugin_id),
 CHECK((convert_from(descriptor_bytes,'UTF8')::jsonb->>'provider_id')=provider_id),
 CHECK((convert_from(descriptor_bytes,'UTF8')::jsonb->>'adapter_id')=adapter_id)
);
CREATE TABLE wl_sources.lifecycle_roots(
 tenant_id uuid NOT NULL,portfolio_id uuid NOT NULL,revision bigint NOT NULL DEFAULT 0 CHECK(revision>=0),
 created_at timestamptz NOT NULL CHECK(pg_catalog.isfinite(created_at)),PRIMARY KEY(tenant_id,portfolio_id),
 FOREIGN KEY(tenant_id,portfolio_id) REFERENCES wl_pg.portfolios(tenant_id,portfolio_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE wl_sources.enablements(
 tenant_id uuid NOT NULL,portfolio_id uuid NOT NULL,plugin_id text NOT NULL,capability text NOT NULL CHECK(capability='FILE_IMPORT'),
 provider_id text NOT NULL,installation_id text NOT NULL,enabled boolean NOT NULL,
 revision bigint NOT NULL CHECK(revision>=1),generation bigint NOT NULL CHECK(generation>=1),
 created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,
 CHECK(pg_catalog.isfinite(created_at) AND pg_catalog.isfinite(updated_at) AND updated_at>=created_at),
 PRIMARY KEY(tenant_id,portfolio_id,plugin_id,capability),
 FOREIGN KEY(tenant_id,portfolio_id) REFERENCES wl_sources.lifecycle_roots(tenant_id,portfolio_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(installation_id,plugin_id,provider_id) REFERENCES wl_sources.installations(id,plugin_id,provider_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE wl_sources.connection_lifecycle(
 tenant_id uuid NOT NULL,portfolio_id uuid NOT NULL,id uuid NOT NULL CHECK(id<>'00000000-0000-0000-0000-000000000000'),
 connection_version text NOT NULL CHECK(connection_version ~ '^[0-9a-f]{64}$'),plugin_id text NOT NULL,provider_id text NOT NULL,
 capability text NOT NULL CHECK(capability='FILE_IMPORT'),installation_id text NOT NULL,
 display_label text NOT NULL CHECK(length(display_label)>=1 AND length(display_label)<=100 AND display_label=btrim(display_label) AND display_label !~ '[[:cntrl:]]'),
 parser_source_alias text CHECK(parser_source_alias IS NULL OR (length(parser_source_alias)>=1 AND length(parser_source_alias)<=160 AND parser_source_alias=btrim(parser_source_alias) AND parser_source_alias !~ '[[:cntrl:]]')),
 enabled boolean NOT NULL,revision bigint NOT NULL CHECK(revision>=1),created_at timestamptz NOT NULL,updated_at timestamptz NOT NULL,
 CHECK(pg_catalog.isfinite(created_at) AND pg_catalog.isfinite(updated_at) AND updated_at>=created_at),
 PRIMARY KEY(tenant_id,portfolio_id,id),UNIQUE(tenant_id,portfolio_id,id,connection_version),
 FOREIGN KEY(tenant_id,portfolio_id,id,connection_version) REFERENCES wl_pg.connections(tenant_id,portfolio_id,id,version) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,portfolio_id,plugin_id,capability) REFERENCES wl_sources.enablements(tenant_id,portfolio_id,plugin_id,capability) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(installation_id,plugin_id,provider_id) REFERENCES wl_sources.installations(id,plugin_id,provider_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE wl_sources.lifecycle_receipts(
 tenant_id uuid NOT NULL,portfolio_id uuid NOT NULL,incarnation uuid NOT NULL CHECK(incarnation<>'00000000-0000-0000-0000-000000000000'),
 restore_epoch bigint NOT NULL CHECK(restore_epoch>=0),operation_id uuid NOT NULL CHECK(operation_id<>'00000000-0000-0000-0000-000000000000'),
 operation_kind text NOT NULL CHECK(operation_kind IN ('SET_ENABLEMENT','CREATE_CONNECTION','UPDATE_CONNECTION')),
 request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),result jsonb NOT NULL CHECK(octet_length(result::text)<=16384),
 created_at timestamptz NOT NULL CHECK(pg_catalog.isfinite(created_at)),PRIMARY KEY(tenant_id,portfolio_id,incarnation,restore_epoch,operation_id),
 FOREIGN KEY(tenant_id,portfolio_id) REFERENCES wl_sources.lifecycle_roots(tenant_id,portfolio_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE wl_sources.lifecycle_audit(
 tenant_id uuid NOT NULL,portfolio_id uuid NOT NULL,incarnation uuid NOT NULL,restore_epoch bigint NOT NULL,operation_id uuid NOT NULL,
 action text NOT NULL CHECK(action IN ('ENABLEMENT_CHANGED','CONNECTION_CREATED','CONNECTION_CHANGED','NO_CHANGE')),
 resource_key text NOT NULL,before_revision bigint NOT NULL CHECK(before_revision>=0),after_revision bigint NOT NULL CHECK(after_revision>=before_revision),
 occurred_at timestamptz NOT NULL CHECK(pg_catalog.isfinite(occurred_at)),PRIMARY KEY(tenant_id,portfolio_id,incarnation,restore_epoch,operation_id),
 FOREIGN KEY(tenant_id,portfolio_id,incarnation,restore_epoch,operation_id)
 REFERENCES wl_sources.lifecycle_receipts(tenant_id,portfolio_id,incarnation,restore_epoch,operation_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX connection_lifecycle_scope ON wl_sources.connection_lifecycle(tenant_id,portfolio_id,plugin_id,capability,id);
CREATE INDEX lifecycle_receipts_created ON wl_sources.lifecycle_receipts(tenant_id,portfolio_id,created_at,operation_id);
CREATE INDEX lifecycle_audit_occurred ON wl_sources.lifecycle_audit(tenant_id,portfolio_id,occurred_at,operation_id);
CREATE INDEX installations_plugin ON wl_sources.installations(plugin_id,id);
REVOKE ALL ON ALL TABLES IN SCHEMA wl_sources FROM PUBLIC;
"""


GUARD_DDL = r"""
CREATE FUNCTION wl_sources.guard_enablement_update_v1() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $source_guard$
DECLARE d pg_catalog.jsonb;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable_source_identity'; END IF;
 IF TG_OP='INSERT' THEN
  IF NOT NEW.enabled OR NEW.revision<>1 OR NEW.generation<>1 THEN RAISE EXCEPTION 'invalid_initial_source'; END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['installation_id','enabled','revision','generation','updated_at']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['installation_id','enabled','revision','generation','updated_at']) OR
     OLD.revision=9223372036854775807 OR OLD.generation=9223372036854775807 OR
     NEW.revision<>OLD.revision+1 OR NEW.generation<>OLD.generation+1 OR
     (NEW.installation_id=OLD.installation_id AND NEW.enabled=OLD.enabled) THEN RAISE EXCEPTION 'invalid_source_transition'; END IF;
 END IF;
 SELECT convert_from(descriptor_bytes,'UTF8')::jsonb INTO d FROM wl_sources.installations
  WHERE id=NEW.installation_id AND plugin_id=NEW.plugin_id AND provider_id=NEW.provider_id;
 IF d IS NULL OR NOT (d->'capabilities' @> '["FILE_IMPORT"]'::jsonb) THEN RAISE EXCEPTION 'invalid_source_binding'; END IF;
 RETURN NEW;
END $source_guard$;
CREATE FUNCTION wl_sources.guard_connection_update_v1() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $source_guard$
DECLARE d pg_catalog.jsonb;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable_source_identity'; END IF;
 IF TG_OP='INSERT' THEN
  IF NOT NEW.enabled OR NEW.revision<>1 THEN RAISE EXCEPTION 'invalid_initial_connection'; END IF;
 ELSE
  IF (to_jsonb(NEW)-ARRAY['installation_id','display_label','enabled','revision','updated_at']) IS DISTINCT FROM
     (to_jsonb(OLD)-ARRAY['installation_id','display_label','enabled','revision','updated_at']) OR
     OLD.revision=9223372036854775807 OR NEW.revision<>OLD.revision+1 OR
     (NEW.installation_id=OLD.installation_id AND NEW.enabled=OLD.enabled AND NEW.display_label=OLD.display_label)
     THEN RAISE EXCEPTION 'invalid_connection_transition'; END IF;
 END IF;
 SELECT convert_from(descriptor_bytes,'UTF8')::jsonb INTO d FROM wl_sources.installations
  WHERE id=NEW.installation_id AND plugin_id=NEW.plugin_id AND provider_id=NEW.provider_id;
 IF d IS NULL OR NOT (d->'capabilities' @> '["FILE_IMPORT"]'::jsonb) OR
    (d->>'alias_policy'='forbidden' AND NEW.parser_source_alias IS NOT NULL) OR
    (d->>'alias_policy'='required' AND NEW.parser_source_alias IS NULL) OR
    NOT EXISTS(SELECT1 FROM wl_pg.connections WHERE tenant_id=NEW.tenant_id AND portfolio_id=NEW.portfolio_id
      AND id=NEW.id AND version=NEW.connection_version AND provider=NEW.provider_id AND kind=NEW.capability)
    THEN RAISE EXCEPTION 'invalid_connection_binding'; END IF;
 RETURN NEW;
END $source_guard$;
REVOKE ALL ON FUNCTION wl_sources.guard_enablement_update_v1() FROM PUBLIC;
REVOKE ALL ON FUNCTION wl_sources.guard_connection_update_v1() FROM PUBLIC;
CREATE TRIGGER immutable_source BEFORE INSERT OR UPDATE OR DELETE ON wl_sources.enablements
 FOR EACH ROW EXECUTE FUNCTION wl_sources.guard_enablement_update_v1();
CREATE TRIGGER immutable_source BEFORE INSERT OR UPDATE OR DELETE ON wl_sources.connection_lifecycle
 FOR EACH ROW EXECUTE FUNCTION wl_sources.guard_connection_update_v1();
""".replace("SELECT1", "SELECT 1")


def table_ddl():
    result = TABLE_DDL + GUARD_DDL
    policy = "tenant_id::text=nullif(current_setting('ledger.tenant_id',true),'') AND portfolio_id::text=nullif(current_setting('ledger.portfolio_id',true),'')"
    for name in TENANT_TABLES:
        result += f"ALTER TABLE wl_sources.{name} ENABLE ROW LEVEL SECURITY;ALTER TABLE wl_sources.{name} FORCE ROW LEVEL SECURITY;CREATE POLICY scope ON wl_sources.{name} USING ({policy}) WITH CHECK ({policy});\n"
    for name in ("installations", "lifecycle_receipts", "lifecycle_audit"):
        result += f"CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON wl_sources.{name} FOR EACH ROW EXECUTE FUNCTION wl_pg.reject_mutation();\n"
    return result


def _canonical_object(values):
    # SQL expressions are closed code constants. Values are already JSONB, so
    # quoted user text is escaped by PostgreSQL, never interpolated as SQL.
    pieces = []
    for name in sorted(values):
        import json
        prefix = ("," if pieces else "{") + json.dumps(name) + ":"
        pieces.extend(["'" + prefix.replace("'", "''") + "'", "coalesce((" + values[name] + ")::text,'null')"])
    return " || ".join(pieces + ["'}'"])


def _assert_effect():
    return "GET DIAGNOSTICS affected=ROW_COUNT;IF affected<>1 THEN RAISE EXCEPTION 'source_effect_failed';END IF;\n"


def _enablement_resource():
    return "pg_catalog.jsonb_build_object('enabled',coalesce(em.enabled,false),'installation_id',em.installation_id,'revision',coalesce(em.revision,0)::text,'generation',coalesce(em.generation,0)::text)"


def _connection_resource():
    return r"""
 SELECT * INTO em FROM wl_sources.enablements WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id
  AND plugin_id=cl.plugin_id AND capability=cl.capability;
 SELECT * INTO ci FROM wl_pg.connections WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id
  AND id=cl.id AND version=cl.connection_version;
 SELECT value INTO availability FROM pg_catalog.jsonb_array_elements(catalog_json->'availability') entry(value)
  WHERE value->>'installation_id'=cl.installation_id;
 -- Resolve the active descriptor by its separately persisted immutable ID.
 SELECT av->>'installation_id' INTO active_id
 FROM pg_catalog.jsonb_array_elements(catalog_json->'availability') available(av)
 JOIN wl_sources.installations installed ON installed.id=av->>'installation_id'
 WHERE installed.plugin_id=cl.plugin_id AND av->>'status'='ACTIVE'
 AND (pg_catalog.convert_from(installed.descriptor_bytes,'UTF8')::jsonb->'capabilities') @> '["FILE_IMPORT"]'::jsonb;
 source_reason:=NULL;
 IF NOT cl.enabled THEN source_status:='DISABLED';
 ELSIF NOT coalesce(em.enabled,false) THEN source_status:='SOURCE_DISABLED';
 ELSIF ci.generation=9223372036854775807 OR coalesce(em.generation,0)=9223372036854775807 OR root_revision=9223372036854775807
  OR (availability->>'availability_generation')::bigint=9223372036854775807 THEN source_status:='UNAVAILABLE';source_reason:='source_counter_exhausted';
 ELSIF active_id IS NULL OR availability->>'status'='REVOKED' THEN source_status:='UNAVAILABLE';source_reason:='source_unavailable';
 ELSIF cl.installation_id<>active_id OR em.installation_id<>cl.installation_id THEN source_status:='CONFIRMATION_REQUIRED';
 ELSE source_status:='ENABLED';END IF;
 resource:=pg_catalog.jsonb_build_object('id',cl.id::text,'connection_version',cl.connection_version,
  'plugin_id',cl.plugin_id,'provider_id',cl.provider_id,'capability',cl.capability,'installation_id',cl.installation_id,
  'availability_generation',availability->>'availability_generation','display_label',cl.display_label,'parser_source_alias',cl.parser_source_alias,
  'enabled',cl.enabled,'revision',cl.revision::text,'generation',ci.generation::text,'status',source_status,'reason',source_reason);
""".replace("SELECT1", "SELECT 1")


def _payload_shape(names):
    keys = ",".join("'"+name+"'" for name in sorted(names))
    fail=identity.fail('instance_not_ready')
    result="IF pg_catalog.jsonb_typeof(p_payload) IS DISTINCT FROM 'object' THEN "+fail+" END IF;\n"
    result+="IF ARRAY(SELECT pg_catalog.jsonb_object_keys(p_payload) ORDER BY 1) IS DISTINCT FROM ARRAY["+keys+"]::text[] THEN "+fail+" END IF;\n"
    uuid_pattern="'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"
    whitespace=r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'"
    controls=r"U&'[\0001-\001F\007F-\009F]'"
    def checked(condition):
        return "IF ("+condition+") IS NOT TRUE THEN "+fail+" END IF;\n"
    def token(expression):
        return "pg_catalog.jsonb_typeof("+expression+")='string' AND ("+expression+"#>>'{}') ~ '^(0|[1-9][0-9]{0,18})$' AND (length("+expression+"#>>'{}')<19 OR ("+expression+"#>>'{}') COLLATE \"C\"<='9223372036854775807' COLLATE \"C\")"
    def uuid_value(expression):
        text="("+expression+"#>>'{}')"
        return "pg_catalog.jsonb_typeof("+expression+")='string' AND length("+text+")=36 AND "+text+" ~ "+uuid_pattern+" AND "+text+"<>'00000000-0000-0000-0000-000000000000'"
    for name in sorted(names):
        expression="p_payload->'"+name+"'";text="(p_payload->>'"+name+"')"
        if name in {'operation_id','connection_id'}:
            result+=checked(uuid_value(expression))
        elif name in {'expected_revision','catalog_revision','state_revision'}:
            nullable=name!='expected_revision'
            result+=("IF "+expression+"<>'null'::jsonb THEN " if nullable else "")+checked(token(expression))+("END IF;\n" if nullable else "")
        elif name=='expected_realm':
            result+="IF "+expression+"<>'null'::jsonb THEN "+checked("pg_catalog.jsonb_typeof("+expression+")='object'")
            result+=checked("ARRAY(SELECT pg_catalog.jsonb_object_keys("+expression+") ORDER BY 1)=ARRAY['incarnation','restore_epoch']::text[]")
            result+=checked(uuid_value("("+expression+")->'incarnation'"))+checked(token("("+expression+")->'restore_epoch'"))+"END IF;\n"
        elif name=='enabled':
            result+=checked("pg_catalog.jsonb_typeof("+expression+")='boolean'")
        elif name=='installation_id':
            result+="IF "+expression+"<>'null'::jsonb THEN "+checked("pg_catalog.jsonb_typeof("+expression+")='string' AND length("+text+")=64 AND "+text+" ~ '^[0-9a-f]{64}$'")+"END IF;\n"
        elif name=='plugin_id':
            result+=checked("pg_catalog.jsonb_typeof("+expression+")='string' AND length("+text+") BETWEEN 1 AND 64 AND "+text+" ~ '^[a-z][a-z0-9_.-]{0,63}$'")
        elif name=='capability':
            result+=checked("pg_catalog.jsonb_typeof("+expression+")='string' AND "+text+" IN ('FILE_IMPORT','PULL_API')")
        elif name in {'display_label','parser_source_alias'}:
            nullable=name=='parser_source_alias';maximum=160 if nullable else 100
            result+=("IF "+expression+"<>'null'::jsonb THEN " if nullable else "")
            result+=checked("pg_catalog.jsonb_typeof("+expression+")='string' AND length("+text+") BETWEEN 1 AND "+str(maximum)+" AND "+text+"=pg_catalog.btrim("+text+","+whitespace+") AND "+text+" !~ "+controls)
            result+=("END IF;\n" if nullable else "")
        elif name=='after':
            result+="IF "+expression+"<>'null'::jsonb THEN "+checked("pg_catalog.jsonb_typeof("+expression+")='string' AND length("+text+") BETWEEN 1 AND 64")+"END IF;\n"
        elif name=='limit':
            result+=checked("pg_catalog.jsonb_typeof("+expression+")='number' AND "+text+" ~ '^[1-9][0-9]{0,2}$'")
    return result


def _function(name, body):
    if name not in GATEWAY:
        raise ValueError("Unknown source callable")
    return """CREATE FUNCTION wl_sources."""+name+"""(p_digest pg_catalog.text,p_user pg_catalog.uuid,p_version pg_catalog.int8,
 p_realm pg_catalog.jsonb,p_catalog_digest pg_catalog.text,p_payload pg_catalog.jsonb) RETURNS pg_catalog.jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $sources$
DECLARE
 st wl_pg.instance_state%ROWTYPE;a wl_identity.instance_auth_state%ROWTYPE;
 u wl_identity.users%ROWTYPE;ss wl_identity.sessions%ROWTYPE;
 cs wl_sources.catalog_state%ROWTYPE;rt wl_sources.lifecycle_roots%ROWTYPE;
 em wl_sources.enablements%ROWTYPE;cl wl_sources.connection_lifecycle%ROWTYPE;ci wl_pg.connections%ROWTYPE;
 receipt wl_sources.lifecycle_receipts%ROWTYPE;
 n pg_catalog.timestamptz;root_revision pg_catalog.int8;before_revision pg_catalog.int8;resource_revision pg_catalog.int8;
 affected pg_catalog.int4;page_limit pg_catalog.int4;counted pg_catalog.int4;
 catalog_json pg_catalog.jsonb;definition pg_catalog.jsonb;descriptor pg_catalog.jsonb;active_descriptor pg_catalog.jsonb;
 availability pg_catalog.jsonb;resource pg_catalog.jsonb;items pg_catalog.jsonb;capabilities pg_catalog.jsonb;cap_resource pg_catalog.jsonb;
 saved pg_catalog.jsonb;body_json pg_catalog.jsonb;public_realm pg_catalog.jsonb;connection_body pg_catalog.jsonb;
 plugin pg_catalog.text;source_capability pg_catalog.text;active_id pg_catalog.text;pin pg_catalog.text;provider pg_catalog.text;
 source_status pg_catalog.text;source_reason pg_catalog.text;after_key pg_catalog.text;last_key pg_catalog.text;
 operation_kind pg_catalog.text;resource_path pg_catalog.text;request_text pg_catalog.text;request_digest pg_catalog.text;
 new_connection_version pg_catalog.text;connection_text pg_catalog.text;rid pg_catalog.uuid;
 changed pg_catalog.bool;auth_changed pg_catalog.bool;needs_authorization pg_catalog.bool;more pg_catalog.bool;
BEGIN
"""+body+"\nEND\n$sources$;\nREVOKE ALL ON FUNCTION "+signature(name)+" FROM PUBLIC;\n"


def _live_guard(*, mutation):
    mode = "UPDATE" if mutation else "SHARE"
    return identity.GUARD.replace("'0002_identity'", "'0003_source_lifecycle'")+identity.user_lock("p_user")+identity.session_lock("p_digest")+f"""
 SELECT * INTO cs FROM wl_sources.catalog_state WHERE id=1 FOR SHARE;
 PERFORM1 FROM wl_pg.portfolios WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id FOR KEY SHARE;
 SELECT * INTO rt FROM wl_sources.lifecycle_roots WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id FOR {mode};
 PERFORM1 FROM wl_sources.enablements WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id ORDER BY plugin_id,capability FOR {mode};
 PERFORM1 FROM wl_pg.connections WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id ORDER BY id,version FOR {mode};
 PERFORM1 FROM wl_sources.connection_lifecycle WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id ORDER BY id FOR {mode};
""".replace("PERFORM1", "PERFORM 1")+("PERFORM 1 FROM wl_sources.lifecycle_receipts WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND incarnation=st.incarnation AND restore_epoch=st.restore_epoch AND operation_id::text=p_payload->>'operation_id' FOR UPDATE;\n" if mutation else "")+identity.CLOCK+"""
 IF p_realm IS DISTINCT FROM """+identity.realm()+""" THEN """+identity.fail('instance_not_ready')+""" END IF;
 IF cs.id IS NULL OR p_catalog_digest IS DISTINCT FROM cs.digest THEN """+identity.fail('source_catalog_unavailable')+""" END IF;
"""+identity.check_user(version="p_version")+identity.check_session()+"""
 IF ss.user_id<>u.id OR ss.credential_version<>u.credential_version THEN """+identity.fail('session_changed')+""" END IF;
 PERFORM pg_catalog.set_config('ledger.tenant_id',u.id::text,true),pg_catalog.set_config('ledger.portfolio_id',u.portfolio_id::text,true);
 root_revision:=coalesce(rt.revision,0);
 catalog_json:=pg_catalog.convert_from(cs.bundle_bytes,'UTF8')::jsonb;
 public_realm:=pg_catalog.jsonb_build_object('incarnation',st.incarnation::text,'restore_epoch',st.restore_epoch::text);
"""


def _page_guard():
    return _payload_shape(("after","limit","catalog_revision","state_revision","expected_realm"))+"""
 IF (pg_catalog.jsonb_typeof(p_payload->'limit')='number' AND (p_payload->>'limit') ~ '^[1-9][0-9]{0,2}$'
 AND (p_payload->>'limit')::integer BETWEEN 1 AND 100) IS NOT TRUE THEN """+identity.fail('instance_not_ready')+""" END IF;
 page_limit:=(p_payload->>'limit')::integer;after_key:=p_payload->>'after';
 IF after_key IS NOT NULL AND ((p_payload->>'catalog_revision') IS DISTINCT FROM cs.revision::text OR
 (p_payload->>'state_revision') IS DISTINCT FROM root_revision::text OR p_payload->'expected_realm' IS DISTINCT FROM public_realm)
 THEN """+identity.fail('source_repreview_required')+""" END IF;
 IF after_key IS NULL AND (p_payload->>'catalog_revision' IS NOT NULL OR p_payload->>'state_revision' IS NOT NULL OR
 p_payload->'expected_realm' IS DISTINCT FROM 'null'::jsonb) THEN """+identity.fail('instance_not_ready')+""" END IF;
 items:='[]'::jsonb;more:=false;last_key:=NULL;counted:=0;
"""


def _connection_reads(name):
    body = _live_guard(mutation=False)
    if name == "sources_connection_v1":
        body += _payload_shape(("connection_id",))+"""
 SELECT * INTO cl FROM wl_sources.connection_lifecycle WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND id=(p_payload->>'connection_id')::uuid;
 IF cl.id IS NULL THEN """+identity.fail('not_found')+""" END IF;
"""+_connection_resource()+identity.success("pg_catalog.jsonb_build_object('resource',resource,'catalog_revision',cs.revision::text,'state_revision',root_revision::text,'realm',public_realm)")
    else:
        body += _page_guard()+"IF after_key IS NOT NULL AND (length(after_key)<>36 OR after_key !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' OR after_key='00000000-0000-0000-0000-000000000000') THEN "+identity.fail('instance_not_ready')+" END IF;\n"+"""
 FOR cl IN SELECT * FROM wl_sources.connection_lifecycle WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id
 AND (after_key IS NULL OR id>after_key::uuid) ORDER BY id LIMIT page_limit+1 LOOP
  IF counted=page_limit THEN more:=true;EXIT;END IF;
"""+_connection_resource()+"""
  items:=items||pg_catalog.jsonb_build_array(resource);last_key:=cl.id::text;counted:=counted+1;
 END LOOP;
"""+identity.success("pg_catalog.jsonb_build_object('items',items,'next_after',CASE WHEN more THEN last_key ELSE NULL END,'catalog_revision',cs.revision::text,'state_revision',root_revision::text,'realm',public_realm)")
    return _function(name,body)


def _catalog_read():
    body = _live_guard(mutation=False)+_page_guard()+"IF after_key IS NOT NULL AND after_key !~ '^[a-z][a-z0-9_.-]{0,63}$' THEN "+identity.fail('instance_not_ready')+" END IF;\n"+"""
 FOR definition IN SELECT value FROM pg_catalog.jsonb_array_elements(catalog_json->'definitions') entry(value)
 WHERE after_key IS NULL OR (value->>'plugin_id') COLLATE "C">after_key COLLATE "C"
 ORDER BY (value->>'plugin_id') COLLATE "C" LIMIT page_limit+1 LOOP
  IF counted=page_limit THEN more:=true;EXIT;END IF;
  plugin:=definition->>'plugin_id';capabilities:='[]'::jsonb;
  FOR source_capability IN SELECT DISTINCT cap.value#>>'{}' FROM wl_sources.installations installed,
    LATERAL pg_catalog.jsonb_array_elements(pg_catalog.convert_from(installed.descriptor_bytes,'UTF8')::jsonb->'capabilities') cap(value)
    WHERE installed.plugin_id=plugin ORDER BY 1 LOOP
   active_id:=NULL;active_descriptor:=NULL;availability:=NULL;
   SELECT av->>'installation_id',pg_catalog.convert_from(installed.descriptor_bytes,'UTF8')::jsonb,av
    INTO active_id,active_descriptor,availability
    FROM pg_catalog.jsonb_array_elements(catalog_json->'availability') available(av)
    JOIN wl_sources.installations installed ON installed.id=av->>'installation_id'
    WHERE installed.plugin_id=plugin AND av->>'status'='ACTIVE' AND
      (pg_catalog.convert_from(installed.descriptor_bytes,'UTF8')::jsonb->'capabilities') @> pg_catalog.jsonb_build_array(source_capability);
   SELECT * INTO em FROM wl_sources.enablements WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND plugin_id=plugin AND wl_sources.enablements.capability=source_capability;
   source_reason:=NULL;
   IF source_capability='PULL_API' THEN source_status:='UNAVAILABLE';source_reason:='source_capability_unavailable';
   ELSIF NOT coalesce(em.enabled,false) THEN source_status:='DISABLED';
   ELSIF root_revision=9223372036854775807 OR em.generation=9223372036854775807 OR
    (availability->>'availability_generation')::bigint=9223372036854775807 OR EXISTS(
      SELECT 1 FROM pg_catalog.jsonb_array_elements(catalog_json->'availability') selected(entry)
      WHERE entry->>'installation_id'=em.installation_id AND (entry->>'availability_generation')::bigint=9223372036854775807)
    THEN source_status:='UNAVAILABLE';source_reason:='source_counter_exhausted';
   ELSIF active_id IS NULL OR EXISTS(
      SELECT 1 FROM pg_catalog.jsonb_array_elements(catalog_json->'availability') selected(entry)
      WHERE entry->>'installation_id'=em.installation_id AND entry->>'status'='REVOKED')
    THEN source_status:='UNAVAILABLE';source_reason:='source_unavailable';
   ELSIF em.installation_id<>active_id THEN source_status:='CONFIRMATION_REQUIRED';ELSE source_status:='ENABLED';END IF;
   cap_resource:=pg_catalog.jsonb_build_object('capability',source_capability,'active_installation_id',active_id,
     'availability_generation',availability->>'availability_generation','adapter_id',active_descriptor->>'adapter_id',
     'package_version',active_descriptor->>'package_version','format_versions',coalesce(active_descriptor->'format_versions','[]'::jsonb),
     'domain_contract_version',1,'parser_api_version',active_descriptor->'parser_api_version','enablement',"""+_enablement_resource()+""",
     'status',source_status,'reason',source_reason,'connection_count',(SELECT count(*) FROM wl_sources.connection_lifecycle
      WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND plugin_id=plugin AND wl_sources.connection_lifecycle.capability=source_capability));
   capabilities:=capabilities||pg_catalog.jsonb_build_array(cap_resource);
  END LOOP;
  items:=items||pg_catalog.jsonb_build_array(definition||pg_catalog.jsonb_build_object('capabilities',capabilities));last_key:=plugin;counted:=counted+1;
 END LOOP;
"""+identity.success("pg_catalog.jsonb_build_object('items',items,'next_after',CASE WHEN more THEN last_key ELSE NULL END,'catalog_revision',cs.revision::text,'state_revision',root_revision::text,'realm',public_realm)")
    return _function("sources_catalog_v1",body)


def _mutator(name):
    kinds = {"set_source_enablement_v1": "SET_ENABLEMENT", "create_source_connection_v1": "CREATE_CONNECTION", "update_source_connection_v1": "UPDATE_CONNECTION"}
    operation = kinds[name]
    common = {"operation_id", "expected_revision", "expected_realm"}
    if operation == "SET_ENABLEMENT":
        names = common | {"plugin_id", "capability", "enabled", "installation_id"}
        client_names = common | {"enabled", "installation_id"}
        path = "'/api/v2/sources/'||(p_payload->>'plugin_id')||'/capabilities/'||(p_payload->>'capability')"
    elif operation == "CREATE_CONNECTION":
        names = common | {"plugin_id", "capability", "installation_id", "display_label", "parser_source_alias"}
        client_names = names
        path = "'/api/v2/source-connections'"
    else:
        names = common | {"connection_id", "enabled", "installation_id", "display_label"}
        client_names = names - {"connection_id"}
        path = "'/api/v2/source-connections/'||(p_payload->>'connection_id')"
    body = _live_guard(mutation=True) + _payload_shape(names)
    if operation=='SET_ENABLEMENT':
        body+="IF (p_payload->>'enabled')::boolean <> ((p_payload->>'installation_id') IS NOT NULL) THEN "+identity.fail('instance_not_ready')+" END IF;\n"
    else:
        body+="IF p_payload->>'installation_id' IS NULL THEN "+identity.fail('instance_not_ready')+" END IF;\n"
    if operation=='CREATE_CONNECTION':
        body+="IF p_payload->>'expected_revision'<>'0' THEN "+identity.fail('instance_not_ready')+" END IF;\n"

    realm_text = _canonical_object({"incarnation": "p_payload->'expected_realm'->'incarnation'", "restore_epoch": "p_payload->'expected_realm'->'restore_epoch'"})
    body_values = {key: "p_payload->'"+key+"'" for key in client_names}
    body_values["expected_realm"] = realm_text
    request_text = _canonical_object({"body": _canonical_object(body_values), "operation_kind": "pg_catalog.to_jsonb(operation_kind)", "resource_path": "pg_catalog.to_jsonb(resource_path)"})
    body += """
 IF p_payload->'expected_realm' IS DISTINCT FROM public_realm THEN """+identity.fail('source_repreview_required')+""" END IF;
 IF (pg_catalog.jsonb_typeof(p_payload->'operation_id')='string' AND
 (p_payload->>'operation_id') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
 AND p_payload->>'operation_id'<>'00000000-0000-0000-0000-000000000000' AND
 pg_catalog.jsonb_typeof(p_payload->'expected_revision')='string' AND (p_payload->>'expected_revision') ~ '^(0|[1-9][0-9]{0,18})$'
 AND (length(p_payload->>'expected_revision')<19 OR (p_payload->>'expected_revision') COLLATE "C"<='9223372036854775807' COLLATE "C")) IS NOT TRUE
 THEN """+identity.fail('instance_not_ready')+""" END IF;
 operation_kind:='"""+operation+"';resource_path:="+path+";request_text:="+request_text+";\n"
    body += """
 request_digest:=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(request_text,'UTF8')),'hex');
 SELECT * INTO receipt FROM wl_sources.lifecycle_receipts WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id
  AND incarnation=st.incarnation AND restore_epoch=st.restore_epoch AND operation_id=(p_payload->>'operation_id')::uuid FOR UPDATE;
 IF receipt.operation_id IS NOT NULL THEN
  IF receipt.request_digest<>request_digest THEN """+identity.fail('source_idempotency_conflict')+""" END IF;
 """+identity.success("receipt.result||pg_catalog.jsonb_build_object('replayed',true,'representation','historical')")+""" END IF;
 changed:=false;auth_changed:=false;
"""
    if operation != "UPDATE_CONNECTION":
        body += """
 plugin:=p_payload->>'plugin_id';source_capability:=p_payload->>'capability';
 IF source_capability='PULL_API' THEN """+identity.fail('source_capability_unavailable')+""" END IF;
 IF source_capability IS DISTINCT FROM 'FILE_IMPORT' THEN """+identity.fail('instance_not_ready')+""" END IF;
 SELECT value INTO definition FROM pg_catalog.jsonb_array_elements(catalog_json->'definitions') entry(value) WHERE value->>'plugin_id'=plugin;
 IF definition IS NULL THEN """+identity.fail('not_found')+""" END IF;
 provider:=definition->>'provider_id';
 SELECT * INTO em FROM wl_sources.enablements WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND plugin_id=plugin AND wl_sources.enablements.capability=source_capability;
"""
    else:
        body += """
 SELECT * INTO cl FROM wl_sources.connection_lifecycle WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND id=(p_payload->>'connection_id')::uuid;
 IF cl.id IS NULL THEN """+identity.fail('not_found')+""" END IF;
 plugin:=cl.plugin_id;source_capability:=cl.capability;provider:=cl.provider_id;
 SELECT * INTO em FROM wl_sources.enablements WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND plugin_id=plugin AND wl_sources.enablements.capability=source_capability;
 SELECT * INTO ci FROM wl_pg.connections WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND id=cl.id AND version=cl.connection_version;
"""
    current_revision = "coalesce(em.revision,0)" if operation == "SET_ENABLEMENT" else ("0" if operation == "CREATE_CONNECTION" else "cl.revision")
    body += "before_revision:="+current_revision+";IF (p_payload->>'expected_revision')::bigint<>before_revision THEN "+identity.fail('source_revision_conflict')+" END IF;\n"
    if operation == "SET_ENABLEMENT":
        body += """
 pin:=CASE WHEN (p_payload->>'enabled')::boolean THEN p_payload->>'installation_id' ELSE em.installation_id END;
 changed:=coalesce(em.enabled,false) IS DISTINCT FROM (p_payload->>'enabled')::boolean OR em.installation_id IS DISTINCT FROM pin;
 auth_changed:=changed;needs_authorization:=(p_payload->>'enabled')::boolean;
"""
    elif operation == "CREATE_CONNECTION":
        body += "pin:=p_payload->>'installation_id';changed:=true;auth_changed:=true;needs_authorization:=true;\n"
    else:
        body += """
 pin:=p_payload->>'installation_id';auth_changed:=cl.enabled IS DISTINCT FROM (p_payload->>'enabled')::boolean OR cl.installation_id IS DISTINCT FROM pin;
 changed:=auth_changed OR cl.display_label IS DISTINCT FROM p_payload->>'display_label';
 needs_authorization:=(NOT cl.enabled AND (p_payload->>'enabled')::boolean) OR cl.installation_id IS DISTINCT FROM pin;
"""
    body += """
 IF needs_authorization THEN
  SELECT pg_catalog.convert_from(descriptor_bytes,'UTF8')::jsonb INTO descriptor FROM wl_sources.installations
   WHERE id=pin AND plugin_id=plugin AND provider_id=provider;
  IF descriptor IS NULL OR NOT (descriptor->'capabilities' @> '["FILE_IMPORT"]'::jsonb) THEN """+identity.fail('source_context_incompatible')+""" END IF;
  SELECT value INTO availability FROM pg_catalog.jsonb_array_elements(catalog_json->'availability') entry(value) WHERE value->>'installation_id'=pin;
  IF availability IS NULL OR availability->>'status'<>'ACTIVE' THEN """+identity.fail('source_unavailable')+""" END IF;
  IF (availability->>'availability_generation')::bigint=9223372036854775807 THEN """+identity.fail('source_counter_exhausted')+""" END IF;
 END IF;
"""
    if operation != "SET_ENABLEMENT":
        body += """
 IF needs_authorization AND (NOT coalesce(em.enabled,false) OR em.installation_id IS DISTINCT FROM pin) THEN """+identity.fail('source_context_incompatible')+""" END IF;
 IF needs_authorization AND em.generation=9223372036854775807 THEN """+identity.fail('source_counter_exhausted')+""" END IF;
"""
        alias = "p_payload->>'parser_source_alias'" if operation == "CREATE_CONNECTION" else "cl.parser_source_alias"
        body += "IF needs_authorization AND ((descriptor->>'alias_policy'='required' AND ("+alias+") IS NULL) OR (descriptor->>'alias_policy'='forbidden' AND ("+alias+") IS NOT NULL)) THEN "+identity.fail('source_context_incompatible')+" END IF;\n"
    if operation == "CREATE_CONNECTION":
        body += "IF (SELECT count(DISTINCT id) FROM wl_pg.connections WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id)>=256 THEN "+identity.fail('source_capacity_reached')+" END IF;\n"
    if operation == "SET_ENABLEMENT":
        counter_checks = "coalesce(em.revision,0)=9223372036854775807 OR coalesce(em.generation,0)=9223372036854775807"
    elif operation == "CREATE_CONNECTION":
        counter_checks = "false"
    else:
        counter_checks = "cl.revision=9223372036854775807 OR (auth_changed AND ci.generation=9223372036854775807)"
    body += "IF changed AND (root_revision=9223372036854775807 OR "+counter_checks+") THEN "+identity.fail('source_counter_exhausted')+" END IF;\n"
    body += """
 IF rt.tenant_id IS NULL THEN INSERT INTO wl_sources.lifecycle_roots VALUES(u.id,u.portfolio_id,0,n);
"""+_assert_effect()+" END IF;\n"
    if operation == "SET_ENABLEMENT":
        body += """
 IF changed THEN
  IF em.tenant_id IS NULL THEN INSERT INTO wl_sources.enablements VALUES(u.id,u.portfolio_id,plugin,source_capability,provider,pin,true,1,1,n,n);
  ELSE UPDATE wl_sources.enablements SET enabled=(p_payload->>'enabled')::boolean,installation_id=pin,revision=revision+1,generation=generation+1,updated_at=n
   WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND plugin_id=plugin AND wl_sources.enablements.capability=source_capability;END IF;
"""+_assert_effect()+"""
 END IF;
 SELECT * INTO em FROM wl_sources.enablements WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND plugin_id=plugin AND wl_sources.enablements.capability=source_capability;
 resource:="""+_enablement_resource()+";\n"
    elif operation == "CREATE_CONNECTION":
        conn_id = _canonical_object({"kind": "'\"connection\"'::jsonb", "portfolio_id": "pg_catalog.to_jsonb(u.portfolio_id::text)", "tenant_id": "pg_catalog.to_jsonb(u.id::text)", "value": "pg_catalog.to_jsonb(rid::text)"})
        declaration = _canonical_object({"id":conn_id,"kind":"'\"FILE_IMPORT\"'::jsonb","provider":"pg_catalog.to_jsonb(provider)"})
        body += """
 rid:=pg_catalog.gen_random_uuid();
 IF EXISTS(SELECT1 FROM wl_pg.connections WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND id=rid) THEN """+identity.fail('source_connection_conflict')+" END IF;\nconnection_text:="+declaration+";\n"
        body += """
 new_connection_version:=pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(connection_text,'UTF8')),'hex');connection_body:=connection_text::jsonb;
 INSERT INTO wl_pg.connections(tenant_id,portfolio_id,id,version,body,provider,provider_digest,kind,generation)
 VALUES(u.id,u.portfolio_id,rid,new_connection_version,connection_body,provider,pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(provider,'UTF8')),'hex'),'FILE_IMPORT',0);
"""+_assert_effect()+"""
 INSERT INTO wl_sources.connection_lifecycle VALUES(u.id,u.portfolio_id,rid,new_connection_version,plugin,provider,source_capability,pin,p_payload->>'display_label',p_payload->>'parser_source_alias',true,1,n,n);
"""+_assert_effect()+"""
 SELECT * INTO cl FROM wl_sources.connection_lifecycle WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND id=rid;
"""
    else:
        body += """
 IF changed THEN
  IF auth_changed THEN UPDATE wl_pg.connections SET generation=generation+1 WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND id=cl.id AND version=cl.connection_version;
"""+_assert_effect()+""" END IF;
  UPDATE wl_sources.connection_lifecycle SET installation_id=pin,display_label=p_payload->>'display_label',enabled=(p_payload->>'enabled')::boolean,revision=revision+1,updated_at=n
  WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND id=cl.id;
"""+_assert_effect()+"""
 END IF;
 SELECT * INTO cl FROM wl_sources.connection_lifecycle WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id AND id=(p_payload->>'connection_id')::uuid;
"""
    body += """
 IF changed THEN UPDATE wl_sources.lifecycle_roots SET revision=revision+1 WHERE tenant_id=u.id AND portfolio_id=u.portfolio_id;
"""+_assert_effect()+"root_revision:=root_revision+1;END IF;\n"
    if operation != "SET_ENABLEMENT":
        body += _connection_resource()
    body += """
 saved:=pg_catalog.jsonb_build_object('operation_id',p_payload->>'operation_id','changed',changed,'resource',resource,
 'catalog_revision',cs.revision::text,'state_revision',root_revision::text,'realm',public_realm);
 INSERT INTO wl_sources.lifecycle_receipts VALUES(u.id,u.portfolio_id,st.incarnation,st.restore_epoch,(p_payload->>'operation_id')::uuid,operation_kind,request_digest,saved,n);
"""+_assert_effect()+"""
 INSERT INTO wl_sources.lifecycle_audit VALUES(u.id,u.portfolio_id,st.incarnation,st.restore_epoch,(p_payload->>'operation_id')::uuid,
 CASE WHEN NOT changed THEN 'NO_CHANGE' WHEN operation_kind='SET_ENABLEMENT' THEN 'ENABLEMENT_CHANGED' WHEN operation_kind='CREATE_CONNECTION' THEN 'CONNECTION_CREATED' ELSE 'CONNECTION_CHANGED' END,
 resource_path,before_revision,(resource->>'revision')::bigint,n);
"""+_assert_effect()+identity.success("saved||pg_catalog.jsonb_build_object('replayed',false,'representation','committed')")
    return _function(name,body.replace("SELECT1", "SELECT 1").replace("ORDER BY1", "ORDER BY 1"))


def gateway_ddl():
    return (_catalog_read()+_connection_reads("sources_connections_v1")+
            _connection_reads("sources_connection_v1")+"\n".join(_mutator(name) for name in GATEWAY[3:]))


def ddl():
    return table_ddl()+identity_replacements()+gateway_ddl()
