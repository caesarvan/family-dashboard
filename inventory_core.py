"""Inventory domain only. Callers authenticate the current household member.

All access requires a caller-owned transaction; mutations require BEGIN
IMMEDIATE. This module never authenticates an actor string, commits a caller's
transaction, registers Flask routes, or changes shopping/financial records.
"""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import re
import secrets
import sqlite3
import unicodedata

MAX_QTY = 1_000_000
LIMITS = {'inventory_items': 5000, 'inventory_acquisitions': 20000,
          'inventory_movements': 100000, 'inventory_source_links': 20000,
          'inventory_operations': 100000}
MESSAGES = {
    'invalid': '库存字段不正确。', 'transaction_required': '需要已认证的当前家庭事务。',
    'not_found': '库存记录不存在。', 'forbidden': '无权管理此库存记录。',
    'conflict': '库存或依赖已变化，请重新核对。', 'gone': '库存记录已删除。',
    'quantity': '数量超过上限或可用库存不足。', 'capacity': '库存记录已达上限。',
    'request_conflict': '该操作标识已用于不同内容。', 'schema': '库存结构不匹配。',
    'busy': '库存正在更新，请稍后重试。', 'storage': '库存操作未完成。',
}


class InventoryError(ValueError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else 'storage'
        super().__init__(MESSAGES[self.code])


SCHEMA_SQL = '''
CREATE TABLE inventory_items(
 id TEXT PRIMARY KEY CHECK(length(id)=24 AND id NOT GLOB '*[^0-9a-f]*'),
 owner TEXT NOT NULL REFERENCES users(id),
 visibility TEXT NOT NULL CHECK(visibility IN ('private','shared')),
 title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 100),
 variant TEXT NOT NULL CHECK(length(variant)<=200),
 unit TEXT NOT NULL CHECK(length(unit) BETWEEN 1 AND 20),
 location TEXT NOT NULL CHECK(length(location)<=100),
 reorder_point INTEGER CHECK(reorder_point IS NULL OR
   (typeof(reorder_point)='integer' AND reorder_point BETWEEN 0 AND 1000000)),
 revision INTEGER NOT NULL DEFAULT 1 CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 9007199254740991),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT);
CREATE INDEX inventory_items_visible ON inventory_items(owner,visibility,deleted_at,id);
CREATE TABLE inventory_acquisitions(
 id TEXT PRIMARY KEY CHECK(length(id)=24 AND id NOT GLOB '*[^0-9a-f]*'),
 item_id TEXT NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
 created_by TEXT NOT NULL REFERENCES users(id),
 shopping_id TEXT REFERENCES entities(id) ON DELETE SET NULL,
 kind TEXT NOT NULL CHECK(kind IN ('purchase','opening')),
 ordered_qty INTEGER NOT NULL CHECK(typeof(ordered_qty)='integer' AND ordered_qty BETWEEN 1 AND 1000000),
 order_state TEXT NOT NULL CHECK(order_state IN ('planned','ordered','in_transit','closed','cancelled')),
 ordered_on TEXT CHECK(ordered_on IS NULL OR (length(ordered_on)=10 AND ordered_on>='0001-01-01' AND date(ordered_on,'+0 days') IS NOT NULL AND date(ordered_on,'+0 days')=ordered_on)),
 expected_on TEXT CHECK(expected_on IS NULL OR (length(expected_on)=10 AND expected_on>='0001-01-01' AND date(expected_on,'+0 days') IS NOT NULL AND date(expected_on,'+0 days')=expected_on)),
 warranty_until TEXT CHECK(warranty_until IS NULL OR (length(warranty_until)=10 AND warranty_until>='0001-01-01' AND date(warranty_until,'+0 days') IS NOT NULL AND date(warranty_until,'+0 days')=warranty_until)),
 after_sales_state TEXT NOT NULL CHECK(after_sales_state IN ('none','open','closed')),
 note TEXT NOT NULL CHECK(length(note)<=500),
 revision INTEGER NOT NULL DEFAULT 1 CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 9007199254740991),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
 CHECK(kind!='opening' OR (shopping_id IS NULL AND order_state='closed' AND ordered_on IS NULL AND expected_on IS NULL)),
 CHECK(ordered_on IS NULL OR expected_on IS NULL OR ordered_on<=expected_on));
CREATE INDEX inventory_acquisitions_item ON inventory_acquisitions(item_id,order_state,id);
CREATE INDEX inventory_acquisitions_shopping ON inventory_acquisitions(shopping_id);
CREATE TABLE inventory_operations(
 id TEXT PRIMARY KEY CHECK(length(id)=24 AND id NOT GLOB '*[^0-9a-f]*'),
 actor TEXT NOT NULL REFERENCES users(id),
 request_id TEXT NOT NULL CHECK(length(request_id) BETWEEN 32 AND 64 AND request_id NOT GLOB '*[^0-9a-f]*'),
 payload_digest TEXT NOT NULL CHECK(length(payload_digest)=64 AND payload_digest NOT GLOB '*[^0-9a-f]*'),
 operation TEXT NOT NULL CHECK(operation IN ('create_item','update_item','archive_item','create_acquisition','update_acquisition','append_movement','reverse_movement','attach_source','detach_source','create_replenishment','create_followup')),
 item_id TEXT NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
 acquisition_id TEXT REFERENCES inventory_acquisitions(id) ON DELETE RESTRICT,
 result TEXT NOT NULL CHECK(json_valid(result) AND json_type(result)='object'),
 created_at TEXT NOT NULL, UNIQUE(actor,request_id));
CREATE TABLE inventory_movements(
 id TEXT PRIMARY KEY CHECK(length(id)=24 AND id NOT GLOB '*[^0-9a-f]*'),
 item_id TEXT NOT NULL REFERENCES inventory_items(id) ON DELETE RESTRICT,
 acquisition_id TEXT NOT NULL REFERENCES inventory_acquisitions(id) ON DELETE RESTRICT,
 actor TEXT NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL CHECK(kind IN ('receive','consume','dispose','return','adjust','reverse')),
 delta_qty INTEGER NOT NULL CHECK(typeof(delta_qty)='integer' AND delta_qty!=0 AND abs(delta_qty)<=1000000),
 occurred_on TEXT NOT NULL CHECK(length(occurred_on)=10 AND occurred_on>='0001-01-01' AND date(occurred_on,'+0 days') IS NOT NULL AND date(occurred_on,'+0 days')=occurred_on),
 reason TEXT NOT NULL CHECK(length(reason)<=300),
 reverses_id TEXT UNIQUE REFERENCES inventory_movements(id) ON DELETE RESTRICT,
 request_id TEXT NOT NULL CHECK(length(request_id) BETWEEN 32 AND 64 AND request_id NOT GLOB '*[^0-9a-f]*'),
 created_at TEXT NOT NULL, UNIQUE(actor,request_id),
 CHECK((kind='receive' AND delta_qty>0) OR (kind IN ('consume','dispose','return') AND delta_qty<0) OR kind IN ('adjust','reverse')),
 CHECK((kind='reverse')=(reverses_id IS NOT NULL)));
CREATE INDEX inventory_movements_item ON inventory_movements(item_id,id);
CREATE INDEX inventory_movements_acquisition ON inventory_movements(acquisition_id,id);
CREATE TABLE inventory_source_links(
 id TEXT PRIMARY KEY CHECK(length(id)=24 AND id NOT GLOB '*[^0-9a-f]*'),
 owner TEXT NOT NULL REFERENCES users(id),
 acquisition_id TEXT NOT NULL REFERENCES inventory_acquisitions(id) ON DELETE RESTRICT,
 order_id TEXT NOT NULL CHECK(length(order_id) BETWEEN 1 AND 100),
 line_key TEXT NOT NULL CHECK(length(line_key) BETWEEN 1 AND 200),
 source_digest TEXT NOT NULL CHECK(length(source_digest)=64 AND source_digest NOT GLOB '*[^0-9a-f]*'),
 source_revision INTEGER NOT NULL CHECK(typeof(source_revision)='integer' AND source_revision>=1),
 settlement_id TEXT CHECK(settlement_id IS NULL OR length(settlement_id) BETWEEN 1 AND 100),
 status TEXT NOT NULL CHECK(status IN ('active','detached')),
 revision INTEGER NOT NULL DEFAULT 1 CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 9007199254740991),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX inventory_sources_line ON inventory_source_links(owner,order_id,line_key) WHERE status='active';
CREATE UNIQUE INDEX inventory_sources_acquisition ON inventory_source_links(acquisition_id) WHERE status='active';
CREATE INDEX inventory_sources_owner ON inventory_source_links(owner,acquisition_id,status);
CREATE TRIGGER inventory_items_no_delete BEFORE DELETE ON inventory_items BEGIN SELECT RAISE(ABORT,'inventory_history'); END;
CREATE TRIGGER inventory_acquisitions_no_delete BEFORE DELETE ON inventory_acquisitions BEGIN SELECT RAISE(ABORT,'inventory_history'); END;
CREATE TRIGGER inventory_movements_no_update BEFORE UPDATE ON inventory_movements BEGIN SELECT RAISE(ABORT,'inventory_history'); END;
CREATE TRIGGER inventory_movements_no_delete BEFORE DELETE ON inventory_movements BEGIN SELECT RAISE(ABORT,'inventory_history'); END;
CREATE TRIGGER inventory_operations_no_update BEFORE UPDATE ON inventory_operations BEGIN SELECT RAISE(ABORT,'inventory_history'); END;
CREATE TRIGGER inventory_operations_no_delete BEFORE DELETE ON inventory_operations BEGIN SELECT RAISE(ABORT,'inventory_history'); END;
CREATE TRIGGER inventory_sources_no_delete BEFORE DELETE ON inventory_source_links BEGIN SELECT RAISE(ABORT,'inventory_history'); END;
CREATE TRIGGER inventory_item_identity BEFORE UPDATE ON inventory_items
WHEN NEW.id!=OLD.id OR NEW.owner!=OLD.owner OR NEW.created_at!=OLD.created_at OR
 (NEW.unit!=OLD.unit AND EXISTS(SELECT 1 FROM inventory_movements WHERE item_id=OLD.id)) OR
 (OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NOT OLD.deleted_at)
BEGIN SELECT RAISE(ABORT,'inventory_identity'); END;
CREATE TRIGGER inventory_acquisition_identity BEFORE UPDATE ON inventory_acquisitions
WHEN NEW.id!=OLD.id OR NEW.item_id!=OLD.item_id OR NEW.created_by!=OLD.created_by OR NEW.kind!=OLD.kind OR
 NEW.created_at!=OLD.created_at OR (OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NOT OLD.deleted_at)
BEGIN SELECT RAISE(ABORT,'inventory_identity'); END;
CREATE TRIGGER inventory_shopping_insert BEFORE INSERT ON inventory_acquisitions
WHEN NEW.shopping_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM entities WHERE id=NEW.shopping_id AND kind='shopping')
BEGIN SELECT RAISE(ABORT,'inventory_shopping'); END;
CREATE TRIGGER inventory_shopping_update BEFORE UPDATE OF shopping_id ON inventory_acquisitions
WHEN NEW.shopping_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM entities WHERE id=NEW.shopping_id AND kind='shopping')
BEGIN SELECT RAISE(ABORT,'inventory_shopping'); END;
CREATE TRIGGER inventory_shopping_unlink AFTER UPDATE OF shopping_id ON inventory_acquisitions
WHEN OLD.shopping_id IS NOT NULL AND NEW.shopping_id IS NULL AND NEW.revision=OLD.revision
BEGIN
 UPDATE inventory_acquisitions SET revision=revision+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.id;
 UPDATE inventory_items SET revision=revision+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=NEW.item_id;
END;
CREATE TRIGGER inventory_source_owner_insert BEFORE INSERT ON inventory_source_links
WHEN NOT EXISTS(SELECT 1 FROM inventory_acquisitions a JOIN inventory_items i ON i.id=a.item_id
 WHERE a.id=NEW.acquisition_id AND a.created_by=NEW.owner AND a.kind='purchase'
 AND a.deleted_at IS NULL AND i.deleted_at IS NULL AND (i.owner=NEW.owner OR i.visibility='shared'))
BEGIN SELECT RAISE(ABORT,'inventory_source_owner'); END;
CREATE TRIGGER inventory_source_owner_update BEFORE UPDATE ON inventory_source_links
WHEN NEW.id!=OLD.id OR NEW.owner!=OLD.owner OR NEW.acquisition_id!=OLD.acquisition_id OR
 NOT EXISTS(SELECT 1 FROM inventory_acquisitions WHERE id=NEW.acquisition_id AND created_by=NEW.owner AND kind='purchase')
BEGIN SELECT RAISE(ABORT,'inventory_source_owner'); END;
CREATE TRIGGER inventory_movement_guard BEFORE INSERT ON inventory_movements BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM inventory_acquisitions a JOIN inventory_items i ON i.id=a.item_id
  WHERE a.id=NEW.acquisition_id AND a.item_id=NEW.item_id AND a.deleted_at IS NULL AND i.deleted_at IS NULL
  AND (i.owner=NEW.actor OR i.visibility='shared')) THEN RAISE(ABORT,'inventory_acl') END;
 SELECT CASE WHEN NEW.kind='reverse' AND NOT EXISTS(SELECT 1 FROM inventory_movements m
  WHERE m.id=NEW.reverses_id AND m.acquisition_id=NEW.acquisition_id AND m.item_id=NEW.item_id
  AND m.kind!='reverse' AND m.delta_qty=-NEW.delta_qty) THEN RAISE(ABORT,'inventory_reverse') END;
 SELECT CASE WHEN NEW.kind='receive' AND EXISTS(SELECT 1 FROM inventory_acquisitions
  WHERE id=NEW.acquisition_id AND kind!='opening' AND order_state IN ('closed','cancelled')) THEN RAISE(ABORT,'inventory_closed') END;
 SELECT CASE WHEN COALESCE((SELECT sum(delta_qty) FROM inventory_movements WHERE acquisition_id=NEW.acquisition_id),0)+NEW.delta_qty
  NOT BETWEEN 0 AND 1000000 THEN RAISE(ABORT,'inventory_quantity') END;
 SELECT CASE WHEN COALESCE((SELECT sum(CASE WHEN m.kind='receive' THEN m.delta_qty
  WHEN m.kind='reverse' AND r.kind='receive' THEN m.delta_qty ELSE 0 END)
  FROM inventory_movements m LEFT JOIN inventory_movements r ON r.id=m.reverses_id WHERE m.acquisition_id=NEW.acquisition_id),0)
  + CASE WHEN NEW.kind='receive' OR (NEW.kind='reverse' AND (SELECT kind FROM inventory_movements WHERE id=NEW.reverses_id)='receive')
    THEN NEW.delta_qty ELSE 0 END NOT BETWEEN 0 AND (SELECT ordered_qty FROM inventory_acquisitions WHERE id=NEW.acquisition_id)
  THEN RAISE(ABORT,'inventory_overreceive') END;
END;
CREATE TRIGGER inventory_order_quantity BEFORE UPDATE OF ordered_qty ON inventory_acquisitions
WHEN NEW.ordered_qty < COALESCE((SELECT sum(CASE WHEN m.kind='receive' THEN m.delta_qty
 WHEN m.kind='reverse' AND r.kind='receive' THEN m.delta_qty ELSE 0 END)
 FROM inventory_movements m LEFT JOIN inventory_movements r ON r.id=m.reverses_id WHERE m.acquisition_id=NEW.id),0)
BEGIN SELECT RAISE(ABORT,'inventory_order_quantity'); END;
CREATE TRIGGER inventory_item_archive BEFORE UPDATE OF deleted_at ON inventory_items
WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL AND EXISTS(
 SELECT 1 FROM inventory_acquisitions a WHERE a.item_id=NEW.id AND
 (a.order_state NOT IN ('closed','cancelled') OR COALESCE((SELECT sum(delta_qty) FROM inventory_movements WHERE acquisition_id=a.id),0)!=0))
BEGIN SELECT RAISE(ABORT,'inventory_stock_remains'); END;
CREATE TRIGGER inventory_acquisition_archive BEFORE UPDATE OF deleted_at ON inventory_acquisitions
WHEN NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL AND
 (NEW.order_state NOT IN ('closed','cancelled') OR COALESCE((SELECT sum(delta_qty) FROM inventory_movements WHERE acquisition_id=NEW.id),0)!=0)
BEGIN SELECT RAISE(ABORT,'inventory_stock_remains'); END;
'''

for _table, _limit in LIMITS.items():
    SCHEMA_SQL += f'''CREATE TRIGGER {_table}_capacity BEFORE INSERT ON {_table}
WHEN (SELECT count(*) FROM {_table})>={_limit}
BEGIN SELECT RAISE(ABORT,'inventory_capacity'); END;
'''


def _pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _id():
    return secrets.token_hex(12)


def _integer(value, low=0, high=MAX_QTY):
    if type(value) is not int or not low <= value <= high:
        raise InventoryError('invalid')
    return value


def _identifier(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{24}', value):
        raise InventoryError('invalid')
    return value


def _text(value, limit, empty=True):
    if type(value) is not str or any(unicodedata.category(c).startswith('C') for c in value):
        raise InventoryError('invalid')
    value = value.strip()
    if len(value) > limit or not empty and not value:
        raise InventoryError('invalid')
    return value


def _day(value):
    if value is None:
        return None
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise InventoryError('invalid')
    try:
        date.fromisoformat(value)
    except ValueError:
        bad = True
    else:
        bad = False
    if bad:
        raise InventoryError('invalid')
    return value


def _fields(data, allowed, required=()):
    if type(data) is not dict or set(data)-set(allowed) or set(required)-set(data):
        raise InventoryError('invalid')


ITEM_FIELDS = {'title', 'variant', 'unit', 'location', 'visibility', 'reorderPoint'}
ACQUISITION_FIELDS = {'kind', 'shoppingId', 'orderedQty', 'orderState', 'orderedOn', 'expectedOn', 'warrantyUntil', 'afterSalesState', 'note'}


def normalize_item(data, previous=None):
    _fields(data, ITEM_FIELDS, () if previous else {'title', 'unit'})
    value = {'variant': '', 'location': '', 'visibility': 'private', 'reorderPoint': None, **(previous or {}), **data}
    result = {k: _text(value[k], n, k not in {'title', 'unit'}) for k, n in [('title',100),('variant',200),('unit',20),('location',100)]}
    if value['visibility'] not in ('private', 'shared'):
        raise InventoryError('invalid')
    result.update(visibility=value['visibility'], reorderPoint=None if value['reorderPoint'] is None else _integer(value['reorderPoint']))
    return result


def normalize_acquisition(data, previous=None):
    _fields(data, ACQUISITION_FIELDS, () if previous else {'orderedQty'})
    value = {'kind':'purchase', 'shoppingId':None, 'orderState':'planned', 'orderedOn':None,
             'expectedOn':None, 'warrantyUntil':None, 'afterSalesState':'none', 'note':'', **(previous or {}), **data}
    if value['kind'] not in ('purchase','opening') or value['orderState'] not in ('planned','ordered','in_transit','closed','cancelled') or value['afterSalesState'] not in ('none','open','closed'):
        raise InventoryError('invalid')
    result = {k: value[k] for k in ('kind','orderState','afterSalesState')}
    result.update(orderedQty=_integer(value['orderedQty'],1), shoppingId=None if value['shoppingId'] is None else _identifier(value['shoppingId']), note=_text(value['note'],500))
    result.update({k:_day(value[k]) for k in ('orderedOn','expectedOn','warrantyUntil')})
    if result['orderedOn'] and result['expectedOn'] and result['expectedOn'] < result['orderedOn']:
        raise InventoryError('invalid')
    if result['kind']=='opening' and (result['shoppingId'] is not None or result['orderState']!='closed' or result['orderedOn'] is not None or result['expectedOn'] is not None):
        raise InventoryError('invalid')
    return result


def _rows(con, sql, args=()):
    cursor = con.execute(sql, args)
    names = [col[0] for col in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _one(con, sql, args=()):
    rows = _rows(con, sql, args)
    return rows[0] if rows else None


def _require(con, actor):
    if not con.in_transaction or con.execute('PRAGMA foreign_keys').fetchone()[0]!=1:
        raise InventoryError('transaction_required')
    if type(actor) is not str or not con.execute('SELECT 1 FROM users WHERE id=?',(actor,)).fetchone():
        raise InventoryError('transaction_required')


def _item(con, actor, item_id, manage=False):
    _identifier(item_id)
    item = _one(con,'SELECT * FROM inventory_items WHERE id=?',(item_id,))
    if not item or item['owner']!=actor and item['visibility']!='shared':
        raise InventoryError('not_found')
    if item['deleted_at']:
        raise InventoryError('gone')
    if manage and item['owner']!=actor:
        raise InventoryError('forbidden')
    return item


def _acquisition(con, actor, acquisition_id):
    _identifier(acquisition_id)
    row = _one(con,'SELECT * FROM inventory_acquisitions WHERE id=?',(acquisition_id,))
    if not row:
        raise InventoryError('not_found')
    item = _item(con,actor,row['item_id'])
    if row['deleted_at']:
        raise InventoryError('gone')
    return item, row


def _cas(row, expected):
    _integer(expected,1,2**53-1)
    if row['revision']!=expected:
        raise InventoryError('conflict')


def _bump(con, table, row):
    if con.execute(f'UPDATE {table} SET revision=revision+1,updated_at=? WHERE id=? AND revision=?',(_stamp(),row['id'],row['revision'])).rowcount!=1:
        raise InventoryError('conflict')


def _capacity(con, table):
    if con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]>=LIMITS[table]:
        raise InventoryError('capacity')


def _request_id(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{32,64}',value):
        raise InventoryError('invalid')
    return value


@contextmanager
def _savepoint(con):
    name = 'inventory_' + secrets.token_hex(8)
    con.execute('SAVEPOINT '+name)
    try:
        yield
    except BaseException:
        con.execute('ROLLBACK TO '+name)
        con.execute('RELEASE '+name)
        raise
    else:
        con.execute('RELEASE '+name)


def _run(con, actor, request_id, operation, payload, action):
    _require(con,actor)
    _request_id(request_id)
    failure = None
    try:
        with _savepoint(con):
            # Acquire/confirm the writer reservation even if a caller used a
            # deferred transaction. No row is modified by this statement.
            con.execute('UPDATE inventory_items SET revision=revision WHERE 0')
            packed = _pack({'operation':operation,'payload':payload}).encode()
            if len(packed)>16384:
                raise InventoryError('invalid')
            fingerprint = sha256(packed).hexdigest()
            old = _one(con,'SELECT * FROM inventory_operations WHERE actor=? AND request_id=?',(actor,request_id))
            if old:
                if old['payload_digest']!=fingerprint:
                    raise InventoryError('request_conflict')
                _item(con,actor,old['item_id'])
                return {**json.loads(old['result']),'replayed':True}
            _capacity(con,'inventory_operations')
            result = action()
            _receipt_result(result)
            con.execute('INSERT INTO inventory_operations VALUES(?,?,?,?,?,?,?,?,?)',
                (_id(),actor,request_id,fingerprint,operation,result['itemId'],result.get('acquisitionId'),_pack(result),_stamp()))
            return {**result,'replayed':False}
    except InventoryError as error:
        failure = error.code
    except sqlite3.IntegrityError:
        failure = 'conflict'
    except sqlite3.OperationalError as error:
        failure = 'busy' if 'locked' in str(error).lower() or 'busy' in str(error).lower() else 'storage'
    except (TypeError,ValueError,OverflowError):
        failure = 'invalid'
    except Exception:
        failure = 'storage'
    raise InventoryError(failure)


def _receipt_result(value):
    _fields(value, {'itemId','itemRevision','acquisitionId','acquisitionRevision','movementId',
                    'quantityDelta','deleted','entityId','sourceLinkId','sourceRevision'}, {'itemId','itemRevision'})
    for key, entry in value.items():
        if key.endswith('Id'):
            _identifier(entry)
        elif key.endswith('Revision'):
            _integer(entry,1,2**53-1)
        elif key=='quantityDelta':
            _integer(entry,-MAX_QTY)
        elif type(entry) is not bool:
            raise InventoryError('invalid')


def apply_with_receipt(con, actor, request_id, operation, payload, action, *,
                       item_id, item_revision, acquisition_id=None, acquisition_revision=None):
    """B/C seam for trusted domain code, never a request-supplied callback.

    Core validates current item/acquisition ACL and CAS before the callback.
    The callback must validate its own source and other dependencies/CAS.
    It must not commit/rollback or perform I/O.
    Only a small ID/revision result allowlist is persisted or replayed.
    """
    if operation not in ('attach_source','detach_source','create_replenishment','create_followup') or not callable(action):
        raise InventoryError('invalid')
    def checked_action():
        item = _item(con,actor,item_id)
        _cas(item,item_revision)
        if acquisition_id is not None:
            _,lot = _acquisition(con,actor,acquisition_id)
            if lot['item_id']!=item_id:
                raise InventoryError('not_found')
            _cas(lot,acquisition_revision)
        elif acquisition_revision is not None or operation in ('attach_source','detach_source'):
            raise InventoryError('invalid')
        if operation in ('attach_source','detach_source') and lot['created_by']!=actor:
            raise InventoryError('forbidden')
        result = action()
        _receipt_result(result)
        if result['itemId']!=item_id or result.get('acquisitionId')!=acquisition_id:
            raise InventoryError('invalid')
        current = _item(con,actor,item_id)
        _cas(current,result['itemRevision'])
        if acquisition_id is not None:
            _,fresh = _acquisition(con,actor,acquisition_id)
            _cas(fresh,result.get('acquisitionRevision'))
        return result
    values = {'itemId':item_id,'itemRevision':item_revision,'acquisitionId':acquisition_id,
              'acquisitionRevision':acquisition_revision,'payload':payload}
    return _run(con,actor,request_id,operation,values,checked_action)


def initialize_inventory(con):
    """Explicit schema initialization only; refuse partial/drifted installations."""
    if con.in_transaction or con.execute('PRAGMA foreign_keys').fetchone()[0]!=1:
        raise InventoryError('transaction_required')
    for table,required in [('users',{'id'}),('entities',{'id','kind','revision'})]:
        columns = con.execute(f'PRAGMA table_info({table})').fetchall()
        if not required <= {row[1] for row in columns} or not any(row[1]=='id' and row[5] for row in columns):
            raise InventoryError('schema')
    reference = sqlite3.connect(':memory:')
    try:
        reference.executescript(SCHEMA_SQL)
        query = "SELECT type,name,sql FROM sqlite_master WHERE name GLOB 'inventory_*' ORDER BY name"
        expected = reference.execute(query).fetchall()
    finally:
        reference.close()
    current = [tuple(row) for row in con.execute(query)]
    if current:
        if current!=expected:
            raise InventoryError('schema')
        return
    failed = False
    try:
        con.executescript('BEGIN IMMEDIATE;\n'+SCHEMA_SQL+'\nCOMMIT;')
    except sqlite3.Error:
        con.rollback()
        failed = True
    if failed:
        raise InventoryError('schema')


def _summary(con, acquisition):
    row = _one(con,'''SELECT COALESCE(sum(m.delta_qty),0) AS onHandQty,
     COALESCE(sum(CASE WHEN m.kind='receive' OR (m.kind='reverse' AND r.kind='receive') THEN m.delta_qty ELSE 0 END),0) AS receivedQty,
     COALESCE(sum(CASE WHEN m.kind='return' OR (m.kind='reverse' AND r.kind='return') THEN -m.delta_qty ELSE 0 END),0) AS returnedQty
     FROM inventory_movements m LEFT JOIN inventory_movements r ON r.id=m.reverses_id WHERE m.acquisition_id=?''',(acquisition['id'],))
    row['remainingExpectedQty'] = max(0,acquisition['ordered_qty']-row['receivedQty']) if acquisition['order_state'] in ('planned','ordered','in_transit') else 0
    row['fulfillmentState'] = 'unreceived' if row['receivedQty']==0 else 'received' if row['receivedQty']==acquisition['ordered_qty'] else 'partial'
    return row


def quantity_summary(con, actor, item_id):
    _require(con,actor)
    _item(con,actor,item_id)
    rows = _rows(con,'SELECT * FROM inventory_acquisitions WHERE item_id=? AND deleted_at IS NULL',(item_id,))
    summaries = [(row,_summary(con,row)) for row in rows]
    return {'onHandQty':sum(s['onHandQty'] for _,s in summaries),
            'inTransitQty':sum(s['remainingExpectedQty'] for r,s in summaries if r['order_state'] in ('ordered','in_transit')),
            'plannedQty':sum(s['remainingExpectedQty'] for r,s in summaries if r['order_state']=='planned')}


def project_item(con, actor, item_id):
    _require(con,actor)
    row = _item(con,actor,item_id)
    value = {key:row[key] for key in ('id','owner','visibility','title','variant','unit','location','revision')}
    value.update(quantity_summary(con,actor,item_id),reorderPoint=row['reorder_point'],canRead=True,canMutate=True,canManage=row['owner']==actor,
                 createdAt=row['created_at'],updatedAt=row['updated_at'])
    value['belowThreshold'] = row['reorder_point'] is not None and value['onHandQty']+value['inTransitQty']<row['reorder_point']
    return value


def project_acquisition(con, actor, acquisition_id):
    _require(con,actor)
    item,row = _acquisition(con,actor,acquisition_id)
    return {'id':row['id'],'itemId':item['id'],'shoppingId':row['shopping_id'],'kind':row['kind'],
            'orderedQty':row['ordered_qty'],'orderState':row['order_state'],'orderedOn':row['ordered_on'],
            'expectedOn':row['expected_on'],'warrantyUntil':row['warranty_until'],
            'afterSalesState':row['after_sales_state'],'note':row['note'],'revision':row['revision'],
            'canMutate':True,'canManageSources':row['created_by']==actor,
            'createdAt':row['created_at'],'updatedAt':row['updated_at'],**_summary(con,row)}


def create_item(con, actor, data, request_id):
    def action():
        value = normalize_item(data)
        _capacity(con,'inventory_items')
        rid,now = _id(),_stamp()
        con.execute('INSERT INTO inventory_items(id,owner,visibility,title,variant,unit,location,reorder_point,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (rid,actor,value['visibility'],value['title'],value['variant'],value['unit'],value['location'],value['reorderPoint'],now,now))
        return {'itemId':rid,'itemRevision':1}
    return _run(con,actor,request_id,'create_item',data,action)


def update_item(con, actor, item_id, revision, patch, request_id):
    def action():
        row = _item(con,actor,item_id,manage=True)
        _cas(row,revision)
        old = {key:row[key] for key in ('title','variant','unit','location','visibility')}
        value = normalize_item(patch,{**old,'reorderPoint':row['reorder_point']})
        if value['unit']!=row['unit'] and con.execute('SELECT 1 FROM inventory_movements WHERE item_id=? LIMIT 1',(item_id,)).fetchone():
            raise InventoryError('conflict')
        con.execute('UPDATE inventory_items SET title=?,variant=?,unit=?,location=?,visibility=?,reorder_point=? WHERE id=?',
            (value['title'],value['variant'],value['unit'],value['location'],value['visibility'],value['reorderPoint'],item_id))
        _bump(con,'inventory_items',row)
        return {'itemId':item_id,'itemRevision':revision+1}
    return _run(con,actor,request_id,'update_item',{'itemId':item_id,'revision':revision,'patch':patch},action)


def archive_item(con, actor, item_id, revision, request_id):
    def action():
        row = _item(con,actor,item_id,manage=True)
        _cas(row,revision)
        lots = _rows(con,'SELECT * FROM inventory_acquisitions WHERE item_id=?',(item_id,))
        if any(_summary(con,lot)['onHandQty'] or lot['order_state'] not in ('closed','cancelled') for lot in lots):
            raise InventoryError('conflict')
        con.execute('UPDATE inventory_items SET deleted_at=? WHERE id=?',(_stamp(),item_id))
        _bump(con,'inventory_items',row)
        return {'itemId':item_id,'itemRevision':revision+1,'deleted':True}
    return _run(con,actor,request_id,'archive_item',{'itemId':item_id,'revision':revision},action)


def _shopping(con, value):
    if value and not con.execute("SELECT 1 FROM entities WHERE id=? AND kind='shopping'",(value,)).fetchone():
        raise InventoryError('not_found')


def create_acquisition(con, actor, item_id, item_revision, data, request_id):
    def action():
        item = _item(con,actor,item_id)
        _cas(item,item_revision)
        value = normalize_acquisition(data)
        _shopping(con,value['shoppingId'])
        _capacity(con,'inventory_acquisitions')
        rid,now = _id(),_stamp()
        con.execute('INSERT INTO inventory_acquisitions(id,item_id,created_by,shopping_id,kind,ordered_qty,order_state,ordered_on,expected_on,warranty_until,after_sales_state,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (rid,item_id,actor,value['shoppingId'],value['kind'],value['orderedQty'],value['orderState'],value['orderedOn'],value['expectedOn'],value['warrantyUntil'],value['afterSalesState'],value['note'],now,now))
        _bump(con,'inventory_items',item)
        return {'itemId':item_id,'itemRevision':item_revision+1,'acquisitionId':rid,'acquisitionRevision':1}
    return _run(con,actor,request_id,'create_acquisition',{'itemId':item_id,'itemRevision':item_revision,'data':data},action)


def update_acquisition(con, actor, acquisition_id, item_revision, revision, patch, request_id):
    def action():
        item,row = _acquisition(con,actor,acquisition_id)
        _cas(item,item_revision); _cas(row,revision)
        previous = project_acquisition(con,actor,acquisition_id)
        value = normalize_acquisition(patch,{key:previous[key] for key in ACQUISITION_FIELDS})
        if value['kind']!=row['kind']:
            raise InventoryError('invalid')
        if actor not in (item['owner'],row['created_by']) and set(patch)-{'orderState','expectedOn','afterSalesState','note'}:
            raise InventoryError('forbidden')
        _shopping(con,value['shoppingId'])
        if value['orderedQty']<_summary(con,row)['receivedQty']:
            raise InventoryError('quantity')
        # Set the revision in this UPDATE so manual unlink is not mistaken for
        # the FK's automatic unlink trigger. Item CAS remains separate.
        changed = con.execute('UPDATE inventory_acquisitions SET shopping_id=?,ordered_qty=?,order_state=?,ordered_on=?,expected_on=?,warranty_until=?,after_sales_state=?,note=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?',
            (value['shoppingId'],value['orderedQty'],value['orderState'],value['orderedOn'],value['expectedOn'],value['warrantyUntil'],value['afterSalesState'],value['note'],_stamp(),acquisition_id,revision))
        if changed.rowcount!=1:
            raise InventoryError('conflict')
        _bump(con,'inventory_items',item)
        return {'itemId':item['id'],'itemRevision':item_revision+1,'acquisitionId':acquisition_id,'acquisitionRevision':revision+1}
    return _run(con,actor,request_id,'update_acquisition',{'acquisitionId':acquisition_id,'itemRevision':item_revision,'revision':revision,'patch':patch},action)


def _movement(con, actor, acquisition_id, item_revision, revision, data, request_id, reverse_id=None):
    item,lot = _acquisition(con,actor,acquisition_id)
    _cas(item,item_revision); _cas(lot,revision)
    if reverse_id is None:
        _fields(data,{'kind','quantity','occurredOn','reason'},{'kind','quantity','occurredOn'})
        kind = data['kind']
        if kind not in ('receive','consume','dispose','return','adjust'):
            raise InventoryError('invalid')
        qty = _integer(data['quantity'],-MAX_QTY if kind=='adjust' else 1)
        if qty==0:
            raise InventoryError('invalid')
        delta = -qty if kind in ('consume','dispose','return') else qty
    else:
        _fields(data,{'occurredOn','reason'},{'occurredOn','reason'})
        original = _one(con,'SELECT * FROM inventory_movements WHERE id=? AND acquisition_id=?',(_identifier(reverse_id),acquisition_id))
        if not original or original['kind']=='reverse' or con.execute('SELECT 1 FROM inventory_movements WHERE reverses_id=?',(reverse_id,)).fetchone():
            raise InventoryError('conflict')
        kind,delta = 'reverse',-original['delta_qty']
    occurred = _day(data['occurredOn'])
    if occurred is None:
        raise InventoryError('invalid')
    reason = _text(data.get('reason',''),300,kind=='receive')
    summary = _summary(con,lot)
    if not 0<=summary['onHandQty']+delta<=MAX_QTY:
        raise InventoryError('quantity')
    receive_delta = delta if kind=='receive' or reverse_id and original['kind']=='receive' else 0
    if not 0<=summary['receivedQty']+receive_delta<=lot['ordered_qty']:
        raise InventoryError('quantity')
    if kind=='receive' and lot['kind']!='opening' and lot['order_state'] in ('closed','cancelled'):
        raise InventoryError('conflict')
    _capacity(con,'inventory_movements')
    rid = _id()
    con.execute('INSERT INTO inventory_movements VALUES(?,?,?,?,?,?,?,?,?,?,?)',
        (rid,item['id'],acquisition_id,actor,kind,delta,occurred,reason,reverse_id,request_id,_stamp()))
    _bump(con,'inventory_acquisitions',lot); _bump(con,'inventory_items',item)
    return {'itemId':item['id'],'itemRevision':item_revision+1,'acquisitionId':acquisition_id,'acquisitionRevision':revision+1,'movementId':rid,'quantityDelta':delta}


def append_movement(con, actor, acquisition_id, item_revision, revision, data, request_id):
    return _run(con,actor,request_id,'append_movement',{'acquisitionId':acquisition_id,'itemRevision':item_revision,'revision':revision,'data':data},
        lambda:_movement(con,actor,acquisition_id,item_revision,revision,data,request_id))


def reverse_movement(con, actor, acquisition_id, movement_id, item_revision, revision, data, request_id):
    return _run(con,actor,request_id,'reverse_movement',{'acquisitionId':acquisition_id,'movementId':movement_id,'itemRevision':item_revision,'revision':revision,'data':data},
        lambda:_movement(con,actor,acquisition_id,item_revision,revision,data,request_id,movement_id))


def get_operation(con, actor, request_id):
    _require(con,actor); _request_id(request_id)
    row = _one(con,'SELECT * FROM inventory_operations WHERE actor=? AND request_id=?',(actor,request_id))
    if not row:
        raise InventoryError('not_found')
    _item(con,actor,row['item_id'])
    return {**json.loads(row['result']),'replayed':True}


def export_inventory(con, actor, include_shared=False):
    _require(con,actor)
    if type(include_shared) is not bool:
        raise InventoryError('invalid')
    result = {'personal':[],'shared':[],'sources':[],'operations':[]}
    items = _rows(con,"SELECT id,owner FROM inventory_items WHERE deleted_at IS NULL AND (owner=? OR (?=1 AND visibility='shared')) ORDER BY id",(actor,int(include_shared)))
    visible = {r['id'] for r in items}
    for row in items:
        value = project_item(con,actor,row['id'])
        value = {k:v for k,v in value.items() if not k.startswith('can')}
        value['acquisitions'] = []
        for lot in _rows(con,'SELECT id FROM inventory_acquisitions WHERE item_id=? AND deleted_at IS NULL ORDER BY id',(row['id'],)):
            projected = project_acquisition(con,actor,lot['id'])
            value['acquisitions'].append({k:v for k,v in projected.items() if not k.startswith('can')})
        value['movements'] = _rows(con,'SELECT id,acquisition_id AS acquisitionId,actor,kind,delta_qty AS deltaQty,occurred_on AS occurredOn,reason,reverses_id AS reversesId,created_at AS createdAt FROM inventory_movements WHERE item_id=? ORDER BY id',(row['id'],))
        result['personal' if row['owner']==actor else 'shared'].append(value)
    for row in _rows(con,'SELECT s.id,s.acquisition_id AS acquisitionId,s.order_id AS orderId,s.settlement_id AS settlementId,s.status,s.revision,a.item_id FROM inventory_source_links s JOIN inventory_acquisitions a ON a.id=s.acquisition_id WHERE s.owner=? ORDER BY s.id',(actor,)):
        if row.pop('item_id') in visible:
            result['sources'].append(row)
    for row in _rows(con,'SELECT id,operation,item_id AS itemId,acquisition_id AS acquisitionId,created_at AS createdAt FROM inventory_operations WHERE actor=? ORDER BY id',(actor,)):
        if row['itemId'] in visible:
            result['operations'].append(row)
    return result
