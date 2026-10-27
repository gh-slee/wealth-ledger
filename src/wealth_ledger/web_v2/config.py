"""Explicit private connection/key files for a single direct PostgreSQL target."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
from urllib.parse import urlsplit


def private_bytes(path,maximum):
    descriptor=None
    try:
        descriptor=os.open(Path(path),os.O_RDONLY|os.O_NOFOLLOW)
        meta=os.fstat(descriptor)
        if not stat.S_ISREG(meta.st_mode) or meta.st_mode&0o077 or meta.st_size>maximum:
            raise ValueError()
        raw=os.read(descriptor,maximum+1)
        if len(raw)>maximum:
            raise ValueError()
        return raw
    except Exception:
        raise ValueError('Invalid private configuration') from None
    finally:
        if descriptor is not None:os.close(descriptor)


def connection_options(config):
    from psycopg.conninfo import conninfo_to_dict
    values=conninfo_to_dict(config.conninfo)
    allowed={'host','hostaddr','port','dbname','user','password','sslmode','sslrootcert','sslcert','sslkey','connect_timeout','application_name'}
    if (not set(values)<=allowed or any(not values.get(k) for k in ['host','port','dbname','user','password','sslmode'])
            or any(',' in values.get(k,'') for k in ['host','hostaddr','port'])
            or not values['port'].isascii() or not values['port'].isdigit() or not 1<=int(values['port'])<=65535
            or values['sslmode'] not in {'disable','allow','prefer','require','verify-ca','verify-full'}):
        raise ValueError('Invalid direct database configuration')
    return values


@dataclass(frozen=True,slots=True)
class Settings:
    identity: object=field(repr=False)
    financial: object=field(repr=False)
    key: bytes=field(repr=False)
    origin: str

    def __post_init__(self):
        try:
            if any(name.startswith('PG') and value for name,value in os.environ.items()):
                raise ValueError()
            left=connection_options(self.identity);right=connection_options(self.financial)
            target=lambda d:{k:v for k,v in d.items() if k not in {'user','password','application_name'}}
            if target(left)!=target(right) or left['user']==right['user'] or type(self.key) is not bytes or len(self.key)!=32:
                raise ValueError()
            origin=urlsplit(self.origin)
            if (origin.scheme not in {'http','https'} or not origin.hostname or origin.username or origin.password
                    or origin.path or origin.query or origin.fragment or any(c.isspace() or ord(c)<32 for c in self.origin)
                    or origin.scheme=='http' and origin.hostname not in {'127.0.0.1','localhost','::1'}):
                raise ValueError()
            origin.port
        except Exception:
            raise ValueError('Invalid explicit identity configuration') from None

    @classmethod
    def from_files(cls,identity_file,financial_file,key_file,origin,*,pool_size=5):
        from wealth_ledger.persistence.config import PostgresConfig
        return cls(PostgresConfig.from_secret_file(identity_file,pool_size=pool_size),
                   PostgresConfig.from_secret_file(financial_file,pool_size=pool_size),private_bytes(key_file,32),origin)

    @property
    def host(self):
        return urlsplit(self.origin).netloc.lower()

    @property
    def secure(self):
        return urlsplit(self.origin).scheme=='https'

    @property
    def cookie_name(self):
        return '__Host-wealth_v2_session' if self.secure else 'wealth_v2_session'
