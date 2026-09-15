"""Private, versioned home-card layouts; register separately from appearance preferences."""
import json

from flask import g, jsonify, request


CARD_ORDER = ('calendar', 'finance', 'tasks', 'shopping', 'trips')


def _stored(value):
    """Keep future stored keys, while adding newly introduced cards visibly at the end."""
    order = list(dict.fromkeys(x for x in value.get('order', []) if isinstance(x, str)))
    order.extend(x for x in CARD_ORDER if x not in order)
    hidden = list(dict.fromkeys(x for x in value.get('hidden', []) if isinstance(x, str) and x in order))
    if all(x in hidden for x in CARD_ORDER):
        hidden = [x for x in hidden if x != 'calendar']
    return {'order': order, 'hidden': hidden}


def register_dashboard_layout(app, db, Problem, body, require_member, audit):
    with app.app_context():
        db().execute('CREATE TABLE IF NOT EXISTS member_dashboard_layout '
                     '(owner TEXT PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL, '
                     'revision INTEGER NOT NULL DEFAULT 1)')
        db().commit()

    @app.route('/api/dashboard-layout', methods=['GET', 'PUT'])
    def dashboard_layout():
        require_member()
        owner = g.actor['id']
        con = db()
        if request.method == 'PUT':
            value = body()
            if set(value) != {'revision', 'order', 'hidden'}:
                raise Problem('请提交布局版本、卡片顺序与隐藏卡片')
            if type(value['revision']) is not int or value['revision'] < 0:
                raise Problem('请提供有效的布局版本')
            for field in ('order', 'hidden'):
                if (not isinstance(value[field], list) or len(value[field]) > 50
                        or any(not isinstance(x, str) or x not in CARD_ORDER for x in value[field])):
                    raise Problem('请选择支持的首页卡片')
            incoming = _stored(value)
            # Do not silently undo a user's attempt to hide the final visible card.
            if all(x in value['hidden'] for x in CARD_ORDER):
                raise Problem('首页至少保留一张可见卡片')
            # Serialize read/compare/write, including first-save races at revision zero.
            con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT data,revision FROM member_dashboard_layout WHERE owner=?', (owner,)).fetchone()
        previous = _stored(json.loads(row['data'])) if row else _stored({})
        revision = row['revision'] if row else 0
        if request.method == 'GET':
            return jsonify({**previous, 'revision': revision})
        if revision != value['revision']:
            con.rollback()
            raise Problem('首页布局已在其他设备修改。请先查看最新布局，再决定保留哪一版。', 409)
        # Older clients cannot introduce unknown keys or erase future server-stored keys.
        future = [x for x in previous['order'] if x not in CARD_ORDER]
        incoming['order'].extend(future)
        incoming['hidden'].extend(x for x in previous['hidden'] if x in future)
        if incoming == previous:
            con.commit()
            return jsonify({**previous, 'revision': revision})
        revision += 1
        con.execute('INSERT INTO member_dashboard_layout(owner,data,revision) VALUES(?,?,?) '
                    'ON CONFLICT(owner) DO UPDATE SET data=excluded.data,revision=excluded.revision',
                    (owner, json.dumps(incoming), revision))
        audit('dashboard_layout_update')
        con.commit()
        return jsonify({**incoming, 'revision': revision})
