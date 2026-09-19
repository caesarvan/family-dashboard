"""Explicit member-only HTTP adapter for the approved inventory core.

No cloud calls, financial writes or application auto-registration.
After-sales tasks are explicitly created locally in the inventory transaction.
The supplied db() must resolve the current household's request-local connection.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import json
import math
import re
import secrets
import sqlite3
import unicodedata

from flask import g, jsonify, request, session

import inventory_core as core


PREFIX = '/api/inventory'
CONFIRM = {'receive':'confirmReceived', 'consume':'confirmConsumed', 'dispose':'confirmDisposed',
           'return':'confirmReturned', 'adjust':'confirmCorrection'}
STATUSES = {'invalid':400, 'not_found':404, 'forbidden':403, 'conflict':409, 'gone':410,
            'quantity':409, 'capacity':409, 'request_conflict':409, 'schema':503,
            'transaction_required':503, 'busy':503, 'storage':503}
EXTRA_ERRORS = {'unauthorized':(401,'登录或家庭已变化，请重新登录。'),
                'csrf':(403,'会话或请求来源已变化，请刷新后重试。'),
                'confirmation_required':(400,'请明确确认本次实物操作。')}


class InventoryAPIError(Exception):
    def __init__(self, code):
        self.code = code if code in STATUSES or code in EXTRA_ERRORS else 'storage'
        if self.code in EXTRA_ERRORS:
            self.status, self.message = EXTRA_ERRORS[self.code]
        else:
            self.status, self.message = STATUSES[self.code], core.MESSAGES[self.code]
        super().__init__(self.message)


def _fields(value, allowed, required=()):
    if type(value) is not dict or set(value)-set(allowed) or set(required)-set(value):
        raise InventoryAPIError('invalid')


def _id(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{24}',value):
        raise InventoryAPIError('invalid')
    return value


def _request_id(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{32,64}',value):
        raise InventoryAPIError('invalid')
    return value


def _body(allowed, required):
    def pairs(values):
        value = {}
        for k,v in values:
            if k in value:
                raise ValueError()
            value[k] = v
        return value
    def reject(_value):
        raise ValueError()
    def decimal(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError()
        return result
    if request.args or not request.is_json or request.content_length is not None and request.content_length>16384:
        raise InventoryAPIError('invalid')
    raw = request.stream.read(16385)
    if len(raw)>16384:
        raise InventoryAPIError('invalid')
    value = None
    try:
        value = json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=reject,parse_float=decimal)
    except (ValueError,UnicodeError,RecursionError):
        pass
    _fields(value,allowed,required)
    _request_id(value.get('requestId'))
    for name in ('revision','itemRevision'):
        if name in value and (type(value[name]) is not int or not 1<=value[name]<=2**53-1):
            raise InventoryAPIError('invalid')
    for name in ('data','patch'):
        if name in value and (type(value[name]) is not dict or not value[name]):
            raise InventoryAPIError('invalid')
    return value


def _confirmation(value, name):
    if value.get(name) is not True:
        raise InventoryAPIError('confirmation_required')


def _query(extra=(), *, default_limit=50):
    if set(request.args)-set(extra)-{'limit','offset'} or any(len(request.args.getlist(k))!=1 for k in request.args):
        raise InventoryAPIError('invalid')
    value = dict(request.args)
    for name, default, low, high in [('limit',default_limit,1,100),('offset',0,0,100000)]:
        raw = value.get(name,str(default))
        if not re.fullmatch('[0-9]{1,6}',raw) or not low<=int(raw)<=high:
            raise InventoryAPIError('invalid')
        value[name] = int(raw)
    return value


def _no_query():
    if request.args:
        raise InventoryAPIError('invalid')


def _rows(con, sql, args=()):
    cursor = con.execute(sql,args)
    names = [v[0] for v in cursor.description]
    return [dict(zip(names,row)) for row in cursor.fetchall()]


def _page(items, total, query):
    end = query['offset']+len(items)
    return dict(items=items,total=total,limit=query['limit'],offset=query['offset'],
                nextOffset=end if end<total else None)


class InventoryAPI:
    def __init__(self, app, db, Problem, validate=None):
        self.app, self.db, self.Problem, self.validate = app, db, Problem, validate

    @contextmanager
    def transaction(self, write=False):
        con = self.db()
        if con.in_transaction:
            raise InventoryAPIError('transaction_required')
        failure = None
        try:
            con.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            actor = getattr(g,'actor',None)
            if not actor:
                raise InventoryAPIError('unauthorized')
            if actor.get('role')!='member' or request.headers.get('X-Display-Mode')=='tv':
                raise InventoryAPIError('forbidden')
            sessions = self.app.extensions.get('member_sessions')
            if sessions is None:
                raise InventoryAPIError('storage')
            current = sessions.current(con)
            household = self.app.config.get('HOUSEHOLD_INFO',{}).get('id','default')
            if (current['owner'],current['auth_version'],household)!=(actor['id'],actor.get('auth_version'),actor.get('householdId')):
                raise InventoryAPIError('unauthorized')
            if write:
                origin = request.headers.get('Origin')
                token = request.headers.get('X-CSRF-Token','')
                expected = session.get('csrf','')
                if (origin and origin.rstrip('/')!=request.host_url.rstrip('/') or not token
                        or type(expected) is not str or not secrets.compare_digest(token,expected)):
                    raise InventoryAPIError('csrf')
            yield con,current['owner']
            con.commit()
        except InventoryAPIError as error:
            failure = error.code
        except core.InventoryError as error:
            failure = error.code
        except self.Problem:
            failure = 'unauthorized'
        except sqlite3.OperationalError as error:
            failure = 'busy' if 'locked' in str(error).lower() or 'busy' in str(error).lower() else 'storage'
        except Exception:
            failure = 'storage'
        finally:
            if con.in_transaction:
                con.rollback()
        if failure:
            # contextlib can restore the original __context__ while unwinding;
            # the outer HTTP boundary constructs a fresh public error after that.
            raise InventoryAPIError(failure)

    def acquisition(self, con, actor, uid):
        value = core.project_acquisition(con,actor,uid)
        item = core.project_item(con,actor,value['itemId'])
        full = item['canManage'] or value['canManageSources']
        value.update(itemRevision=item['revision'],canEditAllFields=full,
            editableFields=sorted(core.ACQUISITION_FIELDS-{'kind'} if full else {'orderState','expectedOn','afterSalesState','note'}))
        return value

    def result(self, con, actor, operation):
        value = {'operation':operation}
        if operation.get('deleted'):
            return value
        value['item'] = core.project_item(con,actor,operation['itemId'])
        if operation.get('acquisitionId'):
            value['acquisition'] = self.acquisition(con,actor,operation['acquisitionId'])
        return value

    def audit(self, con, actor, kind, operation):
        if operation['replayed']:
            return
        con.execute('INSERT INTO audit(actor,action,target,stamp) VALUES(?,?,?,?)',
            (actor,'inventory.'+kind,operation.get('movementId') or operation.get('acquisitionId') or operation['itemId'],
             datetime.now(timezone.utc).isoformat(timespec='microseconds')))
        if con.execute("UPDATE settings SET revision=revision+1 WHERE id='meta'").rowcount!=1:
            raise InventoryAPIError('storage')

    def followup_id(self, con, item_id, acquisition_id):
        # The immutable receipt is the link, including after task deletion. Do
        # not read or expose another member's request ID, actor or payload hash.
        rows = con.execute("""SELECT result FROM inventory_operations
            WHERE operation='create_followup' AND item_id=? AND acquisition_id=? LIMIT 2""",
            (item_id,acquisition_id)).fetchall()
        if not rows:
            return None
        if len(rows)!=1:
            raise core.InventoryError('storage')
        result = json.loads(rows[0]['result'])
        uid = result.get('entityId') if type(result) is dict else None
        if type(uid) is not str or not re.fullmatch('[0-9a-f]{24}',uid):
            raise core.InventoryError('storage')
        return uid

    def create_followup(self, con, actor, uid, value):
        # Resolve only current ACL/identity here. Mutable state, task validation
        # and dependencies belong in action(), after the original-key replay.
        item, lot = core._acquisition(con,actor,uid)
        def action():
            if self.followup_id(con,item['id'],uid) is not None or lot['after_sales_state']!='open':
                raise core.InventoryError('conflict')
            if not callable(self.validate):
                raise core.InventoryError('storage')
            data = value['data']
            if any(type(v) is not str for v in data.values()):
                raise core.InventoryError('invalid')
            try:
                task = self.validate('tasks',data,lambda:con)
            except self.Problem:
                raise core.InventoryError('invalid') from None
            if con.execute("SELECT count(*) FROM entities WHERE kind='tasks'").fetchone()[0]>=2500:
                raise core.InventoryError('capacity')
            task_id = secrets.token_hex(12)
            con.execute("INSERT INTO entities(id,kind,data,updated_at) VALUES(?,?,?,?)",
                (task_id,'tasks',json.dumps(task),datetime.now(timezone.utc).isoformat(timespec='microseconds')))
            core._bump(con,'inventory_items',item)
            core._bump(con,'inventory_acquisitions',lot)
            return dict(itemId=item['id'],itemRevision=item['revision']+1,
                acquisitionId=uid,acquisitionRevision=lot['revision']+1,entityId=task_id)
        return core.apply_with_receipt(con,actor,value['requestId'],'create_followup',value['data'],action,
            item_id=item['id'],item_revision=value['itemRevision'],
            acquisition_id=uid,acquisition_revision=value['revision'])

    def followup(self, con, actor, uid):
        lot = self.acquisition(con,actor,uid)
        task_id = self.followup_id(con,lot['itemId'],uid)
        result = dict(itemId=lot['itemId'],acquisitionId=uid,state='none',task=None)
        if task_id is None:
            return result
        row = con.execute("SELECT id,revision,data FROM entities WHERE id=? AND kind='tasks'",(task_id,)).fetchone()
        if row is None:
            return {**result,'state':'deleted'}
        data = json.loads(row['data'])
        task = {key:data[key] for key in ('title','owner','due','done','note')}
        return {**result,'state':'linked','task':dict(id=row['id'],revision=row['revision'],**task)}


def register_inventory(app, db, Problem, *, initialize=True, validate=None):
    """Register explicitly for EACH household. db() is caller-owned/request-local.

    initialize=False is for a separately migrated schema, never a silent
    in-request migration. This module owns each request transaction and audit.
    validate is the caller's canonical task validator; without it, new followup
    writes fail closed while existing inventory routes remain available.
    """
    if type(initialize) is not bool:
        raise ValueError('Inventory initialization option must be a boolean')
    if initialize:
        with app.app_context():
            core.initialize_inventory(db())
    api = InventoryAPI(app,db,Problem,validate)
    app.extensions['inventory'] = api

    @app.errorhandler(InventoryAPIError)
    def inventory_error(error):
        return jsonify(error=error.message,code=error.code),error.status

    @app.before_request
    def inventory_member_only():
        if request.path==PREFIX or request.path.startswith(PREFIX+'/'):
            actor = getattr(g,'actor',None)
            if not actor:
                raise InventoryAPIError('unauthorized')
            if actor.get('role')!='member' or request.headers.get('X-Display-Mode')=='tv':
                raise InventoryAPIError('forbidden')

    def safe_endpoint(function):
        @wraps(function)
        def wrapped(*args,**kwargs):
            failure = None
            try:
                return function(*args,**kwargs)
            except InventoryAPIError as error:
                failure = error.code
            # This is outside the contextmanager unwind AND the except clause.
            # Neither raw SQL exceptions nor their causes reach the error handler.
            raise InventoryAPIError(failure)
        return wrapped

    def write(kind, callback, created=False):
        with api.transaction(True) as (con,actor):
            operation = callback(con,actor)
            api.audit(con,actor,kind,operation)
            result = api.result(con,actor,operation)
        return jsonify(result),201 if created and not operation['replayed'] else 200

    @app.get(PREFIX+'/shopping/<shopping_id>/acquisitions')
    @safe_endpoint
    def inventory_shopping_acquisitions(shopping_id):
        _id(shopping_id)
        query = _query(default_limit=12)
        with api.transaction() as (con,actor):
            shopping = con.execute("SELECT id,revision,data FROM entities WHERE id=? AND kind='shopping'",
                                   (shopping_id,)).fetchone()
            if shopping is None:
                raise InventoryAPIError('not_found')
            data = json.loads(shopping['data'])
            title, quantity = data.get('title',''), data.get('quantity','')
            if type(title) is not str or type(quantity) is not str:
                raise InventoryAPIError('storage')
            # Apply the current item's ACL before count and pagination. A shared
            # shopping record does not disclose another member's private stock.
            where = """a.shopping_id=? AND a.deleted_at IS NULL AND i.deleted_at IS NULL
                       AND (i.owner=? OR i.visibility='shared')"""
            joined = ' FROM inventory_acquisitions a JOIN inventory_items i ON i.id=a.item_id WHERE '+where
            args = (shopping_id,actor)
            total = con.execute('SELECT count(*)'+joined,args).fetchone()[0]
            rows = con.execute('SELECT a.id,a.item_id'+joined+' ORDER BY a.id LIMIT ? OFFSET ?',
                               args+(query['limit'],query['offset'])).fetchall()
            items = [{'item':core.project_item(con,actor,row['item_id']),
                      'acquisition':api.acquisition(con,actor,row['id'])} for row in rows]
            result = _page(items,total,query)
            result['shopping'] = {'id':shopping['id'],'revision':shopping['revision'],
                                  'title':title,'quantity':quantity}
        return jsonify(result)

    @app.route(PREFIX+'/items',methods=['GET','POST'])
    @safe_endpoint
    def inventory_items():
        if request.method=='POST':
            value = _body({'requestId','data'},{'requestId','data'})
            return write('create_item',lambda c,a:core.create_item(c,a,value['data'],value['requestId']),True)
        query = _query({'scope','q'})
        scope, text = query.get('scope','all'),query.get('q','').strip()
        if scope not in ('all','mine','shared') or len(text)>100 or any(unicodedata.category(c).startswith('C') for c in text):
            raise InventoryAPIError('invalid')
        with api.transaction() as (con,actor):
            where = "deleted_at IS NULL AND (owner=? OR visibility='shared')"
            args = [actor]
            if scope=='mine':
                where+=' AND owner=?';args.append(actor)
            elif scope=='shared':
                where+=" AND visibility='shared'"
            if text:
                literal = '%'+text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
                where+=" AND (title LIKE ? ESCAPE '\\' OR variant LIKE ? ESCAPE '\\' OR location LIKE ? ESCAPE '\\')"
                args.extend([literal]*3)
            total = con.execute('SELECT count(*) FROM inventory_items WHERE '+where,args).fetchone()[0]
            ids = con.execute('SELECT id FROM inventory_items WHERE '+where+' ORDER BY id LIMIT ? OFFSET ?',args+[query['limit'],query['offset']]).fetchall()
            result = _page([core.project_item(con,actor,r[0]) for r in ids],total,query)
        return jsonify(result)

    @app.route(PREFIX+'/items/<uid>',methods=['GET','PATCH','DELETE'])
    @safe_endpoint
    def inventory_item(uid):
        _id(uid)
        if request.method=='GET':
            _no_query()
            with api.transaction() as (con,actor):
                result = {'item':core.project_item(con,actor,uid)}
            return jsonify(result)
        if request.method=='DELETE':
            value = _body({'requestId','revision','confirmArchive'},{'requestId','revision','confirmArchive'})
            _confirmation(value,'confirmArchive')
            return write('archive_item',lambda c,a:core.archive_item(c,a,uid,value['revision'],value['requestId']))
        value = _body({'requestId','revision','patch'},{'requestId','revision','patch'})
        return write('update_item',lambda c,a:core.update_item(c,a,uid,value['revision'],value['patch'],value['requestId']))

    @app.route(PREFIX+'/items/<uid>/acquisitions',methods=['GET','POST'])
    @safe_endpoint
    def inventory_acquisitions(uid):
        _id(uid)
        if request.method=='POST':
            value = _body({'requestId','itemRevision','data'},{'requestId','itemRevision','data'})
            return write('create_acquisition',lambda c,a:core.create_acquisition(c,a,uid,value['itemRevision'],value['data'],value['requestId']),True)
        query = _query()
        with api.transaction() as (con,actor):
            core.project_item(con,actor,uid)
            total = con.execute('SELECT count(*) FROM inventory_acquisitions WHERE item_id=? AND deleted_at IS NULL',(uid,)).fetchone()[0]
            ids = con.execute('SELECT id FROM inventory_acquisitions WHERE item_id=? AND deleted_at IS NULL ORDER BY id LIMIT ? OFFSET ?',
                (uid,query['limit'],query['offset'])).fetchall()
            result = _page([api.acquisition(con,actor,r[0]) for r in ids],total,query)
        return jsonify(result)

    @app.route(PREFIX+'/acquisitions/<uid>',methods=['GET','PATCH'])
    @safe_endpoint
    def inventory_acquisition(uid):
        _id(uid)
        if request.method=='PATCH':
            value = _body({'requestId','itemRevision','revision','patch'},{'requestId','itemRevision','revision','patch'})
            if 'kind' in value['patch']:
                raise InventoryAPIError('invalid')
            return write('update_acquisition',lambda c,a:core.update_acquisition(c,a,uid,value['itemRevision'],value['revision'],value['patch'],value['requestId']))
        _no_query()
        with api.transaction() as (con,actor):
            acquisition = api.acquisition(con,actor,uid)
            result = {'acquisition':acquisition,'item':core.project_item(con,actor,acquisition['itemId'])}
        return jsonify(result)

    @app.route(PREFIX+'/acquisitions/<uid>/followup',methods=['GET','POST'])
    @safe_endpoint
    def inventory_followup(uid):
        _id(uid)
        if request.method=='POST':
            required = {'requestId','itemRevision','revision','data'}
            value = _body(required,required)
            _fields(value['data'],{'title','owner','due','note'},{'title'})
            return write('create_followup',lambda c,a:api.create_followup(c,a,uid,value),True)
        _no_query()
        with api.transaction() as (con,actor):
            result = api.followup(con,actor,uid)
        return jsonify(result)

    @app.route(PREFIX+'/acquisitions/<uid>/movements',methods=['GET','POST'])
    @safe_endpoint
    def inventory_movements(uid):
        _id(uid)
        if request.method=='POST':
            required = {'requestId','itemRevision','revision','data'}
            value = _body(required|set(CONFIRM.values()),required)
            kind = value['data'].get('kind')
            if type(kind) is not str or kind not in CONFIRM:
                raise InventoryAPIError('invalid')
            if set(value)-required-{CONFIRM[kind]}:
                raise InventoryAPIError('invalid')
            _confirmation(value,CONFIRM[kind])
            return write(kind,lambda c,a:core.append_movement(c,a,uid,value['itemRevision'],value['revision'],value['data'],value['requestId']))
        query = _query()
        with api.transaction() as (con,actor):
            core.project_acquisition(con,actor,uid)
            total = con.execute('SELECT count(*) FROM inventory_movements WHERE acquisition_id=?',(uid,)).fetchone()[0]
            rows = _rows(con,"""SELECT m.id,m.acquisition_id AS acquisitionId,m.actor,m.kind,m.delta_qty AS deltaQty,
                m.occurred_on AS occurredOn,m.reason,m.reverses_id AS reversesId,m.created_at AS createdAt,
                m.kind!='reverse' AND NOT EXISTS(SELECT 1 FROM inventory_movements r WHERE r.reverses_id=m.id) AS canReverse
                FROM inventory_movements m WHERE m.acquisition_id=? ORDER BY m.created_at DESC,m.id DESC LIMIT ? OFFSET ?""",
                (uid,query['limit'],query['offset']))
            for row in rows:
                row['canReverse'] = bool(row['canReverse'])
            result = _page(rows,total,query)
        return jsonify(result)

    @app.post(PREFIX+'/acquisitions/<uid>/movements/<movement_id>/reverse')
    @safe_endpoint
    def inventory_reverse(uid,movement_id):
        _id(uid);_id(movement_id)
        required = {'requestId','itemRevision','revision','data','confirmReversal'}
        value = _body(required,required)
        _confirmation(value,'confirmReversal')
        return write('reverse',lambda c,a:core.reverse_movement(c,a,uid,movement_id,value['itemRevision'],value['revision'],value['data'],value['requestId']))

    @app.get(PREFIX+'/operations/<request_id>')
    @safe_endpoint
    def inventory_operation(request_id):
        _request_id(request_id);_no_query()
        with api.transaction() as (con,actor):
            result = api.result(con,actor,core.get_operation(con,actor,request_id))
        return jsonify(result)

    from inventory_sources import register_inventory_sources
    register_inventory_sources(api, safe_endpoint)
    return api
