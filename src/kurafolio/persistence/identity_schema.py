"""Closed identity DDL and definer inventory; no optional imports or runtime I/O."""

REVISION = "0002_identity"
MAXIMUM = 9223372036854775807
HASH_PATTERN = r'^\$argon2id\$v=19\$m=65536,t=3,p=4\$[A-Za-z0-9+/]{22}\$[A-Za-z0-9+/]{43}$'

TABLES = ("users", "instance_auth_state", "invites", "setup_codes", "sessions", "throttle", "auth_audit")
GATEWAY = ("identity_status_v1", "consume_budget_v1", "issue_anonymous_v1", "validate_session_v1",
           "login_target_v1", "password_target_v1", "register_commit_v1", "login_commit_v1",
           "touch_session_v1", "logout_session_v1", "change_password_v1", "bootstrap_commit_v1",
           "admin_issue_invite_v1", "admin_read_invites_v1", "admin_revoke_invite_v1")
OPERATOR = ("issue_invite_v1", "revoke_invite_v1", "reset_user_v1", "set_user_enabled_v1",
            "arm_setup_v1", "revoke_setup_v1")
SIGNATURES = {
    "identity_status_v1": (), "consume_budget_v1": ("text", "text", "text"),
    "issue_anonymous_v1": ("text",), "validate_session_v1": ("text", "text"),
    "login_target_v1": ("text",), "password_target_v1": ("text",),
    "register_commit_v1": ("text", "text", "text", "text"),
    "login_commit_v1": ("uuid", "bigint", "text", "text"),
    "touch_session_v1": ("text",), "logout_session_v1": ("text",),
    "change_password_v1": ("uuid", "bigint", "text", "text"),
    "issue_invite_v1": ("text",), "revoke_invite_v1": ("uuid",),
    "reset_user_v1": ("uuid", "text"), "set_user_enabled_v1": ("uuid", "boolean"),
    "arm_setup_v1": ("text",), "revoke_setup_v1": ("uuid",),
    "bootstrap_commit_v1": ("text", "text", "text", "text"),
    "admin_issue_invite_v1": ("text", "uuid", "bigint", "uuid", "text"),
    "admin_read_invites_v1": ("text", "uuid", "bigint", "uuid", "uuid", "integer"),
    "admin_revoke_invite_v1": ("text", "uuid", "bigint", "uuid"),
    "_clock_timestamp_v1": (),
}


def signature(name):
    return "wl_identity." + name + "(" + ",".join(SIGNATURES[name]) + ")"


def stamp(expression):
    return "pg_catalog.to_char((" + expression + ") AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"


def fail(code):
    return "RETURN pg_catalog.jsonb_build_object('ok',false,'code','" + code + "');"


def success(value="'{}'::pg_catalog.jsonb"):
    return "RETURN pg_catalog.jsonb_build_object('ok',true,'value'," + value + ");"


def audit(action, subject="NULL", actor="NULL"):
    return ("INSERT INTO wl_identity.auth_audit(id,occurred_at,action,subject_id,actor_id) VALUES"
            "(pg_catalog.gen_random_uuid(),n,'" + action + "'," + subject + "," + actor + ");")


def realm():
    return """pg_catalog.jsonb_build_object('database',pg_catalog.current_database(),
      'database_oid',(SELECT oid::pg_catalog.int8 FROM pg_catalog.pg_database WHERE datname=pg_catalog.current_database()),
      'server_address',pg_catalog.inet_server_addr()::pg_catalog.text,'server_port',pg_catalog.inet_server_port(),
      'incarnation',st.incarnation::pg_catalog.text,'epoch',st.restore_epoch)"""


def principal():
    return """pg_catalog.jsonb_build_object('user_id',u.id::pg_catalog.text,'username',u.username,
      'portfolio_id',u.portfolio_id::pg_catalog.text,'credential_version',u.credential_version,
      'session_digest',ss.token_digest,'expires_at',""" + stamp("ss.expires_at") + ", 'idle_expires_at'," + stamp("ss.last_activity+interval '1800 seconds'") + ", 'authorized_at'," + stamp("n") + ", 'is_instance_admin',a.admin_user_id=u.id,'realm'," + realm() + ")"


