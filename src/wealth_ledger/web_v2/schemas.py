"""Closed optional V2 wire schemas. Validation errors are never echoed to clients."""
from typing import Annotated, Literal
import re
from pydantic import BaseModel, ConfigDict, Field, AfterValidator, SecretStr, field_validator, model_validator
from wealth_ledger.persistence.errors import CODES


def password(value, minimum=15):
    if not minimum <= len(value) <= 256 or '\x00' in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError('Invalid password')
    return value


def canonical_uuid(value):
    from wealth_ledger.persistence.context import identifier
    try:
        identifier(value)
    except Exception:
        raise ValueError("Invalid UUID") from None
    return value


NewPassword = Annotated[str, Field(min_length=15, max_length=256, repr=False), AfterValidator(password)]
CurrentPassword = Annotated[str, Field(min_length=1, max_length=256, repr=False), AfterValidator(lambda v: password(v, 1))]
Username = Annotated[str, Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_.-]+$'),
                     AfterValidator(lambda v: v if re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',v) else (_ for _ in ()).throw(ValueError()))]
UUID = Annotated[str, AfterValidator(canonical_uuid)]
Token = Annotated[str, Field(min_length=43,max_length=43,pattern=r'^[A-Za-z0-9_-]+$',repr=False)]
Hex = Annotated[str, Field(min_length=64,max_length=64,pattern=r'^[0-9a-f]+$',repr=False)]
Timestamp = Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$')]


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True,hide_input_in_errors=True)

    @field_validator('password',check_fields=False)
    @classmethod
    def bounded_password(cls,value):
        password(value.get_secret_value(),1)
        return value


class Empty(Closed):
    pass


class Login(Closed):
    username: Username
    password: SecretStr = Field(min_length=1, max_length=256)


class Register(Closed):
    invite_token: Token
    username: Username
    password: SecretStr = Field(min_length=15, max_length=256)


class Setup(Closed):
    setup_token: Token
    username: Username
    password: SecretStr = Field(min_length=15, max_length=256)


class ChangePassword(Closed):
    current_password: CurrentPassword
    new_password: NewPassword


class InviteIssue(Closed):
    issue_request_id: UUID


class Alive(Closed):
    alive: Literal[True]


class Ready(Closed):
    ready: bool


class Csrf(Closed):
    csrf_token: Hex
    authenticated: bool


class LoggedIn(Closed):
    authenticated: Literal[True]
    csrf_token: Hex


class Registered(Closed):
    registered: Literal[True]


class Initialized(Closed):
    initialized: Literal[True]


class User(Closed):
    id: UUID
    username: Username
    role: Literal['instance_admin','member']


class Portfolio(Closed):
    id: UUID


class Me(Closed):
    authenticated: Literal[True]
    user: User
    portfolio: Portfolio


class Invitation(Closed):
    id: UUID
    issue_request_id: UUID | None
    created_at: Timestamp
    expires_at: Timestamp
    status: Literal['issued','expired','revoked','consumed']
    revocation_reason: Literal['manual','restore'] | None


class InvitationIssued(Closed):
    id: UUID
    issue_request_id: UUID
    invite_token: Token
    expires_at: Timestamp


class Invitations(Closed):
    items: list[Invitation]
    next_after: UUID | None


class Job(Closed):
    id: UUID
    kind: Literal['foundation']
    status: Literal['queued','running','retryable_error','succeeded','failed','cancelled']
    attempt: Annotated[int,Field(ge=0,le=3)]
    error_code: Literal[tuple(sorted(CODES | {'internal_error'}))] | None


ERROR_CODES = ('invalid_headers','invalid_host','invalid_length','not_found','method_not_allowed',
 'origin_rejected','authentication_required','invalid_credentials','csrf_rejected','anonymous_session_required',
 'unsupported_media_type','body_too_large','request_timeout','invalid_input','rate_limited','authentication_busy',
 'credentials_changed','session_changed','registration_rejected','instance_not_ready','internal_error',
 'setup_rejected','setup_closed','setup_required','admin_required','invite_already_issued','invite_not_active',
 'source_catalog_unavailable','source_unavailable','source_capability_unavailable','source_context_incompatible',
 'source_connection_conflict','source_revision_conflict','source_idempotency_conflict','source_repreview_required',
 'source_capacity_reached','source_counter_exhausted','source_commit_uncertain')


class ErrorDetail(Closed):
    code: Literal[ERROR_CODES]
    message: str
    request_id: Annotated[str,Field(pattern=r'^[0-9a-f]{32}$')]


class Error(Closed):
    error: ErrorDetail


# Sources are available only in the explicit0003 backend profile. These models
# contain metadata, never financial values or executable plugin configuration.
def source_counter(value):
    from wealth_ledger.data_sources.contract_v1 import counter
    return counter(value)


