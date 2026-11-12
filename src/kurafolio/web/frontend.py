"""Serve only built application assets; financial files never enter a static route."""
from pathlib import Path

from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from ..workspace import CODE_ROOT

# Browser application pages receive this policy; API responses keep a deny-all policy.
APP_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
DEFAULT_ROOT = CODE_ROOT / "frontend/dist"


class BuildFiles(StaticFiles):
    async def get_response(self, path, scope):
        # Source maps, dotfiles and symlinks are never public build assets.
        if any(part.startswith(".") for part in Path(path).parts) or path.endswith(".map"):
            from starlette.exceptions import HTTPException
            raise HTTPException(404)
        target = Path(self.directory) / path
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent != Path(self.directory)):
            from starlette.exceptions import HTTPException
            raise HTTPException(404)
        return await super().get_response(path, scope)


def install_frontend(app, root=None, *, pages=("/", "/login"), licenses=True):
    """Mount a built bundle; return False, adding no route, when none is present."""
    root = Path(root) if root is not None else DEFAULT_ROOT
    index = root / "index.html"
    if not index.is_file() or index.is_symlink():
        return False
    markup = index.read_text(encoding="utf-8")
    app.mount("/assets", BuildFiles(directory=root / "assets", follow_symlink=False), name="frontend-assets")
    if licenses and (root / "licenses").is_dir():
        app.mount("/licenses", BuildFiles(directory=root / "licenses", follow_symlink=False), name="frontend-licenses")

    def frontend(page=""):
        return HTMLResponse(markup)
    # Explicit SPA paths cannot fall back for /api, /data or arbitrary host files.
    for path in (*pages, "/app", "/app/{page:path}"):
        app.add_api_route(path, frontend, methods=["GET"], response_class=HTMLResponse, include_in_schema=False)
    return True
