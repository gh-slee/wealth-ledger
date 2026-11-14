"""Explicit private connection configuration; never discover a legacy workspace."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
from .errors import PersistenceError

@dataclass(frozen=True, slots=True)
class PostgresConfig:
    conninfo: str = field(repr=False)
    pool_size: int = 5

    def __post_init__(self):
        if (type(self.conninfo) is not str or not 1 <= len(self.conninfo) <= 16384
                or type(self.pool_size) is not int or not 1 <= self.pool_size <= 5):
            raise PersistenceError("invalid_config")
        from psycopg.conninfo import conninfo_to_dict
        try:
            values = conninfo_to_dict(self.conninfo)
            if not values.get("dbname") or not values.get("user"):
                raise ValueError()
        except Exception:
            raise PersistenceError("invalid_config") from None

    @classmethod
    def from_secret_file(cls, path, *, pool_size=5):
        descriptor = None
        try:
            descriptor = os.open(Path(path), os.O_RDONLY | os.O_NOFOLLOW)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise ValueError()
            raw = os.read(descriptor, 16385)
            if len(raw) > 16384:
                raise ValueError()
            return cls(raw.decode("utf-8").strip(), pool_size)
        except (OSError, ValueError, UnicodeError):
            raise PersistenceError("invalid_config") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
