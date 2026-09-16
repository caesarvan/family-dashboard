"""Serve an immutable Expo Web export without changing API authentication."""
from pathlib import Path
from urllib.parse import urlencode

from flask import abort, redirect, request, send_file, send_from_directory


PUBLIC_TYPES = {
    '.js': 'text/javascript', '.css': 'text/css',
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.webp': 'image/webp', '.gif': 'image/gif', '.svg': 'image/svg+xml',
    '.ico': 'image/vnd.microsoft.icon', '.avif': 'image/avif',
    '.ttf': 'font/ttf', '.otf': 'font/otf', '.woff': 'font/woff',
    '.woff2': 'font/woff2',
}


def _linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def register_frontend_runtime(app, static_root):
    """Register public export routes and return the guarded home-page handler."""
    static_root = Path(static_root)
    export_root = static_root / 'experience'

    def safe_file(name):
        # URL decoding has already happened. Reject alternate Windows paths as
        # well as traversal, hidden build files, symlinks and junctions.
        parts = name.split('/')
        if (not name or any(c in name for c in ('\\', ':', '%'))
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or any(not p or p.startswith('.') or p.endswith((' ', '.')) for p in parts)):
            abort(404)
        try:
            if _linked(static_root) or _linked(export_root):
                abort(404)
            path = export_root
            for part in parts:
                path = path / part
                if _linked(path):
                    abort(404)
            if not path.resolve().is_relative_to(export_root.resolve()):
                abort(404)
            return path if path.is_file() else None
        except OSError:
            abort(404)

    def index_file():
        return safe_file('index.html')

    def serve(path, mimetype):
        response = send_file(path, mimetype=mimetype, conditional=False, max_age=0)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/classic')
    def classic_frontend():
        response = send_from_directory(static_root, 'index.html')
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/app', defaults={'name': ''}, strict_slashes=False)
    @app.get('/app/<path:name>')
    def expo_frontend(name):
        if not name or name == 'index.html':
            path = index_file()
            if path is None:
                abort(404)
            return serve(path, 'text/html')
        path = safe_file(name)
        suffix = Path(name).suffix.lower()
        if path is not None:
            if suffix not in PUBLIC_TYPES:
                abort(404)
            return serve(path, PUBLIC_TYPES[suffix])
        # Asset namespaces, dotted paths and unknown file types never receive
        # HTML. Only an extensionless client route can use the SPA entry.
        if name.split('/')[0] in {'_expo', 'assets'} or any('.' in p for p in name.split('/')):
            abort(404)
        path = index_file()
        if path is None:
            abort(404)
        return serve(path, 'text/html')

    def home_frontend():
        # These callbacks continue the existing source-selection/import flow.
        # Forward only the known status fields, never provider codes or tokens.
        auth = request.args.get('auth')
        if auth in {'connected', 'photos-connected', 'error'}:
            query = {'auth': auth}
            if auth == 'error':
                query['reason'] = request.args.get('reason', '')[:80]
            response = redirect('/classic?' + urlencode(query), code=302)
            response.headers['Cache-Control'] = 'no-store'
            return response
        # A checkout without a build keeps the working classic entry. Invalid
        # linked exports fail closed rather than redirecting to outside files.
        if index_file() is not None:
            response = redirect('/app', code=302)
        else:
            response = send_from_directory(static_root, 'index.html')
        response.headers['Cache-Control'] = 'no-store'
        return response

    return home_frontend