def source_text(value):
    import unicodedata
    if value != value.strip() or any(unicodedata.category(ch)=='Cc' or 0xD800<=ord(ch)<=0xDFFF for ch in value):
        raise ValueError('Invalid source label')
    return value


Counter = Annotated[str,AfterValidator(source_counter)]
PositiveCounter = Annotated[str,AfterValidator(lambda v: source_counter(v) if v!='0' else (_ for _ in ()).throw(ValueError('Positive counter required')))]
Namespace = Annotated[str,Field(min_length=1,max_length=64,pattern=r'^[a-z][a-z0-9_.-]{0,63}$')]
SourceLabel = Annotated[str,Field(min_length=1,max_length=100),AfterValidator(source_text)]
SourceAlias = Annotated[str,Field(min_length=1,max_length=160),AfterValidator(source_text)]
SourceCapability = Literal['FILE_IMPORT','PULL_API']
VersionOne = Annotated[int,Field(strict=True,ge=1,le=1)]


class SourceRealm(Closed):
    incarnation: UUID
    restore_epoch: Counter


class SourceCommon(Closed):
    operation_id: UUID
    expected_revision: Counter
    expected_realm: SourceRealm


class SourceEnableRequest(SourceCommon):
    enabled: bool
    installation_id: Hex | None

    @model_validator(mode='after')
    def installation_required(self):
        if self.enabled != (self.installation_id is not None):
            raise ValueError('Explicit installation confirmation required')
        return self


class SourceCreateRequest(SourceCommon):
    plugin_id: Namespace
    capability: SourceCapability
    installation_id: Hex
    display_label: SourceLabel
    parser_source_alias: SourceAlias | None

    @model_validator(mode='after')
    def initial_revision(self):
        if self.expected_revision!='0':
            raise ValueError('Create revision must be zero')
        return self


class SourceUpdateRequest(SourceCommon):
    enabled: bool
    installation_id: Hex
    display_label: SourceLabel


class SourceEnablement(Closed):
    enabled: bool
    installation_id: Hex | None
    revision: Counter
    generation: Counter


class Capability(Closed):
    capability: SourceCapability
    active_installation_id: Hex | None
    availability_generation: PositiveCounter | None
    adapter_id: Namespace | None
    package_version: Annotated[str,Field(min_length=1,max_length=200)] | None
    format_versions: Annotated[list[Annotated[str,Field(min_length=1,max_length=128)]],Field(max_length=32)]
    domain_contract_version: VersionOne
    parser_api_version: Annotated[int,Field(strict=True,ge=2,le=2)] | None
    enablement: SourceEnablement
    status: Literal['DISABLED','CONFIRMATION_REQUIRED','UNAVAILABLE','ENABLED']
    reason: Literal['source_unavailable','source_capability_unavailable','source_counter_exhausted'] | None
    connection_count: Annotated[int,Field(strict=True,ge=0,le=256)]


class CatalogItem(Closed):
    plugin_id: Namespace
    provider_id: Namespace
    display_name: Annotated[str,Field(min_length=1,max_length=100)]
    publisher_label: Annotated[str,Field(min_length=1,max_length=100)]
    docs_url: Annotated[str,Field(max_length=1024)] | None
    capabilities: Annotated[list[Capability],Field(max_length=2)]


class SourceCatalogPage(Closed):
    items: Annotated[list[CatalogItem],Field(max_length=100)]
    next_after: Namespace | None
    catalog_revision: Counter
    state_revision: Counter
    realm: SourceRealm


class SourceConnection(Closed):
    id: UUID
    connection_version: Hex
    plugin_id: Namespace
    provider_id: Namespace
    capability: Literal['FILE_IMPORT']
    installation_id: Hex
    availability_generation: PositiveCounter
    display_label: SourceLabel
    parser_source_alias: SourceAlias | None
    enabled: bool
    revision: Counter
    generation: Counter
    status: Literal['DISABLED','SOURCE_DISABLED','CONFIRMATION_REQUIRED','UNAVAILABLE','ENABLED']
    reason: Literal['source_unavailable','source_context_incompatible','source_counter_exhausted'] | None


class SourceConnectionPage(Closed):
    items: Annotated[list[SourceConnection],Field(max_length=100)]
    next_after: UUID | None
    catalog_revision: Counter
    state_revision: Counter
    realm: SourceRealm


class SourceConnectionRead(Closed):
    resource: SourceConnection
    catalog_revision: Counter
    state_revision: Counter
    realm: SourceRealm


class SourceMutation(Closed):
    operation_id: UUID
    replayed: bool
    representation: Literal['committed','historical']
    changed: bool
    resource: SourceEnablement | SourceConnection
    catalog_revision: Counter
    state_revision: Counter
    realm: SourceRealm


class SourceEnableMutation(SourceMutation):
    resource: SourceEnablement


class SourceConnectionMutation(SourceMutation):
    resource: SourceConnection
