"""Reviewed PostgreSQL18 schema fragments for the isolated candidate foundation."""
SCHEMA = "wl_pg"

HELPERS = r"""
CREATE FUNCTION wl_pg.decimal_token_v1(token text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET search_path=pg_catalog AS $$
DECLARE unsigned text; whole text; fraction text;
BEGIN
 IF octet_length(token) NOT BETWEEN 1 AND 256 THEN RETURN false; END IF;
 IF token COLLATE "C" ~ '[^0-9.-]' OR NOT (token COLLATE "C" ~ '^-?(0|[1-9][0-9]*)([.][0-9]+)?$') THEN RETURN false; END IF;
 unsigned := CASE WHEN left(token,1)='-' THEN substring(token FROM 2) ELSE token END;
 whole := split_part(unsigned,'.',1); fraction := split_part(unsigned,'.',2);
 RETURN length(btrim(whole||fraction,'0'))<=38 AND length(rtrim(fraction,'0'))<=24 AND length(ltrim(whole,'0'))<=38;
END $$;
CREATE FUNCTION wl_pg.decimal_pair_v1(token text,value numeric) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE SET search_path=pg_catalog AS $$
BEGIN
 IF token IS NULL THEN RETURN value IS NULL; END IF;
 IF value IS NULL OR wl_pg.decimal_token_v1(token) IS NOT TRUE THEN RETURN false; END IF;
 IF value IN ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric) THEN RETURN false; END IF;
 RETURN value=token::numeric;
END $$;
CREATE FUNCTION wl_pg.quantity_pair_v1(token text,value numeric,satoshi boolean) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE SET search_path=pg_catalog AS $$
BEGIN
 IF satoshi IS NULL OR wl_pg.decimal_pair_v1(token,value) IS NOT TRUE THEN RETURN false; END IF;
 IF token IS NULL OR NOT satoshi THEN RETURN true; END IF;
 RETURN length(rtrim(split_part(token,'.',2),'0'))<=8;
END $$;
CREATE FUNCTION wl_pg.reject_mutation() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'immutable_candidate'; END $$;
CREATE FUNCTION wl_pg.connection_generation_only() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-'generation') IS DISTINCT FROM (to_jsonb(OLD)-'generation') OR NEW.generation<OLD.generation THEN
  RAISE EXCEPTION 'immutable_connection';
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION wl_pg.job_request_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF (to_jsonb(NEW)-ARRAY['status','attempt','fencing_token','worker_id','lease_expires_at','available_at','error_code','cancel_requested','lease_seconds']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['status','attempt','fencing_token','worker_id','lease_expires_at','available_at','error_code','cancel_requested','lease_seconds']) OR
    NEW.attempt<OLD.attempt OR NEW.fencing_token<OLD.fencing_token THEN RAISE EXCEPTION 'immutable_job_request'; END IF;
 RETURN NEW;
END $$;
"""

SCOPE = "tenant_id uuid NOT NULL,portfolio_id uuid NOT NULL"
PRIVATE_TABLES = []
IMMUTABLE_TABLES = []


def scope_fk(table, local="id,version", remote=None):
    left = "tenant_id,portfolio_id" + ("," + local if local else "")
    right = "tenant_id,portfolio_id" + ("," + (remote or local) if local else "")
    return f"FOREIGN KEY({left}) REFERENCES wl_pg.{table}({right}) DEFERRABLE INITIALLY DEFERRED"


def money(name):
    return f"""{name}_token text,{name}_value numeric,{name}_currency text,
 CHECK(wl_pg.decimal_pair_v1({name}_token,{name}_value) IS TRUE),
 CHECK((({name}_token IS NULL AND {name}_currency IS NULL) OR
       ({name}_token IS NOT NULL AND length({name}_currency)=3 AND {name}_currency COLLATE "C" ~ '^[A-Z]{{3}}$')) IS TRUE)"""


def moment(prefix=""):
    return f"""{prefix}time_tag text,{prefix}time_token text,{prefix}time_zone text,
 {prefix}time_utc timestamptz,{prefix}time_detail jsonb,{prefix}time_index text NOT NULL,
 CHECK({prefix}time_index IN ('unknown','date_only','indexed','unindexable')),
 CHECK((({prefix}time_tag IS NULL AND {prefix}time_token IS NULL AND {prefix}time_utc IS NULL AND {prefix}time_index='unknown') OR
 ({prefix}time_tag='date_only' AND {prefix}time_token IS NOT NULL AND {prefix}time_utc IS NULL AND {prefix}time_index='date_only') OR
 ({prefix}time_tag IN ('instant','legacy_datetime') AND {prefix}time_token IS NOT NULL AND
 (({prefix}time_index='indexed' AND {prefix}time_utc IS NOT NULL) OR ({prefix}time_index='unindexable' AND {prefix}time_utc IS NULL)))) IS TRUE)"""


