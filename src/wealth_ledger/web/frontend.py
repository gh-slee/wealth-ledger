"""Serve only built application assets; financial files never enter a static route."""
from pathlib import Path

from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

from ..workspace import CODE_ROOT


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


def install_frontend(app, root=None):
    root = Path(root) if root is not None else CODE_ROOT / "frontend/dist"
    index = root / "index.html"
    if not index.is_file() or index.is_symlink():
        return
    markup = index.read_text(encoding="utf-8")
    app.mount("/assets", BuildFiles(directory=root / "assets", follow_symlink=False), name="frontend-assets")
    if (root / "licenses").is_dir():
        app.mount("/licenses", BuildFiles(directory=root / "licenses", follow_symlink=False), name="frontend-licenses")
    # Explicit SPA paths cannot fall back for /api, /data or arbitrary host files.
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/login", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/app", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/app/{page:path}", response_class=HTMLResponse, include_in_schema=False)
    def frontend(page=""):
        return HTMLResponse(markup)
