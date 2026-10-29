#!/usr/bin/env python3
"""Explicit optional PostgreSQL foundation operations; never discover/migrate SQLite."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
PG_IMAGE='postgres@sha256:edb0c08dc33befd0262ab3b5cf1c4f3f8cfd8b09e88c05b45adee29d6761ddb6'


def _private(path,text):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb' if isinstance(text,bytes) else 'w') as stream:stream.write(text)


def test_environment(output, *, identity=False):
    """Create only new explicitly synthetic Docker resources and generated secrets."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from wealth_ledger.persistence.config import PostgresConfig
    from wealth_ledger.persistence.context import Database
    from wealth_ledger.persistence.migration import migrate
    output=Path(output).resolve()
    if output.exists():raise ValueError('invalid_config')
    output.mkdir(parents=True,mode=0o700)
    suffix=uuid.uuid4().hex[:12];prefix='wealth-ledger-pg-test-'+suffix
    resources={'container':prefix,'volume':prefix,'network':prefix,'database':'wl_test_'+suffix,
               'migration_role':'wl_test_'+suffix+'_operator','runtime_role':'wl_test_'+suffix+'_runtime','image':PG_IMAGE}
    if identity:resources['identity_role']='wl_test_'+suffix+'_identity'
    _private(output/'resources.json',json.dumps(resources,indent=2)+'\n')
    bootstrap=secrets.token_urlsafe(32);_private(output/'bootstrap.secret',bootstrap)
    for kind in ['volume','network']:
        if subprocess.run(['docker',kind,'inspect',resources[kind]],capture_output=True).returncode==0:raise ValueError('invalid_config')
        subprocess.run(['docker',kind,'create','--label','wealth-ledger.test=pg-foundation',resources[kind]],check=True,stdout=subprocess.DEVNULL)
    # Persist an OS-selected random binding in Docker's configuration. A blank
    # HostPort is reallocated on restart, invalidating the explicit secret files.
    # A bind race fails safely; no alternate/fixed service port is adopted.
    import socket
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
        probe.bind(('127.0.0.1',0));selected_port=probe.getsockname()[1]
    subprocess.run(['docker','run','--detach','--name',prefix,'--label','wealth-ledger.test=pg-foundation',
        '--network',prefix,'--publish','127.0.0.1:'+str(selected_port)+':5432','--env','POSTGRES_PASSWORD_FILE=/run/secrets/bootstrap',
        '--mount','type=bind,src='+str(output/'bootstrap.secret')+',dst=/run/secrets/bootstrap,readonly',
        '--mount','type=volume,src='+prefix+',dst=/var/lib/postgresql',PG_IMAGE],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    port=int(subprocess.check_output(['docker','port',prefix,'5432/tcp'],text=True).strip().rsplit(':',1)[1])
    if port!=selected_port:raise ValueError('invalid_config')
    options={'host':'127.0.0.1','port':port,'connect_timeout':5 if identity else 2}
    if identity:options['sslmode']='disable'
    connection=None
    for attempt in range(100):
        try:connection=psycopg.connect(**options,dbname='postgres',user='postgres',password=bootstrap,autocommit=True);break
        except psycopg.OperationalError:time.sleep(.25)
    if connection is None:raise ValueError('database_unavailable')
    with connection:
        for key in ['migration','runtime']+(['identity'] if identity else []):
            role=resources[key+'_role'];value=secrets.token_urlsafe(32)
            connection.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE').format(sql.Identifier(role),sql.Literal(value)))
            _private(output/(key+'.conninfo'),make_conninfo(**options,dbname=resources['database'],user=role,password=value))
        connection.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(resources['database']),sql.Identifier(resources['migration_role'])))
    operator=Database(PostgresConfig.from_secret_file(output/'migration.conninfo'),schema_mode='identity' if identity else 'foundation')
    try:
        if identity:
            import hashlib
            from wealth_ledger.persistence.migration import migrate_identity
            key=secrets.token_bytes(32);_private(output/'identity.key',key)
            status=migrate_identity(operator,resources['runtime_role'],resources['identity_role'],hashlib.sha256(key).hexdigest())
        else:status=migrate(operator,resources['runtime_role'])
    finally:operator.close()
    configuration={'format':'wealth-ledger-synthetic-identity-tests' if identity else 'wealth-ledger-synthetic-pg-tests',**resources,
                   'migration_secret_file':str(output/'migration.conninfo'),'runtime_secret_file':str(output/'runtime.conninfo')}
    if identity:configuration.update(identity_secret_file=str(output/'identity.conninfo'),key_file=str(output/'identity.key'))
    _private(output/'test-config.json',json.dumps(configuration,indent=2)+'\n')
    return {'synthetic':True,'config':str(output/'test-config.json'),'schema_revision':status['schema_revision']}


