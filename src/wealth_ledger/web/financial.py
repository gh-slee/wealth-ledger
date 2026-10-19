"""Typed data-only declarations, simulated off-ledger and committed by the worker."""
from contextlib import closing
from datetime import date, datetime
import csv
import io
import json
import sqlite3
from pathlib import Path
import tempfile
from typing import Annotated, Literal

from fastapi import Depends, Header, Request
from pydantic import Field, JsonValue, TypeAdapter, model_validator

from .imports import Input, JobView, Confirmation
from .jobs import Jobs, engine_fingerprint
from .storage import WebError

Text = Annotated[str, Field(min_length=1, max_length=240, pattern=r"^[^\x00-\x1f\x7f]+$")]
BTC = Annotated[str, Field(max_length=40, pattern=r"^(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,8})?$")]
Money = Annotated[str, Field(max_length=40, pattern=r"^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,12})?$")]
RecordID = Annotated[str, Field(pattern=r"^[BE][0-9]{6,18}$")]
EventType = Literal['fee','sale','spend','external_out','external_in','own_transfer','conversion']


class BalanceDeclaration(Input):
    command: Literal['balance']
    quantity_btc: BTC
    as_of: Text
    source: Text
    replaces: RecordID | None = None


class EventDeclaration(Input):
    command: Literal['event']
    type: EventType
    quantity_btc: BTC
    occurred_at: Text
    source: Text
    reference: Text
    balance_id: RecordID | None = None
    replaces: RecordID | None = None


class WalletRevision(Input):
    command: Literal['revision']
    record_id: RecordID
    expected_revision: int = Field(ge=1)
    reason: Text
    action: Literal['revise','void','link','unlink']
    quantity_btc: BTC | None = None
    source: Text | None = None
    type: EventType | None = None
    occurred_at: Text | None = None
    balance_id: RecordID | None = None

    @model_validator(mode='after')
    def changes(self):
        supplied = self.model_fields_set - {'command','record_id','expected_revision','reason','action'}
        if self.action == 'void' and supplied:
            raise ValueError('Void cannot include changes')
        if self.action == 'link' and (supplied != {'balance_id'} or self.balance_id is None):
            raise ValueError('Link requires a balance ID only')
        if self.action == 'unlink' and supplied:
            raise ValueError('Unlink cannot include changes')
        if self.action == 'revise' and (not supplied or 'balance_id' in supplied or any(getattr(self,k) is None for k in supplied)):
            raise ValueError('Revise requires explicit non-null changes')
        return self


class OpeningDeclaration(Input):
    command: Literal['opening']
    expected_revision: int = Field(ge=0)
    reported_total_btc_equivalent: BTC
    reference_as_of: Text
    declared_on: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    balance_scope: Literal['all_wallets_btc_plus_lbtc']
    basis: Text
    confirmed_by: Text


