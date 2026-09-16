"""Real backend contract exercised by the compiled Expo assistant flow, without external AI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading

from werkzeug.serving import WSGIRequestHandler, make_server

from test_app import app, member


class Quiet(WSGIRequestHandler):
    def log(self, *_args, **_kwargs):
        pass


def test_real_expo_assistant_flow(app, tmp_path):
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    assert node, 'Node is required for this Expo-specific contract check'
    app.config['ASSISTANT_PROVIDER'] = 'local'
    one, headers = member(app)
    two, _ = member(app, 2)
    new_one, _ = member(app)
    cookie_name = app.config['SESSION_COOKIE_NAME']
    def cookie(client):
        return cookie_name + '=' + client.get_cookie(cookie_name).value
    for index in range(22):
        response = one.post('/api/items/tasks', json={'title': f'分页合成 {index:02}', 'sourceId': ''}, headers=headers)
        assert response.status_code == 201
    server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    result = tmp_path / 'flow-result.json'
    env = dict(os.environ, ASSISTANT_TEST_ROOT=str(root), ASSISTANT_TEST_ORIGIN=f'http://127.0.0.1:{server.server_port}',
               ASSISTANT_TEST_COOKIE1=cookie(one), ASSISTANT_TEST_COOKIE2=cookie(two), ASSISTANT_TEST_COOKIE1_NEW=cookie(new_one),
               ASSISTANT_TEST_REPORT=str(result))
    try:
        completed = subprocess.run([node, str(root / 'tests/expo_assistant_flow.cjs')], env=env,
                                   capture_output=True, text=True, encoding='utf-8', timeout=90)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        report = json.loads(result.read_text('utf-8'))
        assert report['passed'] and len(report['checks']) == 12
        print(completed.stdout)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