def quantity():
    return """account_id uuid NOT NULL,account_version text NOT NULL,
 instrument_id uuid NOT NULL,instrument_version text NOT NULL,requires_satoshi boolean NOT NULL,
 quantity_token text NOT NULL,quantity_value numeric NOT NULL,
 CHECK(wl_pg.quantity_pair_v1(quantity_token,quantity_value,requires_satoshi) IS TRUE),
 FOREIGN KEY(tenant_id,portfolio_id,account_id,account_version)
 REFERENCES wl_pg.accounts(tenant_id,portfolio_id,id,version) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,portfolio_id,instrument_id,instrument_version,requires_satoshi)
 REFERENCES wl_pg.instruments(tenant_id,portfolio_id,id,version,requires_satoshi) DEFERRABLE INITIALLY DEFERRED"""


def ddl():
    """Return pure DDL text; only the explicit operator migration executes it."""
    statements=[HELPERS]
    private=[];immutable=[]
    def table(name, body, *, frozen=False):
        private.append(name)
        if frozen: immutable.append(name)
        import re
        uuids=set(re.findall(r"(?:^|,)\s*([a-z_]+) uuid",body))
        checks=''.join(f",CHECK({field} IS NULL OR {field}<>'00000000-0000-0000-0000-000000000000')" for field in sorted(uuids))
        statements.append(f"CREATE TABLE wl_pg.{name}({SCOPE},{body}{checks});")
    statements.append("""CREATE TABLE wl_pg.instance_state(id smallint PRIMARY KEY CHECK(id=1),
 incarnation uuid NOT NULL CHECK(incarnation<>'00000000-0000-0000-0000-000000000000'),
 restore_epoch bigint NOT NULL CHECK(restore_epoch>=0),ready boolean NOT NULL);""")
    table('tenant_roots',"PRIMARY KEY(tenant_id),UNIQUE(tenant_id,portfolio_id),CHECK(tenant_id<>'00000000-0000-0000-0000-000000000000'),CHECK(portfolio_id<>'00000000-0000-0000-0000-000000000000')")
    table('portfolios',"""fact_generation bigint NOT NULL DEFAULT 0 CHECK(fact_generation>=0),
 PRIMARY KEY(tenant_id,portfolio_id),UNIQUE(tenant_id),
 FOREIGN KEY(tenant_id,portfolio_id) REFERENCES wl_pg.tenant_roots(tenant_id,portfolio_id) DEFERRABLE INITIALLY DEFERRED""")
    statements.append("ALTER TABLE wl_pg.tenant_roots ADD FOREIGN KEY(tenant_id,portfolio_id) REFERENCES wl_pg.portfolios(tenant_id,portfolio_id) DEFERRABLE INITIALLY DEFERRED;")
    for name, fields in [
      ('issuers','label text NOT NULL'),
      ('accounts',"category text NOT NULL,role text NOT NULL CHECK(role IN ('investment','crypto','funding')),label text NOT NULL"),
      ('connections',"provider text NOT NULL,provider_digest text NOT NULL CHECK(encode(sha256(convert_to(provider,'UTF8')),'hex')=provider_digest),UNIQUE(tenant_id,portfolio_id,id,version,provider_digest),kind text NOT NULL CHECK(kind IN ('FILE_IMPORT','PULL_API')),generation bigint NOT NULL DEFAULT 0 CHECK(generation>=0)"),
      ('instruments',"""kind text NOT NULL CHECK(kind IN ('SECURITY','CASH','CRYPTO','UNSUPPORTED')),
 currency text,ticker text,mic text,symbol text,network text,settlement_identity text,
 issuer_id uuid,issuer_version text,identifiers jsonb NOT NULL,
 requires_satoshi boolean GENERATED ALWAYS AS (kind IN ('CRYPTO','UNSUPPORTED') AND
 coalesce(symbol COLLATE "C" ~ '^([Bb][Tt][Cc]|[Ll][Bb][Tt][Cc])$',false)) STORED,
 FOREIGN KEY(tenant_id,portfolio_id,issuer_id,issuer_version) REFERENCES wl_pg.issuers(tenant_id,portfolio_id,id,version) DEFERRABLE INITIALLY DEFERRED,
 CHECK((issuer_id IS NULL)=(issuer_version IS NULL))""")]:
        extra=",UNIQUE(tenant_id,portfolio_id,id,version,requires_satoshi)" if name=='instruments' else ''
        table(name,f"id uuid NOT NULL,version text NOT NULL CHECK(version COLLATE \"C\" ~ '^[0-9a-f]{{64}}$'),body jsonb NOT NULL,{fields},PRIMARY KEY(tenant_id,portfolio_id,id,version),"+scope_fk('portfolios',local='',remote='').replace('portfolio_id,)','portfolio_id)')+extra,frozen=name!='connections')
    table('candidate_batches',"""id uuid NOT NULL,digest text NOT NULL,canonical_bytes bytea NOT NULL,
 contract_version smallint NOT NULL CHECK(contract_version=1),profile text NOT NULL CHECK(profile='decimal-38s-24f-38i-v1'),mapping_revision text NOT NULL,
 PRIMARY KEY(tenant_id,portfolio_id,id),CHECK(octet_length(canonical_bytes)<=4194304),
 CHECK(encode(sha256(canonical_bytes),'hex')=digest),"""+scope_fk('portfolios',local='',remote='').replace('portfolio_id,)','portfolio_id)'),frozen=True)
    table('account_aliases',"""batch_id uuid NOT NULL,ordinal integer NOT NULL CHECK(ordinal>=0),connection_id uuid NOT NULL,connection_version text NOT NULL,
 account_id uuid NOT NULL,account_version text NOT NULL,source_account_key text NOT NULL,mapping_revision text NOT NULL,body jsonb NOT NULL,
 PRIMARY KEY(tenant_id,portfolio_id,batch_id,ordinal),"""+scope_fk('candidate_batches','batch_id','id')+','+scope_fk('connections','connection_id,connection_version','id,version')+','+scope_fk('accounts','account_id,account_version','id,version'),frozen=True)
    table('candidate_revisions',"""key text NOT NULL CHECK(key COLLATE "C" ~ '^[0-9a-f]{64}$'),logical_key text NOT NULL,
 selector_text text NOT NULL CHECK(octet_length(selector_text)<=4194304),logical_selector_text text NOT NULL CHECK(octet_length(logical_selector_text)<=4194304),
 connection_id uuid NOT NULL,connection_version text NOT NULL,provider_digest text NOT NULL,
 source_revision text,fact_id uuid,kind text NOT NULL CHECK(kind IN ('item','activity','snapshot','coverage')),
 body jsonb NOT NULL,body_digest text NOT NULL,parent_key text,
 PRIMARY KEY(tenant_id,portfolio_id,key),UNIQUE(tenant_id,portfolio_id,key,logical_key),
 CHECK(encode(sha256(convert_to(selector_text,'UTF8')),'hex')=key),
 CHECK(encode(sha256(convert_to(logical_selector_text,'UTF8')),'hex')=logical_key),
 CHECK((jsonb_typeof(selector_text::jsonb)='array' AND jsonb_array_length(selector_text::jsonb)=8 AND
 selector_text::jsonb->>0=connection_id::text AND
 encode(sha256(convert_to(selector_text::jsonb->>1,'UTF8')),'hex')=provider_digest AND
 (selector_text::jsonb-7)=logical_selector_text::jsonb AND
 (selector_text::jsonb->>7) IS NOT DISTINCT FROM source_revision) IS TRUE),
 FOREIGN KEY(tenant_id,portfolio_id,connection_id,connection_version,provider_digest) REFERENCES wl_pg.connections(tenant_id,portfolio_id,id,version,provider_digest) DEFERRABLE INITIALLY DEFERRED,
 CHECK(parent_key IS NULL OR parent_key<>key),
 FOREIGN KEY(tenant_id,portfolio_id,parent_key,logical_key) REFERENCES wl_pg.candidate_revisions(tenant_id,portfolio_id,key,logical_key) DEFERRABLE INITIALLY DEFERRED,
 """+scope_fk('portfolios',local='',remote='').replace('portfolio_id,)','portfolio_id)'),frozen=True)
    table('candidate_evidence',"""batch_id uuid NOT NULL,ordinal integer NOT NULL CHECK(ordinal>=0),revision_key text,
 evidence_kind text NOT NULL,body jsonb NOT NULL,UNIQUE(tenant_id,portfolio_id,batch_id,revision_key),"""+moment()+",PRIMARY KEY(tenant_id,portfolio_id,batch_id,ordinal),"+scope_fk('candidate_batches','batch_id','id')+','+scope_fk('candidate_revisions','revision_key','key'),frozen=True)
    table('candidate_snapshots',"""batch_id uuid NOT NULL,key text NOT NULL,snapshot_id uuid NOT NULL,body jsonb NOT NULL,"""+moment()+",PRIMARY KEY(tenant_id,portfolio_id,batch_id,key),"+scope_fk('candidate_revisions','key','key')+','+scope_fk('candidate_batches','batch_id','id'),frozen=True)
    table('candidate_items',"""batch_id uuid NOT NULL,snapshot_key text NOT NULL,ordinal integer NOT NULL,key text NOT NULL,"""+quantity()+','+','.join(money(n) for n in ['market_value','unit_price','cost_native','cost_cad','unrealized'])+','+moment()+",support jsonb NOT NULL,PRIMARY KEY(tenant_id,portfolio_id,batch_id,snapshot_key,ordinal),"+scope_fk('candidate_snapshots','batch_id,snapshot_key','batch_id,key')+','+scope_fk('candidate_revisions','key','key'),frozen=True)
    table('candidate_activities',"""batch_id uuid NOT NULL,key text NOT NULL,kind text NOT NULL,status text NOT NULL,fees_known boolean NOT NULL,
 source_kind text NOT NULL,source_status text NOT NULL,body jsonb NOT NULL,"""+','.join(money(n) for n in ['acquisition_cost','acquisition_cost_cad','cash_flow'])+','+moment()+",PRIMARY KEY(tenant_id,portfolio_id,batch_id,key),"+scope_fk('candidate_revisions','key','key')+','+scope_fk('candidate_batches','batch_id','id'),frozen=True)
    for name, extra in [('candidate_legs',"role text NOT NULL CHECK(role IN ('ACQUISITION','PAYMENT','TRANSFER','FEE','OTHER'))"),('candidate_fees',"included_in_leg boolean NOT NULL,included_in_cost boolean NOT NULL,CHECK(quantity_value>=0)")]:
        table(name,"batch_id uuid NOT NULL,event_key text NOT NULL,ordinal integer NOT NULL CHECK(ordinal>=0),"+quantity()+','+extra+",PRIMARY KEY(tenant_id,portfolio_id,batch_id,event_key,ordinal),"+scope_fk('candidate_activities','batch_id,event_key','batch_id,key'),frozen=True)
    table('candidate_coverage',"batch_id uuid NOT NULL,key text NOT NULL,account_id uuid NOT NULL,account_version text NOT NULL,status text NOT NULL CHECK(status IN ('complete','partial','unknown')),body jsonb NOT NULL,"+moment('start_')+','+moment('end_')+",PRIMARY KEY(tenant_id,portfolio_id,batch_id,key),"+scope_fk('candidate_revisions','key','key')+','+scope_fk('candidate_batches','batch_id','id')+','+scope_fk('accounts','account_id,account_version','id,version'),frozen=True)
    table('repository_heads',"batch_id uuid NOT NULL,logical_key text NOT NULL,revision_key text NOT NULL,PRIMARY KEY(tenant_id,portfolio_id,logical_key),"+scope_fk('candidate_revisions','revision_key,logical_key','key,logical_key')+','+scope_fk('candidate_evidence','batch_id,revision_key','batch_id,revision_key'))
    table('operation_receipts',"""id uuid NOT NULL,operation_kind text NOT NULL,idempotency_key text NOT NULL,
 request_digest text NOT NULL CHECK(request_digest COLLATE "C" ~ '^[0-9a-f]{64}$'),generation bigint NOT NULL CHECK(generation>=0),result jsonb NOT NULL,
 PRIMARY KEY(tenant_id,portfolio_id,id),UNIQUE(tenant_id,portfolio_id,operation_kind,idempotency_key),
 CHECK(length(idempotency_key) BETWEEN 8 AND 128 AND idempotency_key COLLATE "C" !~ '[^ -~]'),"""+scope_fk('portfolios',local='',remote='').replace('portfolio_id,)','portfolio_id)'),frozen=True)
    table('audit_actions',"id uuid NOT NULL,operation_id uuid NOT NULL,action text NOT NULL,created_at timestamptz NOT NULL DEFAULT clock_timestamp(),PRIMARY KEY(tenant_id,portfolio_id,id),"+scope_fk('operation_receipts','operation_id','id'),frozen=True)
    table('jobs',"""id uuid NOT NULL,kind text NOT NULL CHECK(kind='foundation'),request jsonb NOT NULL,
 request_digest text NOT NULL CHECK(request_digest COLLATE "C" ~ '^[0-9a-f]{64}$'),idempotency_key text NOT NULL,
 CHECK((jsonb_typeof(request)='object' AND request-'resource_id'-'version'='{}'::jsonb AND
 jsonb_typeof(request->'resource_id')='string' AND jsonb_typeof(request->'version')='string' AND request->>'version'='1' AND
 (request->>'resource_id') COLLATE "C" ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND
 request->>'resource_id'<>'00000000-0000-0000-0000-000000000000') IS TRUE),
 status text NOT NULL CHECK(status IN ('queued','running','retryable_error','succeeded','failed','cancelled')),
 attempt bigint NOT NULL DEFAULT 0 CHECK(attempt>=0),max_attempts integer NOT NULL CHECK(max_attempts BETWEEN 1 AND 3),CHECK(attempt<=max_attempts),
 fencing_token bigint NOT NULL DEFAULT 0 CHECK(fencing_token>=0),worker_id uuid,lease_expires_at timestamptz,
 lease_seconds integer NOT NULL DEFAULT 60 CHECK(lease_seconds BETWEEN 15 AND 3600),
 available_at timestamptz NOT NULL DEFAULT clock_timestamp(),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 connection_id uuid,connection_version text,connection_generation bigint,
 expected_generation bigint NOT NULL CHECK(expected_generation>=0),error_code text,cancel_requested boolean NOT NULL DEFAULT false,
 PRIMARY KEY(tenant_id,portfolio_id,id),UNIQUE(tenant_id,portfolio_id,kind,idempotency_key),
 CHECK(length(idempotency_key) BETWEEN 8 AND 128 AND idempotency_key COLLATE "C" !~ '[^ -~]'),
 CHECK(((connection_id IS NULL AND connection_version IS NULL AND connection_generation IS NULL) OR
 (connection_id IS NOT NULL AND connection_version IS NOT NULL AND connection_generation IS NOT NULL AND connection_generation>=0)) IS TRUE),
 """+scope_fk('portfolios',local='',remote='').replace('portfolio_id,)','portfolio_id)')+','+scope_fk('connections','connection_id,connection_version','id,version'))
    table('job_effect_receipts',"job_id uuid NOT NULL,operation_id uuid NOT NULL,result jsonb NOT NULL,PRIMARY KEY(tenant_id,portfolio_id,job_id),"+scope_fk('jobs','job_id','id')+','+scope_fk('operation_receipts','operation_id','id'),frozen=True)
    table('outbox',"""id uuid NOT NULL,operation_id uuid NOT NULL,generation bigint NOT NULL CHECK(generation>=0),
 event_kind text NOT NULL CHECK(event_kind IN ('candidate_stored','effect_committed')),resource_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),dispatched_at timestamptz,
 PRIMARY KEY(tenant_id,portfolio_id,id),"""+scope_fk('operation_receipts','operation_id','id'))
    statements.append("CREATE INDEX jobs_ready ON wl_pg.jobs(tenant_id,portfolio_id,status,available_at,created_at,id);CREATE INDEX outbox_pending ON wl_pg.outbox(tenant_id,portfolio_id,created_at,id) WHERE dispatched_at IS NULL;")
    policy="tenant_id::text=nullif(current_setting('ledger.tenant_id',true),'') AND portfolio_id::text=nullif(current_setting('ledger.portfolio_id',true),'')"
    for name in private:
        statements.append(f"ALTER TABLE wl_pg.{name} ENABLE ROW LEVEL SECURITY;ALTER TABLE wl_pg.{name} FORCE ROW LEVEL SECURITY;CREATE POLICY scope ON wl_pg.{name} USING ({policy}) WITH CHECK ({policy});")
    for name in immutable:
        statements.append(f"CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON wl_pg.{name} FOR EACH ROW EXECUTE FUNCTION wl_pg.reject_mutation();")
    statements.append("CREATE TRIGGER immutable BEFORE UPDATE OR DELETE ON wl_pg.connections FOR EACH ROW EXECUTE FUNCTION wl_pg.connection_generation_only();")
    statements.append("CREATE TRIGGER immutable_request BEFORE UPDATE ON wl_pg.jobs FOR EACH ROW EXECUTE FUNCTION wl_pg.job_request_immutable();")
    return '\n'.join(statements),tuple(private),tuple(immutable)
