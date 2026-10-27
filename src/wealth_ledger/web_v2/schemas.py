"""Closed optional V2 wire schemas. Validation errors are never echoed to clients."""
from typing import Annotated, Literal
import re
from pydantic import BaseModel, ConfigDict, Field, AfterValidator, SecretStr, field_validator
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
 'setup_rejected','setup_closed','setup_required','admin_required','invite_already_issued','invite_not_active')


class ErrorDetail(Closed):
    code: Literal[ERROR_CODES]
    message: str
    request_id: Annotated[str,Field(pattern=r'^[0-9a-f]{32}$')]


class Error(Closed):
    error: ErrorDetail
