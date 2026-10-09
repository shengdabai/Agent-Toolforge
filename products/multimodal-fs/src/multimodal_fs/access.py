"""Explicit POSIX file boundary for the MCP entrypoint, not a parser sandbox."""
import fnmatch
import os
from pathlib import Path
import stat

MAX_BYTES = 8 * 1024 * 1024
SECRET_NAMES = (".env*", "auth.json", "*.key", "*.pem", "id_rsa*", "credentials.*", "secrets.*", ".npmrc")


class FileAccess:
    def __init__(self, root):
        if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            raise ValueError("This file boundary requires POSIX no-follow and dir_fd support")
        self.root = Path(root).resolve(strict=True)
        if any(p.lower() in (".ssh", ".aws") or any(fnmatch.fnmatch(p.lower(), pattern) for pattern in SECRET_NAMES) for p in self.root.parts):
            raise PermissionError("Credential directories cannot be configured as a read root")
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read(self, path):
        requested = Path(path)
        relative = requested.relative_to(self.root) if requested.is_absolute() else requested
        parts = relative.parts
        if not parts or any(p.lower() in ("..", ".ssh", ".aws") for p in parts):
            raise PermissionError("Path outside permitted file scope")
        if any(any(fnmatch.fnmatch(p.lower(), pattern) for pattern in SECRET_NAMES) for p in parts):
            raise PermissionError("Credential files are not exposed by this tool")
        fd = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                    raise PermissionError("Only regular, single-link files up to 8 MiB are supported")
                data = source.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise PermissionError("File grew beyond 8 MiB")
                return data, requested.suffix
        finally:
            os.close(fd)