GUARD = """
 SELECT * INTO st FROM wl_pg.instance_state WHERE id=1 FOR SHARE;
 IF st.id IS NULL OR NOT st.ready OR
   (SELECT pg_catalog.count(*)<>1 OR pg_catalog.max(version_num) IS DISTINCT FROM '0002_identity' FROM wl_pg.alembic_version) THEN
   RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready');
 END IF;
 SELECT * INTO a FROM wl_identity.instance_auth_state WHERE id=1 FOR UPDATE;
 IF a.id IS NULL THEN RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready'); END IF;
"""
CLOCK = """
 n := wl_identity._clock_timestamp_v1();
 IF NOT pg_catalog.isfinite(n) OR n<a.last_observed_at THEN
   RETURN pg_catalog.jsonb_build_object('ok',false,'code','instance_not_ready');
 END IF;
 UPDATE wl_identity.instance_auth_state SET last_observed_at=n WHERE id=1;
"""


def user_lock(expression):
    return "SELECT * INTO u FROM wl_identity.users WHERE id=" + expression + " FOR UPDATE;\n"


def session_lock(expression):
    return "SELECT * INTO ss FROM wl_identity.sessions WHERE token_digest=" + expression + " FOR UPDATE;\n"


def session_user(token):
    # Reading the hint under the singleton guard does not acquire a session row lock.
    return ("SELECT user_id INTO uid FROM wl_identity.sessions WHERE token_digest=" + token + ";\n"
            + user_lock("uid"))


def check_session(code="session_changed", kind="authenticated"):
    return ("IF ss.token_digest IS NULL OR ss.kind<>'" + kind + "' OR ss.revoked OR "
            "ss.incarnation<>st.incarnation OR ss.epoch<>st.restore_epoch THEN " + fail(code) + " END IF;\n"
            "IF n<ss.created_at OR n<ss.last_activity THEN " + fail("instance_not_ready") + " END IF;\n"
            "IF n>=ss.expires_at" + (" OR n>=ss.last_activity+interval '1800 seconds'" if kind == "authenticated" else "")
            + " THEN " + fail(code) + " END IF;\n")


def check_user(*, version=None, code="authentication_required"):
    body = ("IF u.id IS NULL OR NOT u.enabled OR u.credential_incarnation<>st.incarnation "
            "OR u.credential_epoch<>st.restore_epoch THEN " + fail(code) + " END IF;\n"
            "IF n<u.created_at THEN " + fail("instance_not_ready") + " END IF;\n")
    if version:
        body += "IF " + version + " IS NULL OR " + version + "<1 THEN " + fail("instance_not_ready") + " END IF;\n"
        body += "IF u.credential_version IS DISTINCT FROM " + version + " THEN " + fail("credentials_changed") + " END IF;\n"
    return body


def check_admin():
    return (check_user(version="p_version") + check_session()
            + "IF ss.user_id<>u.id OR ss.credential_version<>u.credential_version THEN " + fail("session_changed") + " END IF;\n"
            + "IF a.admin_user_id IS DISTINCT FROM u.id THEN " + fail("admin_required") + " END IF;\n")


def consume_nonce():
    return """UPDATE wl_identity.sessions SET revoked=true WHERE token_digest=p_nonce AND kind='anonymous' AND NOT revoked;
 GET DIAGNOSTICS affected=ROW_COUNT;
 IF affected<>1 THEN RAISE EXCEPTION 'identity transition failed'; END IF;
"""


def validated_hash(expression):
    return "IF " + expression + " IS NULL OR " + expression + " !~ '" + HASH_PATTERN + "' THEN " + fail("instance_not_ready") + " END IF;\n"


def validated_digest(expression):
    return "IF " + expression + " IS NULL OR " + expression + " !~ '^[0-9a-f]{64}$' THEN " + fail("instance_not_ready") + " END IF;\n"


def function(name, parameters, body):
    arguments = ",".join(n + " pg_catalog." + {"bigint":"int8","integer":"int4","boolean":"bool"}.get(t,t) for n, t in parameters)
    assert tuple(t for _, t in parameters) == SIGNATURES[name]
    return ("CREATE FUNCTION wl_identity." + name + "(" + arguments + ") RETURNS pg_catalog.jsonb "
            "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $identity$\nDECLARE\n"
            " st wl_pg.instance_state%ROWTYPE; a wl_identity.instance_auth_state%ROWTYPE;\n"
            " u wl_identity.users%ROWTYPE; ss wl_identity.sessions%ROWTYPE;\n"
            " inv wl_identity.invites%ROWTYPE; sc wl_identity.setup_codes%ROWTYPE;\n"
            " n pg_catalog.timestamptz; uid pg_catalog.uuid; pid pg_catalog.uuid; rid pg_catalog.uuid;\n"
            " affected pg_catalog.int4; total pg_catalog.int4; lim pg_catalog.int4; win pg_catalog.int4;\n"
            " keys pg_catalog.text[]; bucket_key pg_catalog.text; item pg_catalog.jsonb; items pg_catalog.jsonb;\n"
            " row_data pg_catalog.record; vstate pg_catalog.text; more pg_catalog.bool;\n"
            "BEGIN\n" + body + "\nEND\n$identity$;\nREVOKE ALL ON FUNCTION " + signature(name) + " FROM PUBLIC;\n")


