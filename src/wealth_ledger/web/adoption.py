"""Trusted-host copy/verify/switch of a stopped CLI workspace; never reimport."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import uuid

from ..locking import file_lock
from ..operations import list_operations
from ..workspace import resolve_workspace
from .backups import database_info, file_hash, MAX_FILES, MAX_TOTAL, MAX_FILE, safe_name, snapshot_database
from .jobs import digest, engine_fingerprint
from .maintenance import maintenance
from .storage import Store, contained, private_write

CONFIG_FILES = {'local.toml','bull-opening.json','company-aliases.json','company-aliases.override.json'}
FINISHED = {'published','data_only_complete','data_failed','stale'}


def inventory(source):
    """Select private financial state, not checkout instructions, credentials or code."""
    files, directories, links, databases = {}, [], {}, {}
    def walk(path):
        name = path.relative_to(source).as_posix();safe_name(name)
        if path.is_symlink():
            if name != 'reports/latest': raise ValueError('Unexpected workspace symlink')
            target = os.readlink(path);safe_name(target)
            if not (path.parent/target).is_dir() or not (path.parent/target).resolve().is_relative_to((source/'reports').resolve()):
                raise ValueError('Invalid latest report link')
            links[name]=target
        elif path.is_dir():
            directories.append(name)
            for child in sorted(path.iterdir()):walk(child)
        elif path.is_file() and stat.S_ISREG(path.stat().st_mode):
            if name in {'data/db/portfolio.sqlite3-wal','data/db/portfolio.sqlite3-shm','data/db/portfolio.sqlite3-journal'}:return
            if path.stat().st_size>MAX_FILE: raise ValueError('Workspace file exceeds adoption size bound')
            files[name]={'sha256':file_hash(path),'bytes':path.stat().st_size}
            if name=='data/db/portfolio.sqlite3':databases[name]=database_info(path)
        else: raise ValueError('Unsupported workspace entry')
    for name in ('data','reports','backups'):
        path=source/name
        if path.exists():walk(path)
    config=source/'config'
    if config.is_symlink():raise ValueError('Unexpected config symlink')
    if config.exists():
        directories.append('config')
        for name in sorted(CONFIG_FILES):
            path=config/name
            if path.exists() or path.is_symlink():walk(path)
    if len(files)+len(directories)+len(links)>MAX_FILES or sum(v['bytes'] for v in files.values())>MAX_TOTAL:
        raise ValueError('Workspace exceeds adoption bounds')
    if 'data/db/portfolio.sqlite3' not in databases:raise ValueError('Existing financial database is required')
    pending=[op for op in list_operations(source) if op['status'] not in FINISHED]
    if pending:raise ValueError('Resolve unfinished CLI operations before adoption; do not reimport committed inputs')
    return {'files':files,'directories':sorted(directories),'links':links,'databases':databases}


def verify_portfolio(project, *, allow_legacy_reports=False):
    """All source revisions and published bundles must retain their original evidence."""
    db=contained(project,'data/db/portfolio.sqlite3')
    from ..source_ingestion import verify_store
    verify_store(project)
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
        tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table,pathcol,hashcol in (('sources','path','sha256'),('crypto_sources','path','sha256'),
                ('wallet_revisions','source_path','sha256'),('crypto_opening_revisions','source_path','source_sha256')):
            if table in tables:
                for name,expected in conn.execute(f'SELECT "{pathcol}","{hashcol}" FROM "{table}"'):
                    path=contained(project,name)
                    if not name.startswith('data/raw/') or not path.is_file() or file_hash(path)!=expected:
                        raise ValueError('Original source evidence is missing or changed')
        if 'fund_sources' in tables:
            for (raw,) in conn.execute('SELECT payload_json FROM fund_sources'):
                for evidence in json.loads(raw).get('evidence',[]):
                    path=contained(project,evidence['path'])
                    if not evidence['path'].startswith('data/raw/') or not path.is_file() or file_hash(path)!=evidence['sha256']:
                        raise ValueError('Official source evidence is missing or changed')
    bundles=[]
    from .report_evidence import inspect_report, json_object
    for path in sorted((project/'reports').rglob('manifest.json')):
        manifest=json_object(path.read_bytes())
        if not isinstance(manifest.get('import'),dict):raise ValueError('Invalid report operation declaration')
        operation=manifest['import'].get('operation_id')
        bundles.append(inspect_report(project,path.parent,operation,allow_legacy=allow_legacy_reports))
    pointer=project/'reports/latest.json'
    if pointer.is_file():
        relative=json.loads(pointer.read_text())['path'];contained(project,relative)
        if relative not in {bundle['relative'] for bundle in bundles}:raise ValueError('Latest report is not a verified bundle')
        latest=project/'reports/latest'
        if latest.is_symlink() and latest.resolve()!=(project/relative).resolve():raise ValueError('Latest report pointers differ')
    from ..settings import report_locale,btc_cost_policy
    report_locale(project);btc_cost_policy(project)
    return bundles


def source_guard(source):
    return file_lock(contained(source,'work/update.guard'))


def validate_source(settings, workspace):
    original=Path(workspace).expanduser().absolute()
    if original.is_symlink():raise ValueError('Choose the original workspace directory, not a symlink')
    source=resolve_workspace(explicit=original).workspace_root
    if source.is_relative_to(settings.data_root) or settings.data_root.is_relative_to(source):
        raise ValueError('Source workspace and Web instance must be separate directories')
    if not (source/'work').is_dir():raise ValueError('Source work directory is required for exclusive locking')
    return source


def prepare_adoption(settings, workspace, name, output, *, allow_legacy_reports=False):
    store=Store(settings)
    if not store.owner():raise ValueError('Initialize the Web owner first')
    if not name.strip() or len(name)>80 or any(ord(c)<32 or ord(c)==127 for c in name):raise ValueError('Invalid portfolio name')
    source=validate_source(settings,workspace)
    output=Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(source) or output.resolve().is_relative_to(store.root):
        raise ValueError('Use a new private plan file outside both state directories')
    with source_guard(source):
        if (source/'work/update.lock').exists():raise ValueError('Stop source writes and review its update lock first')
        snapshot=inventory(source);bundles=verify_portfolio(source,allow_legacy_reports=allow_legacy_reports)
        plan={'format':'wealth-ledger-private-adoption','version':1,'engine':engine_fingerprint(),'source_root':str(source),'target_root':str(store.root),
              'allow_legacy_reports':allow_legacy_reports,'portfolio_id':uuid.uuid4().hex,'name':name.strip(),'created_at':datetime.now(timezone.utc).isoformat(),
              'snapshot':snapshot,'bundles':bundles,'excluded':['code and agent instructions','non-financial config including publication authorization',
                  'replaceable work cache/builds and runtime locks','active database WAL/SHM/journal (committed content is snapshotted)']}
        raw=(json.dumps(plan,sort_keys=True,indent=2)+'\n').encode()
        if len(raw)>16*1024**2:raise ValueError('Adoption plan exceeds the 16 MiB bound')
        with output.open('xb') as stream:output.chmod(0o600);stream.write(raw)
    return {'status':'adoption_preview','plan_sha256':digest(plan),'portfolio_id':plan['portfolio_id'],
            'financial_files':len(snapshot['files']),'reports':len(bundles),'source_preserved':True,
            'legacy_reports':sum('evidence' in b for b in bundles),
            'legacy_verification':'Migration-time capture; no original publication checksums or historical authenticity proof' if any('evidence' in b for b in bundles) else None,
            'next':'Review the private plan, stop all source writes, then adopt-confirm --plan FILE --plan-sha256 SHA'}


def confirm_adoption(settings, plan_path, expected_digest):
    path=Path(plan_path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>16*1024**2:raise ValueError('Invalid adoption plan')
    plan=json.loads(path.read_text())
    if not isinstance(plan,dict) or digest(plan)!=expected_digest or plan.get('format')!='wealth-ledger-private-adoption' or plan.get('version')!=1 or plan.get('engine')!=engine_fingerprint():
        raise ValueError('Adoption plan or engine changed; prepare a fresh preview')
    store=Store(settings);pid=plan['portfolio_id']
    from .storage import ID
    if not ID.fullmatch(pid) or plan['target_root']!=str(store.root):raise ValueError('Adoption destination differs')
    allow_legacy=plan.get('allow_legacy_reports',False)
    if type(allow_legacy) is not bool:raise ValueError('Invalid legacy acceptance policy')
    source=validate_source(settings,plan['source_root'])
    target=contained(store.root,'portfolios/'+pid)
    receipts=contained(store.root,'admin/adoptions');receipts.mkdir(exist_ok=True,mode=0o700)
    receipt=contained(receipts,pid+'.json')
    with maintenance(store.root),source_guard(source):
        previous=json.loads(receipt.read_text()) if receipt.exists() else None
        if previous and previous.get('plan_sha256')!=expected_digest:raise ValueError('Different adoption already owns this identity')
        with closing(store.connect()) as conn:
            registered=conn.execute('SELECT id FROM portfolios WHERE id=?',(pid,)).fetchone()
        if registered:
            if not previous:raise ValueError('Portfolio identity is already registered')
            private_write(receipt,json.dumps({**previous,'status':'complete'}).encode())
            return {'status':'already_adopted','portfolio_id':pid,'source_preserved':True}
        if (source/'work/update.lock').exists():raise ValueError('Stop source writes and review its update lock first')
        if inventory(source)!=plan['snapshot'] or verify_portfolio(source,allow_legacy_reports=allow_legacy)!=plan['bundles']:
            raise ValueError('Source changed after preview; prepare a new adoption plan')
        if target.exists() and not previous:raise ValueError('Adoption destination is not empty')
        with tempfile.TemporaryDirectory(prefix='adopt-',dir=contained(store.root,'cache')) as directory:
            stage=Path(directory)/'portfolio';stage.mkdir(mode=0o700)
            if target.exists():
                if any(p.name not in {'data','reports','backups','config','work'} for p in target.iterdir()) or any((target/'work').iterdir()):
                    raise ValueError('Interrupted adoption has unexpected local content; preserve it for host review')
                if (target/'config').exists() and any(p.name not in CONFIG_FILES for p in (target/'config').iterdir()):
                    raise ValueError('Interrupted adoption config scope differs')
                # A prior crash may leave an installed, unregistered exact copy.
                candidate=inventory(target)
                expected=plan['snapshot']
                if set(candidate['files'])!=set(expected['files']) or candidate['directories']!=expected['directories'] or candidate['links']!=expected['links'] or candidate['databases']!=expected['databases'] or any(file_hash(contained(target,n))!=v['sha256'] for n,v in expected['files'].items() if n not in expected['databases']):
                    raise ValueError('Interrupted adoption copy needs host review')
                shutil.rmtree(target)
            for name in plan['snapshot']['directories']:contained(stage,name).mkdir(parents=True,exist_ok=True,mode=0o700)
            for name,metadata in plan['snapshot']['files'].items():
                src=contained(source,name);dst=contained(stage,name)
                if name in plan['snapshot']['databases']:
                    if snapshot_database(src,dst)!=plan['snapshot']['databases'][name]:raise ValueError('Database changed during adoption')
                else:
                    shutil.copyfile(src,dst);dst.chmod(0o600)
                    if dst.stat().st_size!=metadata['bytes'] or file_hash(dst)!=metadata['sha256']:raise ValueError('Copied evidence differs')
            (stage/'work').mkdir(exist_ok=True,mode=0o700)
            for name,link in plan['snapshot']['links'].items():contained(stage,name).symlink_to(link,target_is_directory=True)
            if verify_portfolio(stage,allow_legacy_reports=allow_legacy)!=plan['bundles']:raise ValueError('Copied report relationships differ')
            if inventory(source)!=plan['snapshot']:raise ValueError('Source changed during adoption')
            record={'version':1,'plan_sha256':expected_digest,'source_root':str(source),'portfolio_id':pid,
                    'status':'installing','financial_database':plan['snapshot']['databases'],
                    'verification_captured_at':plan['created_at'],
                    'legacy_reports':{b['relative']:b['evidence'] for b in plan['bundles'] if 'evidence' in b},
                    'created_at':datetime.now(timezone.utc).isoformat()}
            private_write(receipt,json.dumps(record,sort_keys=True).encode())
            installed=False
            try:
                os.replace(stage,target);installed=True
                with store.transaction() as conn:
                    conn.execute('INSERT INTO portfolios VALUES(?,1,?,?)',(pid,plan['name'],store.clock()))
                    operations={op['operation_id']:op for op in list_operations(target)}
                    for index,bundle in enumerate(plan['bundles']):
                        report=uuid.uuid5(uuid.UUID(pid),bundle['relative']).hex
                        operation=bundle['operation']
                        if operation in operations and operations[operation]['status']!='published':raise ValueError('Report operation is not published')
                        result={'report_id':report,'valuation_as_of':bundle['as_of'],'snapshot_id':bundle['snapshot_id'],'adopted':True,'source_operation_id':operation}
                        if 'evidence' in bundle:
                            result['legacy_evidence_sha256']=digest(bundle['evidence'])
                            result['legacy_capture_at']=plan['created_at']
                        conn.execute("""INSERT INTO jobs(id,portfolio_id,kind,status,request_json,request_digest,execution_at,
                            idempotency_key,core_operation_id,result_json,created_at,updated_at)
                            VALUES(?,?,'update','published',?,?,?,?,?,?,?,?)""",
                            (report,pid,'{}',digest({'adopted':bundle['relative']}),bundle['as_of'],'adopt:'+report,None,
                             json.dumps(result),store.clock(),store.clock()+index/1000000))
                        for filename in bundle['files']:
                            # register_artifact queries the committed portfolio registry,
                            # so register exact verified bytes within this same transaction.
                            relative=bundle['relative']+'/'+filename;artifact=contained(target,relative)
                            from .storage import ARTIFACT_TYPES,MAX_ARTIFACT_BYTES
                            media=ARTIFACT_TYPES.get(artifact.suffix.lower())
                            if not media or artifact.stat().st_size>MAX_ARTIFACT_BYTES:raise ValueError('Unsupported historical artifact')
                            conn.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)',(uuid.uuid4().hex,pid,report,relative,
                                file_hash(artifact),artifact.stat().st_size,media))
            except BaseException:
                with closing(store.connect()) as check:
                    committed=check.execute('SELECT 1 FROM portfolios WHERE id=?',(pid,)).fetchone()
                if not committed:
                    if installed:shutil.rmtree(target)
                    receipt.unlink(missing_ok=True)
                # A committed registry and its files survive uncertain completion;
                # the exact plan retry can finish the private receipt safely.
                raise
            private_write(receipt,json.dumps({**record,'status':'complete'},sort_keys=True).encode())
    return {'status':'adopted','portfolio_id':pid,'reports':len(plan['bundles']),'source_preserved':True,
            'financial_values_verified':True,'report_regenerated':False}