def cleanup_environment(path):
    configuration=json.loads(Path(path).read_text())
    if configuration.get('format') not in {'wealth-ledger-synthetic-pg-tests','wealth-ledger-synthetic-identity-tests'}:raise ValueError('invalid_config')
    prefix=configuration['container']
    if not prefix.startswith('wealth-ledger-pg-test-') or any(configuration[k]!=prefix for k in ['network','volume']):raise ValueError('invalid_config')
    for kind in ['container','volume','network']:
        result=subprocess.run(['docker',kind,'inspect',prefix],capture_output=True,text=True)
        if result.returncode:continue
        item=json.loads(result.stdout)[0]
        labels=item.get('Config',{}).get('Labels',{}) if kind=='container' else item.get('Labels',{})
        if labels.get('wealth-ledger.test')!='pg-foundation':raise ValueError('invalid_config')
    subprocess.run(['docker','container','rm','--force',prefix],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['docker','volume','rm',prefix],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['docker','network','rm',prefix],check=True,stdout=subprocess.DEVNULL)
    return {'synthetic_resources_removed':True,'private_evidence_directory_preserved':True}



def source_test_artifact(image,context_manifest,output):
    """Explicit test-host proof from an audited context; no ambient discovery."""
    import hashlib
    import re
    import tomllib
    from wealth_ledger.data_sources.contract_v1 import canonical
    from wealth_ledger.data_sources.catalog_v1 import verify_installation
    from wealth_ledger.data_sources.compatibility_v1 import builtin_descriptors
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',image):raise ValueError('invalid_config')
    manifest=json.loads(Path(context_manifest).read_bytes())
    files=[]
    for name,digest in sorted(manifest['files'].items()):
        if not name.startswith('src/wealth_ledger/'):continue
        path=Path(name)
        if path.is_absolute() or '..' in path.parts or '__pycache__' in path.parts or (ROOT/path).is_symlink():raise ValueError('invalid_config')
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest:raise ValueError('invalid_config')
        files.append({'path':name[4:],'sha256':digest})
    if not files:raise ValueError('invalid_config')
    project=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']
    raw=canonical({'format':'source-content-v1','package_distribution':project['name'],'package_version':project['version'],
        'entry_points':[{'name':'wealthsimple.holdings','target':'wealth_ledger.source_builtin:registrations'},
                        {'name':'bullbitcoin.orders','target':'wealth_ledger.source_builtin:registrations'}], 'files':files})
    descriptors=builtin_descriptors(package_distribution=project['name'],package_version=project['version'],
        artifact_sha256=hashlib.sha256(raw).hexdigest(),execution_image_digest=image[7:],entry_point_target='wealth_ledger.source_builtin:registrations')
    for descriptor in descriptors:verify_installation(descriptor,raw,image_root='/app/src')
    _private(Path(output),raw)
    return {'synthetic':True,'artifact_file':str(output),'files':len(files),'image_id':image}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ['status','migrate','finalize-restore']:
        item=commands.add_parser(name);item.add_argument('--secret-file',required=True,type=Path)
        if name!='status':item.add_argument('--runtime-role',required=True)
    commands.add_parser('test-environment').add_argument('--output',required=True,type=Path)
    commands.add_parser('test-identity-environment').add_argument('--output',required=True,type=Path)
    commands.add_parser('cleanup-test-environment').add_argument('--config',required=True,type=Path)
    artifact=commands.add_parser('test-source-artifact')
    artifact.add_argument('--image',required=True)
    artifact.add_argument('--context-manifest',required=True,type=Path)
    artifact.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    try:
        if args.command=='test-environment':result=test_environment(args.output)
        elif args.command=='test-identity-environment':result=test_environment(args.output,identity=True)
        elif args.command=='cleanup-test-environment':result=cleanup_environment(args.config)
        elif args.command=='test-source-artifact':result=source_test_artifact(args.image,args.context_manifest,args.output)
        else:
            from wealth_ledger.persistence.config import PostgresConfig
            from wealth_ledger.persistence.context import Database
            from wealth_ledger.persistence.migration import migrate,finalize_restore
            db=Database(PostgresConfig.from_secret_file(args.secret_file))
            try:
                result=db.status() if args.command=='status' else (migrate(db,args.runtime_role) if args.command=='migrate' else finalize_restore(db,args.runtime_role))
            finally:db.close()
        print(json.dumps(result));return 0
    except Exception as error:
        from wealth_ledger.persistence.errors import PersistenceError
        code=error.code if isinstance(error,PersistenceError) else 'operation_failed'
        print(json.dumps({'error':code}),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