def ddl():
    """Return deterministic0002 DDL without changing the0001 finance DDL provider."""
    schema = r"""
CREATE SCHEMA wl_identity;
REVOKE ALL ON SCHEMA wl_identity FROM PUBLIC;
CREATE TABLE wl_identity.users(
 id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
 portfolio_id uuid NOT NULL UNIQUE,
 username text COLLATE "C" NOT NULL CHECK(username ~ '^[A-Za-z0-9_.-]{1,64}$'),
 username_key text COLLATE "C" NOT NULL UNIQUE CHECK(username_key=pg_catalog.lower(username COLLATE "C")),
 argon_hash text NOT NULL CHECK(length(argon_hash)<=256), enabled boolean NOT NULL DEFAULT true,
 credential_version bigint NOT NULL DEFAULT 1 CHECK(credential_version BETWEEN 1 AND 9223372036854775807),
 credential_incarnation uuid NOT NULL, credential_epoch bigint NOT NULL CHECK(credential_epoch>=0),
 created_at timestamptz NOT NULL CHECK(pg_catalog.isfinite(created_at)),
 FOREIGN KEY(id,portfolio_id) REFERENCES wl_pg.portfolios(tenant_id,portfolio_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE wl_identity.instance_auth_state(
 id integer PRIMARY KEY CHECK(id=1) REFERENCES wl_pg.instance_state(id),
 key_digest text NOT NULL CHECK(key_digest ~ '^[0-9a-f]{64}$'),
 last_observed_at timestamptz NOT NULL CHECK(pg_catalog.isfinite(last_observed_at)),
 bootstrap_closed boolean NOT NULL DEFAULT false, admin_user_id uuid REFERENCES wl_identity.users(id),
 CHECK(bootstrap_closed=(admin_user_id IS NOT NULL))
);
CREATE TABLE wl_identity.invites(
 id uuid PRIMARY KEY, token_digest text NOT NULL UNIQUE CHECK(token_digest ~ '^[0-9a-f]{64}$'),
 issue_request_id uuid UNIQUE CHECK(issue_request_id<>'00000000-0000-0000-0000-000000000000'),
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 incarnation uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=0),
 status text NOT NULL CHECK(status IN ('issued','consumed','revoked')),
 revocation_reason text CHECK(revocation_reason IN ('manual','restore')),
 consumed_user_id uuid REFERENCES wl_identity.users(id),
 CHECK((status='consumed')=(consumed_user_id IS NOT NULL)),
 CHECK((status='revoked' AND revocation_reason IS NOT NULL) OR (status<>'revoked' AND revocation_reason IS NULL)),
 CHECK(pg_catalog.isfinite(created_at) AND expires_at=created_at+interval '86400 seconds')
);
CREATE TABLE wl_identity.setup_codes(
 id uuid PRIMARY KEY, token_digest text NOT NULL UNIQUE CHECK(token_digest ~ '^[0-9a-f]{64}$'),
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 incarnation uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=0),
 status text NOT NULL CHECK(status IN ('issued','expired','revoked','consumed')),
 CHECK(pg_catalog.isfinite(created_at) AND expires_at=created_at+interval '1800 seconds')
);
CREATE UNIQUE INDEX one_armed_setup ON wl_identity.setup_codes((1)) WHERE status='issued';
CREATE TABLE wl_identity.sessions(
 token_digest text PRIMARY KEY CHECK(token_digest ~ '^[0-9a-f]{64}$'),
 kind text NOT NULL CHECK(kind IN ('anonymous','authenticated')),
 user_id uuid REFERENCES wl_identity.users(id), credential_version bigint,
 created_at timestamptz NOT NULL, last_activity timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 incarnation uuid NOT NULL, epoch bigint NOT NULL CHECK(epoch>=0), revoked boolean NOT NULL DEFAULT false,
 CHECK((kind='anonymous' AND user_id IS NULL AND credential_version IS NULL) OR
       (kind='authenticated' AND user_id IS NOT NULL AND credential_version>0)),
 CHECK(pg_catalog.isfinite(created_at) AND last_activity>=created_at AND last_activity<expires_at),
 CHECK((kind='anonymous' AND expires_at=created_at+interval '600 seconds') OR
       (kind='authenticated' AND expires_at=created_at+interval '43200 seconds'))
);
CREATE TABLE wl_identity.throttle(
 bucket text COLLATE "C" PRIMARY KEY CHECK(length(bucket)<=128),
 started_at timestamptz NOT NULL CHECK(pg_catalog.isfinite(started_at)),
 window_seconds integer NOT NULL CHECK(window_seconds IN (300,900)),
 attempts integer NOT NULL CHECK(attempts BETWEEN 1 AND 1000000)
);
CREATE TABLE wl_identity.auth_audit(
 id uuid PRIMARY KEY, occurred_at timestamptz NOT NULL CHECK(pg_catalog.isfinite(occurred_at)),
 action text NOT NULL CHECK(action IN ('registered','invite_issued','invite_revoked','password_reset',
  'password_changed','account_disabled','account_enabled','setup_armed','setup_revoked','setup_completed',
  'admin_invite_issued','admin_invite_revoked','restore_finalized')),
 subject_id uuid, actor_id uuid
);
REVOKE ALL ON ALL TABLES IN SCHEMA wl_identity FROM PUBLIC;
CREATE FUNCTION wl_identity._clock_timestamp_v1() RETURNS pg_catalog.timestamptz
 LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,pg_temp
 AS 'SELECT pg_catalog.clock_timestamp()';
REVOKE ALL ON FUNCTION wl_identity._clock_timestamp_v1() FROM PUBLIC;
"""
    bodies = {}
    status = "SELECT * INTO st FROM wl_pg.instance_state WHERE id=1; SELECT * INTO a FROM wl_identity.instance_auth_state WHERE id=1;\n"
    status += success(realm() + " || pg_catalog.jsonb_build_object('ready',st.ready,'schema_revision',"
                      "(SELECT version_num FROM wl_pg.alembic_version),'key_digest',a.key_digest,"
                      "'bootstrap_closed',a.bootstrap_closed,'admin_user_id',a.admin_user_id::pg_catalog.text)")
    bodies['identity_status_v1'] = ([], status)

    budget = GUARD + """
 IF p_operation NOT IN ('anonymous','login','register','password_change','setup','invite_issue','invite_revoke','invite_read')
 OR p_peer IS NULL OR p_peer !~ '^[0-9a-f]{64}$' THEN
 """ + fail('instance_not_ready') + " END IF;\n"
    budget += """
 IF p_operation IN ('login','password_change','invite_issue','invite_revoke','invite_read') AND
 (p_subject IS NULL OR p_subject !~ '^[0-9a-f]{64}$') THEN
 """ + fail('instance_not_ready') + " END IF;\n"
    budget += "PERFORM 1 FROM wl_identity.throttle ORDER BY bucket FOR UPDATE;\n" + CLOCK
    budget += """
 DELETE FROM wl_identity.throttle WHERE started_at+window_seconds*interval '1 second'<=n;
 IF p_operation='password_change' THEN keys:=ARRAY[p_operation||':user:'||p_subject];
 ELSIF p_operation LIKE 'invite_%' THEN keys:=ARRAY[p_operation||':instance',p_operation||':user:'||p_subject];
 ELSIF p_operation='login' THEN keys:=ARRAY[p_operation||':instance',p_operation||':peer:'||p_peer,p_operation||':user:'||p_subject];
 ELSE keys:=ARRAY[p_operation||':instance',p_operation||':peer:'||p_peer]; END IF;
 win:=CASE WHEN p_operation IN ('anonymous','invite_read') THEN 300 ELSE 900 END;
 FOREACH bucket_key IN ARRAY keys LOOP
   lim:=CASE WHEN p_operation='anonymous' THEN CASE WHEN bucket_key=p_operation||':instance' THEN 600 ELSE 60 END
     WHEN p_operation='invite_read' THEN CASE WHEN bucket_key=p_operation||':instance' THEN 600 ELSE 60 END
     WHEN bucket_key=p_operation||':instance' THEN 20 ELSE 5 END;
   SELECT * INTO row_data FROM wl_identity.throttle WHERE bucket=bucket_key;
   IF FOUND THEN
     IF n<row_data.started_at THEN
 """ + fail('instance_not_ready') + """ END IF;
     IF row_data.attempts>=lim THEN
 """ + fail('rate_limited') + """ END IF;
     UPDATE wl_identity.throttle SET attempts=attempts+1 WHERE bucket=bucket_key;
   ELSE INSERT INTO wl_identity.throttle VALUES(bucket_key,n,win,1); END IF;
 END LOOP;
 """ + success()
    bodies['consume_budget_v1'] = ([('p_operation','text'),('p_peer','text'),('p_subject','text')], budget)
    anon = GUARD + "PERFORM 1 FROM wl_identity.sessions WHERE kind='anonymous' ORDER BY token_digest FOR UPDATE;\n" + CLOCK + validated_digest('p_digest')
    anon += """
 DELETE FROM wl_identity.sessions WHERE kind='anonymous' AND (revoked OR expires_at<=n);
 IF (SELECT count(*) FROM wl_identity.sessions WHERE kind='anonymous')>=1000 THEN
 """ + fail('rate_limited') + """ END IF;
 INSERT INTO wl_identity.sessions VALUES(p_digest,'anonymous',NULL,NULL,n,n,n+interval '600 seconds',st.incarnation,st.restore_epoch,false);
 """ + success("pg_catalog.jsonb_build_object('expires_at'," + stamp("n+interval '600 seconds'") + ")")
    bodies['issue_anonymous_v1'] = ([('p_digest','text')], anon)

    validation = GUARD + session_user('p_digest') + session_lock('p_digest') + CLOCK
    validation += "IF p_kind NOT IN ('any','anonymous','authenticated') OR p_kind IS NULL THEN " + fail('instance_not_ready') + " END IF;\n"
    validation += "IF ss.kind='anonymous' THEN\n" + check_session('authentication_required','anonymous')
    validation += "IF p_kind='authenticated' THEN " + fail('authentication_required') + " END IF;\n"
    validation += success("pg_catalog.jsonb_build_object('kind','anonymous','expires_at'," + stamp('ss.expires_at') + ")") + "\nEND IF;\n"
    validation += check_user() + check_session('authentication_required')
    validation += "IF ss.user_id<>u.id OR ss.credential_version<>u.credential_version THEN " + fail('authentication_required') + " END IF;\n"
    validation += "IF p_kind='anonymous' THEN " + fail('anonymous_session_required') + " END IF;\n"
    validation += success("pg_catalog.jsonb_build_object('kind','authenticated','principal'," + principal() + ")")
    bodies['validate_session_v1'] = ([('p_digest','text'),('p_kind','text')], validation)

    target = GUARD + "SELECT * INTO u FROM wl_identity.users WHERE username_key=p_username FOR UPDATE;\n" + CLOCK
    target += "IF u.id IS NULL OR NOT u.enabled OR u.credential_incarnation<>st.incarnation OR u.credential_epoch<>st.restore_epoch THEN "
    target += success("pg_catalog.jsonb_build_object('usable',false)") + " END IF;\n"
    target += success("pg_catalog.jsonb_build_object('usable',true,'user_id',u.id::pg_catalog.text,'argon_hash',u.argon_hash,'credential_version',u.credential_version)")
    bodies['login_target_v1'] = ([('p_username','text')], target)
    target = GUARD + session_user('p_digest') + session_lock('p_digest') + CLOCK + check_user() + check_session('authentication_required')
    target += "IF ss.user_id<>u.id OR ss.credential_version<>u.credential_version THEN " + fail('authentication_required') + " END IF;\n"
    target += success("pg_catalog.jsonb_build_object('user_id',u.id::pg_catalog.text,'argon_hash',u.argon_hash,'credential_version',u.credential_version)")
    bodies['password_target_v1'] = ([('p_digest','text')], target)

    for name, setup in [('register_commit_v1', False), ('bootstrap_commit_v1', True)]:
        table = 'setup_codes' if setup else 'invites'
        record = 'sc' if setup else 'inv'
        rejection = 'setup_rejected' if setup else 'registration_rejected'
        body = GUARD + 'SELECT * INTO ' + record + ' FROM wl_identity.' + table + ' WHERE token_digest=p_code FOR UPDATE;\n'
        body += session_lock('p_nonce') + CLOCK + check_session('session_changed','anonymous')
        body += "IF " + ("a.bootstrap_closed" if setup else "NOT a.bootstrap_closed") + " THEN " + fail('setup_closed' if setup else 'setup_required') + " END IF;\n"
        body += "IF " + record + ".id IS NULL OR " + record + ".status<>'issued' OR " + record + ".incarnation<>st.incarnation OR " + record + ".epoch<>st.restore_epoch OR n>=" + record + ".expires_at THEN " + fail(rejection) + " END IF;\n"
        body += "IF n<" + record + '.created_at THEN ' + fail('instance_not_ready') + " END IF;\n"
        body += "IF p_username IS NULL OR p_username !~ '^[A-Za-z0-9_.-]{1,64}$' OR EXISTS(SELECT 1 FROM wl_identity.users WHERE username_key=pg_catalog.lower(p_username COLLATE \"C\")) THEN " + fail(rejection) + " END IF;\n"
        body += validated_hash('p_hash') + consume_nonce()
        body += """
 uid:=pg_catalog.gen_random_uuid();pid:=pg_catalog.gen_random_uuid();
 INSERT INTO wl_pg.tenant_roots(tenant_id,portfolio_id) VALUES(uid,pid);
 INSERT INTO wl_pg.portfolios(tenant_id,portfolio_id) VALUES(uid,pid);
 INSERT INTO wl_identity.users VALUES(uid,pid,p_username,pg_catalog.lower(p_username COLLATE "C"),p_hash,true,1,st.incarnation,st.restore_epoch,n);
 """
        if setup:
            body += "UPDATE wl_identity.instance_auth_state SET bootstrap_closed=true,admin_user_id=uid WHERE id=1;\nUPDATE wl_identity.setup_codes SET status='consumed' WHERE id=sc.id;\n" + audit('setup_completed','uid')
        else:
            body += "UPDATE wl_identity.invites SET status='consumed',consumed_user_id=uid WHERE id=inv.id;\n" + audit('registered','uid')
        body += success("pg_catalog.jsonb_build_object('" + ('initialized' if setup else 'registered') + "',true)")
        bodies[name] = ([('p_code','text'),('p_username','text'),('p_hash','text'),('p_nonce','text')], body)

    login = GUARD + user_lock('p_user') + session_lock('p_nonce') + CLOCK + check_session('session_changed','anonymous') + check_user(version='p_version') + validated_digest('p_replacement') + consume_nonce()
    login += """INSERT INTO wl_identity.sessions VALUES(p_replacement,'authenticated',u.id,u.credential_version,n,n,n+interval '43200 seconds',st.incarnation,st.restore_epoch,false);
 SELECT * INTO ss FROM wl_identity.sessions WHERE token_digest=p_replacement;
 """ + success("pg_catalog.jsonb_build_object('principal'," + principal() + ")")
    bodies['login_commit_v1'] = ([('p_user','uuid'),('p_version','bigint'),('p_nonce','text'),('p_replacement','text')], login)
    for name, logout in [('touch_session_v1',False),('logout_session_v1',True)]:
        body = GUARD + session_user('p_digest') + session_lock('p_digest') + CLOCK + check_user()
        body += "IF u.credential_version IS DISTINCT FROM ss.credential_version THEN " + fail('credentials_changed') + " END IF;\n" + check_session()
        body += "UPDATE wl_identity.sessions SET " + ('revoked=true' if logout else 'last_activity=n') + " WHERE token_digest=p_digest;\n" + success()
        bodies[name] = ([('p_digest','text')], body)
    change = GUARD + user_lock('p_user')
    change += "PERFORM 1 FROM wl_identity.sessions WHERE user_id=p_user ORDER BY token_digest FOR UPDATE;\n" + session_lock('p_digest') + CLOCK
    change += check_user(version='p_version') + check_session() + "IF ss.user_id<>u.id OR ss.credential_version<>u.credential_version THEN " + fail('session_changed') + " END IF;\n"
    change += validated_hash('p_hash') + "IF u.credential_version>=9223372036854775807 THEN " + fail('instance_not_ready') + " END IF;\n"
    change += "UPDATE wl_identity.users SET argon_hash=p_hash,credential_version=credential_version+1 WHERE id=u.id; UPDATE wl_identity.sessions SET revoked=true WHERE user_id=u.id;\n" + audit('password_changed','u.id','u.id') + success()
    bodies['change_password_v1'] = ([('p_user','uuid'),('p_version','bigint'),('p_digest','text'),('p_hash','text')], change)

    arm = GUARD + "PERFORM 1 FROM wl_identity.setup_codes ORDER BY id FOR UPDATE;\n" + CLOCK + validated_digest('p_digest')
    arm += "IF a.bootstrap_closed THEN " + fail('setup_closed') + " END IF;\n"
    arm += "IF EXISTS(SELECT 1 FROM wl_identity.setup_codes WHERE status='issued' AND incarnation=st.incarnation AND epoch=st.restore_epoch AND expires_at>n) THEN " + fail('setup_already_armed') + " END IF;\n"
    arm += "UPDATE wl_identity.setup_codes SET status='expired' WHERE status='issued'; rid:=pg_catalog.gen_random_uuid();\n"
    arm += "INSERT INTO wl_identity.setup_codes VALUES(rid,p_digest,n,n+interval '1800 seconds',st.incarnation,st.restore_epoch,'issued');\n" + audit('setup_armed','rid')
    arm += success("pg_catalog.jsonb_build_object('setup_id',rid::pg_catalog.text,'expires_at'," + stamp("n+interval '1800 seconds'") + ")")
    bodies['arm_setup_v1'] = ([('p_digest','text')], arm)
    revoke = GUARD + "SELECT * INTO sc FROM wl_identity.setup_codes WHERE id=p_id FOR UPDATE;\n" + CLOCK
    revoke += "IF sc.id IS NULL THEN " + fail('operator_not_found') + " END IF;\nIF sc.status<>'issued' OR sc.incarnation<>st.incarnation OR sc.epoch<>st.restore_epoch OR n>=sc.expires_at THEN " + fail('setup_not_active') + " END IF;\n"
    revoke += "UPDATE wl_identity.setup_codes SET status='revoked' WHERE id=sc.id;\n" + audit('setup_revoked','sc.id') + success()
    bodies['revoke_setup_v1'] = ([('p_id','uuid')], revoke)

    issue = GUARD + CLOCK + validated_digest('p_digest')
    issue += "IF NOT a.bootstrap_closed THEN " + fail('setup_required') + " END IF;\nrid:=pg_catalog.gen_random_uuid();\n"
    issue += "INSERT INTO wl_identity.invites VALUES(rid,p_digest,NULL,n,n+interval '86400 seconds',st.incarnation,st.restore_epoch,'issued',NULL,NULL);\n" + audit('invite_issued','rid')
    issue += success("pg_catalog.jsonb_build_object('invite_id',rid::pg_catalog.text,'expires_at'," + stamp("n+interval '86400 seconds'") + ")")
    bodies['issue_invite_v1'] = ([('p_digest','text')], issue)
    revoke = GUARD + "SELECT * INTO inv FROM wl_identity.invites WHERE id=p_id FOR UPDATE;\n" + CLOCK
    revoke += "IF inv.id IS NULL THEN " + fail('operator_not_found') + " END IF;\nIF inv.status<>'issued' OR inv.incarnation<>st.incarnation OR inv.epoch<>st.restore_epoch OR n>=inv.expires_at THEN " + fail('invite_not_active') + " END IF;\n"
    revoke += "UPDATE wl_identity.invites SET status='revoked',revocation_reason='manual' WHERE id=inv.id;\n" + audit('invite_revoked','inv.id') + success()
    bodies['revoke_invite_v1'] = ([('p_id','uuid')], revoke)
    for name, reset in [('reset_user_v1',True),('set_user_enabled_v1',False)]:
        body = GUARD + user_lock('p_user') + "PERFORM 1 FROM wl_identity.sessions WHERE user_id=p_user ORDER BY token_digest FOR UPDATE;\n" + CLOCK
        body += "IF u.id IS NULL THEN " + fail('operator_not_found') + " END IF;\n"
        if reset:
            body += validated_hash('p_hash') + "IF u.credential_version>=9223372036854775807 THEN " + fail('instance_not_ready') + " END IF;\n"
            body += "UPDATE wl_identity.users SET argon_hash=p_hash,credential_version=credential_version+1,credential_incarnation=st.incarnation,credential_epoch=st.restore_epoch WHERE id=u.id;\n" + audit('password_reset','u.id')
        else:
            body += "IF p_enabled IS NULL THEN " + fail('instance_not_ready') + " END IF;\nIF u.enabled=p_enabled THEN " + success() + " END IF;\n"
            body += "UPDATE wl_identity.users SET enabled=p_enabled WHERE id=u.id;\n"
            body += "IF p_enabled THEN " + audit('account_enabled','u.id') + " ELSE " + audit('account_disabled','u.id') + " END IF;\n"
        body += "UPDATE wl_identity.sessions SET revoked=true WHERE user_id=u.id;\n" + success()
        bodies[name] = ([('p_user','uuid'),('p_hash','text')] if reset else [('p_user','uuid'),('p_enabled','boolean')], body)

    admin_parameters = [('p_digest','text'),('p_user','uuid'),('p_version','bigint')]
    issue = GUARD + user_lock('p_user') + session_lock('p_digest') + CLOCK + check_admin() + validated_digest('p_token')
    issue += "IF p_request IS NULL OR p_request='00000000-0000-0000-0000-000000000000'::pg_catalog.uuid THEN " + fail('instance_not_ready') + " END IF;\n"
    issue += "IF EXISTS(SELECT 1 FROM wl_identity.invites WHERE issue_request_id=p_request) THEN " + fail('invite_already_issued') + " END IF;\nrid:=pg_catalog.gen_random_uuid();\n"
    issue += "INSERT INTO wl_identity.invites VALUES(rid,p_token,p_request,n,n+interval '86400 seconds',st.incarnation,st.restore_epoch,'issued',NULL,NULL);\n" + audit('admin_invite_issued','rid','u.id')
    issue += success("pg_catalog.jsonb_build_object('id',rid::pg_catalog.text,'issue_request_id',p_request::pg_catalog.text,'expires_at'," + stamp("n+interval '86400 seconds'") + ")")
    bodies['admin_issue_invite_v1'] = (admin_parameters+[('p_request','uuid'),('p_token','text')],issue)
    revoke = GUARD + user_lock('p_user') + "SELECT * INTO inv FROM wl_identity.invites WHERE id=p_id FOR UPDATE;\n" + session_lock('p_digest') + CLOCK + check_admin()
    revoke += "IF inv.id IS NULL THEN " + fail('not_found') + " END IF;\nIF inv.status<>'issued' OR inv.incarnation<>st.incarnation OR inv.epoch<>st.restore_epoch OR n>=inv.expires_at THEN " + fail('invite_not_active') + " END IF;\n"
    revoke += "UPDATE wl_identity.invites SET status='revoked',revocation_reason='manual' WHERE id=inv.id;\n" + audit('admin_invite_revoked','inv.id','u.id') + success()
    bodies['admin_revoke_invite_v1'] = (admin_parameters+[('p_id','uuid')],revoke)
    listing = GUARD + user_lock('p_user') + session_lock('p_digest') + CLOCK + check_admin()
    listing += "IF p_limit IS NULL OR p_limit<1 OR p_limit>100 OR (p_request IS NOT NULL AND (p_after IS NOT NULL OR p_limit<>50)) THEN " + fail('instance_not_ready') + " END IF;\n"
    listing += """
 IF EXISTS(SELECT 1 FROM wl_identity.invites WHERE status='issued' AND (incarnation<>st.incarnation OR epoch<>st.restore_epoch)) THEN
 """ + fail('instance_not_ready') + """ END IF;
 items:='[]'::pg_catalog.jsonb;total:=0;more:=false;
 FOR inv IN SELECT * FROM wl_identity.invites WHERE
   (p_request IS NULL OR issue_request_id=p_request) AND (p_after IS NULL OR id>p_after)
   ORDER BY id LIMIT p_limit+1 LOOP
   IF total=p_limit THEN more:=true;EXIT;END IF;
   vstate:=CASE WHEN inv.status='issued' AND n>=inv.expires_at THEN 'expired' ELSE inv.status END;
   item:=pg_catalog.jsonb_build_object('id',inv.id::pg_catalog.text,'issue_request_id',inv.issue_request_id::pg_catalog.text,
     'created_at',""" + stamp('inv.created_at') + ",'expires_at'," + stamp('inv.expires_at') + """,
     'status',vstate,'revocation_reason',inv.revocation_reason);
   items:=items||pg_catalog.jsonb_build_array(item);rid:=inv.id;total:=total+1;
 END LOOP;
 """ + success("pg_catalog.jsonb_build_object('items',items,'next_after',CASE WHEN more THEN rid::pg_catalog.text ELSE NULL END)")
    bodies['admin_read_invites_v1'] = (admin_parameters+[('p_request','uuid'),('p_after','uuid'),('p_limit','integer')],listing)
    assert set(bodies) == set(SIGNATURES)-{'_clock_timestamp_v1'}
    for name in SIGNATURES:
        if name != '_clock_timestamp_v1':
            schema += function(name,*bodies[name])
    return schema