class CashFlowDeclaration(Input):
    command: Literal['cash_flow']
    date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    account_id: str = Field(pattern=r'^a_[a-f0-9]{16}$')
    flow_type: Literal['deposit','withdrawal','transfer_in','transfer_out','income','fee','internal']
    currency: Literal['CAD','USD']
    amount: Money
    flow_id: Text
    transfer_id: Text | None = None
    usd_cad: Money | None = None
    amount_cad: Money | None = None
    fx_date: str | None = Field(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$')
    fx_source: Text | None = None


class FlowUpload(Input):
    command: Literal['cash_flow_upload']
    upload_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class CoverageDeclaration(Input):
    command: Literal['coverage']
    start_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    status: Literal['partial','complete','no_external']
    account_id: str = Field(default='portfolio',pattern=r'^(?:portfolio|a_[a-f0-9]{16})$')


Declaration = Annotated[BalanceDeclaration | EventDeclaration | WalletRevision | OpeningDeclaration |
                         CashFlowDeclaration | FlowUpload | CoverageDeclaration, Field(discriminator='command')]
ADAPTER = TypeAdapter(Declaration)


class FinancialState(Input):
    accounts: list[dict[str, JsonValue]]
    balances: list[dict[str, JsonValue]]
    events: list[dict[str, JsonValue]]
    opening: dict[str, JsonValue] | None
    cash_flows: list[dict[str, JsonValue]]
    coverage: list[dict[str, JsonValue]]
    input_fingerprint: str
    truncated: bool


def safe_record(row):
    allowed = {'record_id','kind','revision','quantity_btc','as_of','source','type','occurred_at',
               'reference','balance_id','void','reason','action','replaces','recorded_expected_btc',
               'recorded_residual_btc','status','record_type','opening_btc_equivalent_qty',
               'reference_as_of','reported_total_btc_equivalent','reference_purchased_btc_equivalent','reference_known_event_btc',
               'imported','id','cost_cad','historical_contribution_cad','declared_on','basis','confirmed_by','integrity_ok'}
    return {k:v for k,v in row.items() if k in allowed}


def financial_state(project):
    from ..application import ApplicationService
    from ..workspace import resolve_workspace
    from .. import wallet
    from ..crypto_opening import latest_opening
    from ..operations import input_fingerprint
    balances = wallet.records(project,'balance'); events = wallet.records(project,'event')
    opening = latest_opening(project)
    flows, coverage = [], []
    database = project/'data/db/portfolio.sqlite3'
    if database.is_file():
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'cash_flows' in tables:
                flows = [json.loads(r[0]) for r in conn.execute('SELECT payload_json FROM cash_flows ORDER BY flow_date DESC,flow_id LIMIT 1001')]
            if 'flow_periods' in tables:
                coverage = [dict(r) for r in conn.execute('SELECT id,start_date,end_date,account_id,status FROM flow_periods ORDER BY id DESC LIMIT 1001')]
    return {'accounts':ApplicationService(resolve_workspace(explicit=project)).accounts(),
            'balances':[safe_record(r) for r in balances[:1000]],'events':[safe_record(r) for r in events[:1000]],
            'opening':safe_record(opening) if opening else None,'cash_flows':flows[:1000], 'coverage':coverage[:1000],
            'input_fingerprint':input_fingerprint(project),'truncated':any(len(v)>1000 for v in (balances,events,flows,coverage))}


def apply_declaration(stage, request, *, upload_path=None, now=None):
    """Reuse CLI/core validators. No prices, reports, or contribution inference."""
    model = ADAPTER.validate_python(request)
    values = model.model_dump(exclude={'command'},exclude_none=True)
    from .. import wallet
    from ..core import mark_flow_period, import_cash_flows
    from ..crypto_opening import import_opening, latest_opening
    if model.command == 'balance':
        return wallet.add_balance(stage, values.pop('quantity_btc'), values.pop('as_of'), now=now, **values)
    if model.command == 'event':
        return wallet.add_event(stage, now=now, **values)
    if model.command == 'revision':
        if model.action == 'unlink': values['balance_id'] = None
        return wallet.revise(stage, **values)
    if model.command == 'coverage':
        return mark_flow_period(stage, **values)
    if model.command == 'cash_flow_upload':
        if upload_path is None: raise ValueError('Verified cash-flow upload is required')
        return import_cash_flows(stage, upload_path)
    if model.command == 'opening':
        current = latest_opening(stage)
        if (current['revision'] if current else 0) != values.pop('expected_revision'):
            raise ValueError('Opening revision changed')
        if date.fromisoformat(values['declared_on']) > datetime.fromisoformat(now).date():
            raise ValueError('Declaration date cannot be in the future')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'opening-declaration.json'
            path.write_text(json.dumps(values,sort_keys=True)+'\n',encoding='utf-8')
            return import_opening(stage,path)
    values = {k:str(v) for k,v in values.items()}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'cash-flow-declaration.csv'
        stream = io.StringIO(newline=''); writer = csv.DictWriter(stream,fieldnames=sorted(values))
        writer.writeheader();writer.writerow(values);path.write_text(stream.getvalue(),encoding='utf-8',newline='')
        return import_cash_flows(stage,path)


def declaration_upload(store, row):
    request = json.loads(row['request_json'])
    if request['engine_fingerprint'] != engine_fingerprint():
        raise WebError(409,'stale_engine','Application changed; run preview again')
    if request['declaration']['command'] != 'cash_flow_upload': return None
    from .uploads import get_upload, verified_upload
    upload = get_upload(store,row['portfolio_id'],request['declaration']['upload_id'])
    if upload['kind'] != 'cash_flows' or upload['sha256'] != request['upload_sha256']:
        raise WebError(409,'upload_integrity','Cash-flow evidence changed')
    return verified_upload(store,upload)


def preview_declaration(project, request, *, upload_path=None, now=None):
    from ..preflight import _snapshot
    with tempfile.TemporaryDirectory(prefix='wealth-ledger-record-preview-') as directory:
        stage = Path(directory)/'project';_snapshot(project,stage)
        result = apply_declaration(stage,request,upload_path=upload_path,now=now)
        return {'status':'ready','declaration':request,'result':safe_record(result) or result,
                'report_published':False,'network_used':False,'live_data_changed':False}


class FinancialRecordDetail(Input):
    record: dict[str, JsonValue]
    revisions: list[dict[str, JsonValue]]
    reconciliation: dict[str, JsonValue] | None = None


def install_financial_routes(app, store, auth, require_owner):
    jobs=Jobs(store); prefix='/api/v1/portfolios/{portfolio_id}/financial'

    @app.get(prefix,response_model=FinancialState)
    def state(portfolio_id: str, owner=Depends(require_owner)):
        _,project=store.portfolio(portfolio_id,owner['owner_id'])
        return financial_state(project)

    @app.get(prefix+'/records/{record_id}',response_model=FinancialRecordDetail)
    def record(portfolio_id: str,record_id: str,owner=Depends(require_owner)):
        _,project=store.portfolio(portfolio_id,owner['owner_id'])
        from .. import wallet
        try:
            row=wallet.get_record(project,record_id)
            value={'record':safe_record(row),'revisions':[safe_record(r) for r in wallet.revision_history(project,record_id)]}
            if row['kind']=='balance':
                reconciliation=wallet.balance_detail(project,record_id)['reconciliation']
                value['reconciliation']={k:v for k,v in reconciliation.items() if k!='status_label'} if reconciliation else None
            return value
        except ValueError as exc: raise WebError(404,'not_found','Record not found') from exc

    @app.post(prefix+'/previews',status_code=202,response_model=JobView)
    def preview(portfolio_id: str,body: Declaration,request: Request,
                idempotency_key: str | None=Header(default=None),owner=Depends(require_owner)):
        value=body.model_dump(exclude_none=True)
        # Unlink explicitly supplies its null in the service, not as an ambiguous edit.
        row=jobs.record_preview(portfolio_id,value,idempotency_key,owner['owner_id'])
        auth.touch(request.cookies.get(store.settings.cookie_name));return jobs.view(row)

    @app.post(prefix+'/jobs',status_code=202,response_model=JobView)
    def confirm(portfolio_id: str,body: Confirmation,request: Request,
                idempotency_key: str | None=Header(default=None),owner=Depends(require_owner)):
        row=jobs.confirm(portfolio_id,body.preview_id,idempotency_key,owner['owner_id'],preview_kind='record_preview')
        auth.touch(request.cookies.get(store.settings.cookie_name));return jobs.view(row)
