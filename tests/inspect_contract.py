"""Generate a source-only route/schema inventory using disposable test databases.

Run from the project root. Never loads .env or accesses production services.
"""
from contextlib import closing
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app


def schema(path):
    with closing(sqlite3.connect(path)) as con:
        tables = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        return {table: [dict(name=r[1], type=r[2], notNull=bool(r[3]), primaryKey=bool(r[5]))
                        for r in con.execute(f'PRAGMA table_info("{table}")')] for table in tables}


def main():
    keys = ('MEMBER1_PASSWORD', 'MEMBER2_PASSWORD')
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ[key] = secrets.token_urlsafe(24)
        with TemporaryDirectory(prefix='family-contract-docs-') as directory:
            app = create_app({'TESTING': True, 'SECRET_KEY': secrets.token_hex(48),
                              'DATA_DIR': directory, 'SESSION_COOKIE_SECURE': False})
            assert app.test_client().get('/api/spaces/current').status_code == 200
            routes = []
            for rule in app.url_map.iter_rules():
                view = app.view_functions[rule.endpoint]
                source = Path(inspect.getsourcefile(view)).resolve().relative_to(ROOT).as_posix()
                for method in sorted(rule.methods - {'HEAD', 'OPTIONS'}):
                    routes.append(dict(method=method, path=rule.rule, source=source, endpoint=rule.endpoint))
            routes.sort(key=lambda r: (r['path'], r['method']))
            report = {'generatedAt': datetime.now(timezone.utc).isoformat(),
                      'scope': 'local source; isolated new databases; no production verification',
                      'routes': routes, 'wsgiRoutes': [{'method':'GET', 'path':'/space/<slug>', 'source':'household_spaces.py'}],
                      'householdTables': schema(Path(directory) / 'household.sqlite3'),
                      'platformTables': schema(Path(directory) / 'platform.sqlite3')}
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    content = ['# 当前路由与存储索引', '',
               '由 `tests/inspect_contract.py` 在临时新数据库中实例化当前 Flask 应用生成。只含结构，不含运行数据或凭据。', '',
               '本表描述**本地源码**，其与正式版本的差异见 [交接说明](HANDOFF.md)。表用于定位代码；字段、权限、错误和状态机参见 [README 文档导航](../README.md#文档导航)。', '',
               f'Flask HTTP 方法与路径组合：**{len(routes)}**；另有 `GET /space/<slug>`。HEAD/OPTIONS 不重复列出。动态 `<action>` 路由算一个模板，允许的具体动作见 [待办发布契约](TASK-PUBLISH.md)。', '',
               '| 方法 | 路径 | 实现 |', '|---|---|---|']
    content.extend(f"| {r['method']} | `{r['path']}` | [{r['source']}](../{r['source']}) · `{r['endpoint']}` |" for r in routes)
    for title, key in [('每户业务数据表', 'householdTables'), ('平台注册目录', 'platformTables')]:
        content.extend(['', f'## {title}', '', f"共 **{len(report[key])}** 张表：", '', ', '.join(f'`{name}`' for name in report[key])])
    content.extend(['', '每户表位于各自 `household.sqlite3`；平台注册目录位于 `platform.sqlite3`。字段结构见 [机器可读清单](contract-inventory.json)。', '',
                    '重建本索引：在隔离开发环境运行 `python tests/inspect_contract.py`。该脚本只写本文及相邻 JSON，使用虚构初始密码和临时数据库，不读取 `.env`，不连接第三方服务。', ''])
    (ROOT / 'docs' / 'PLATFORM-ROUTES.md').write_text('\n'.join(content), encoding='utf-8')
    (ROOT / 'docs' / 'contract-inventory.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'routes':len(routes), 'householdTables':len(report['householdTables']), 'platformTables':len(report['platformTables'])}))


if __name__ == '__main__':
    main()
