"""Explicit private imported-order links; no financial or physical-stock writes.

Stored order item order is immutable under the import/transaction APIs. Array
positions identify lines only inside that persisted order snapshot. A changed
revision/digest requires review; it never silently remaps a stored line.
"""
from hashlib import sha256
import json
import secrets
import time

from flask import g, jsonify
from itsdangerous import BadSignature, URLSafeTimedSerializer

import inventory_core as core


PREVIEW_SECONDS = 900
MAX_LINES = 5000


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _text(value, maximum, required=False):
    if type(value) is not str or len(value)>maximum or required and not value:
        raise core.InventoryError('invalid')
    return value


def _order(con, actor, order_id):
    core._identifier(order_id)
    row = core._one(con,'SELECT id,revision,data FROM hub_transactions WHERE owner=? AND id=?',(actor,order_id))
    if row is None:
        raise core.InventoryError('not_found')
    data = json.loads(row['data'])
    if type(data) is not dict or data.get('kind')!='orders':
        raise core.InventoryError('not_found')
    order = dict(id=row['id'],revision=row['revision'],title=_text(data.get('title'),200,True),
                 date=_text(data.get('date'),10,True),status=_text(data.get('status',''),80))
    if 'orderItems' in data:
        entries = data['orderItems']
        if type(entries) is not list or not 1<=len(entries)<=MAX_LINES:
            raise core.InventoryError('invalid')
        lines = []
        for index, entry in enumerate(entries):
            if type(entry) is not dict:
                raise core.InventoryError('invalid')
            lines.append(dict(lineKey='item:'+str(index),title=_text(entry.get('title'),500,True),
                              variant=_text(entry.get('variant',''),500),
                              quantityText=_text(entry.get('quantityText',''),100)))
    else:
        lines = [dict(lineKey='order',title=order['title'],variant='',quantityText='')]
    # Financial metadata stays in the private ledger. Only its digest is stored
    # on the private link; no title, quantity, URL or amount is copied to stock.
    return order,lines,_digest({'id':row['id'],'data':data})


def _managed(con, actor, acquisition_id):
    item,lot = core._acquisition(con,actor,acquisition_id)
    if lot['created_by']!=actor:
        raise core.InventoryError('forbidden')
    if lot['kind']!='purchase':
        raise core.InventoryError('invalid')
    return item,lot


def _line(lines, key):
    if type(key) is not str:
        raise core.InventoryError('invalid')
    line = next((entry for entry in lines if entry['lineKey']==key),None)
    if line is None:
        raise core.InventoryError('invalid')
    return line


def _link_projection(con, actor, row):
    reasons,order,line = [],None,None
    try:
        order,lines,digest = _order(con,actor,row['order_id'])
        if row['source_revision']!=order['revision'] or row['source_digest']!=digest:
            reasons.append('source_changed')
        else:
            line = next((entry for entry in lines if entry['lineKey']==row['line_key']),None)
            if line is None:
                reasons.append('source_changed')
    except core.InventoryError as error:
        if error.code not in ('not_found','invalid'):
            raise
        reasons.append('source_missing' if error.code=='not_found' else 'source_changed')
    state = 'detached' if row['status']=='detached' else 'needs_review' if reasons else 'current'
    return dict(id=row['id'],revision=row['revision'],status=row['status'],state=state,
                reviewReasons=reasons,orderId=row['order_id'],lineKey=row['line_key'],
                orderRevision=row['source_revision'],order=order,line=line)


def order_context(con, actor, order_id, query):
    order,lines,digest = _order(con,actor,order_id)
    links = {row['line_key']:row for row in core._rows(con,
        "SELECT * FROM inventory_source_links WHERE owner=? AND order_id=? AND status='active'",(actor,order_id))}
    page = []
    for line in lines[query['offset']:query['offset']+query['limit']]:
        state,linked = 'none',None
        row = links.get(line['lineKey'])
        if row is not None:
            state = 'unavailable'
            try:
                item,lot = _managed(con,actor,row['acquisition_id'])
                if row['source_revision']==order['revision'] and row['source_digest']==digest:
                    linked = dict(sourceLinkId=row['id'],sourceRevision=row['revision'],
                                  itemId=item['id'],acquisitionId=lot['id'])
                    state = 'linked'
            except core.InventoryError as error:
                if error.code not in ('not_found','gone','forbidden'):
                    raise
        page.append({**line,'linkState':state,'link':linked})
    end = query['offset']+len(page)
    return dict(order=order,lines=page,total=len(lines),limit=query['limit'],offset=query['offset'],
                nextOffset=end if end<len(lines) else None)


def source_context(con, actor, acquisition_id):
    item,lot = _managed(con,actor,acquisition_id)
    row = core._one(con,"""SELECT * FROM inventory_source_links WHERE owner=? AND acquisition_id=?
        ORDER BY (status='active') DESC,updated_at DESC,id DESC LIMIT 1""",(actor,acquisition_id))
    return dict(itemId=item['id'],acquisitionId=lot['id'],
                link=_link_projection(con,actor,row) if row else None)


def _plan(value):
    common = {'requestId','operation','acquisitionId','itemRevision','revision'}
    operation = value.get('operation')
    fields = common | ({'orderId','lineKey','orderRevision'} if operation=='attach' else
                       {'sourceLinkId','sourceRevision'} if operation=='detach' else set())
    if operation not in ('attach','detach') or set(value)!=fields:
        raise core.InventoryError('invalid')
    core._request_id(value['requestId'])
    core._identifier(value['acquisitionId'])
    for name in ('itemRevision','revision','orderRevision' if operation=='attach' else 'sourceRevision'):
        core._integer(value[name],1,2**53-1)
    core._identifier(value['orderId'] if operation=='attach' else value['sourceLinkId'])
    if operation=='attach':
        _text(value['lineKey'],200,True)
    return dict(value)


def _assess(con, actor, plan):
    item,lot = _managed(con,actor,plan['acquisitionId'])
    core._cas(item,plan['itemRevision'])
    core._cas(lot,plan['revision'])
    if plan['operation']=='attach':
        order,lines,digest = _order(con,actor,plan['orderId'])
        if order['revision']!=plan['orderRevision']:
            raise core.InventoryError('conflict')
        line = _line(lines,plan['lineKey'])
        if con.execute("""SELECT 1 FROM inventory_source_links WHERE status='active' AND
            (acquisition_id=? OR (owner=? AND order_id=? AND line_key=?)) LIMIT 1""",
            (lot['id'],actor,plan['orderId'],plan['lineKey'])).fetchone():
            raise core.InventoryError('conflict')
        return item,lot,order,line,None,digest
    link = core._one(con,'SELECT * FROM inventory_source_links WHERE id=? AND owner=? AND acquisition_id=?',
                     (plan['sourceLinkId'],actor,lot['id']))
    if link is None:
        raise core.InventoryError('not_found')
    core._cas(link,plan['sourceRevision'])
    if link['status']!='active':
        raise core.InventoryError('conflict')
    projection = _link_projection(con,actor,link)
    return item,lot,projection['order'],projection['line'],projection,None


def _identity(api, con, actor):
    current = api.app.extensions['member_sessions'].current(con)
    captured = getattr(g,'member_session',None) or {}
    fields = ('id','owner','credential_hash','auth_version')
    if current['owner']!=actor or any(current[name]!=captured.get(name) for name in fields):
        # Keep only a public code; callers never serialize these credentials.
        from inventory_api import InventoryAPIError
        raise InventoryAPIError('unauthorized')
    return _digest({'household':api.app.config.get('HOUSEHOLD_INFO',{}).get('id','default'),
                    **{name:current[name] for name in fields}})


def register_inventory_sources(api, safe_endpoint):
    """Register against the existing per-household adapter and transaction owner."""
    from inventory_api import InventoryAPIError, PREFIX, _body, _confirmation, _id, _no_query, _query

    app = api.app
    signer = URLSafeTimedSerializer(app.config['SECRET_KEY'],salt='inventory-source-preview-v1')

    @app.get(PREFIX+'/orders/<order_id>')
    @safe_endpoint
    def inventory_order_source(order_id):
        _id(order_id)
        query = _query()
        with api.transaction() as (con,actor):
            _identity(api,con,actor)
            result = order_context(con,actor,order_id,query)
        return jsonify(result)

    @app.get(PREFIX+'/acquisitions/<uid>/source')
    @safe_endpoint
    def inventory_acquisition_source(uid):
        _id(uid);_no_query()
        with api.transaction() as (con,actor):
            _identity(api,con,actor)
            result = source_context(con,actor,uid)
        return jsonify(result)

    @app.post(PREFIX+'/sources/preview')
    @safe_endpoint
    def inventory_source_preview():
        value = _body({'requestId','operation','acquisitionId','itemRevision','revision',
                       'orderId','lineKey','orderRevision','sourceLinkId','sourceRevision'},
                      {'requestId','operation','acquisitionId','itemRevision','revision'})
        # POST preview checks CSRF/Origin as well, but writes no domain data.
        with api.transaction(True) as (con,actor):
            context = _identity(api,con,actor)
            plan = _plan(value)
            item,_,order,line,link,digest = _assess(con,actor,plan)
            token = signer.dumps(dict(version=1,owner=actor,context=context,plan=plan,sourceDigest=digest))
            result = dict(requestId=plan['requestId'],operation=plan['operation'],
                          item=core.project_item(con,actor,item['id']),
                          acquisition=api.acquisition(con,actor,plan['acquisitionId']),
                          order=order,line=line,link=link,previewToken=token,expiresInSeconds=PREVIEW_SECONDS)
        return jsonify(result)

    @app.post(PREFIX+'/sources/confirm')
    @safe_endpoint
    def inventory_source_confirm():
        value = _body({'requestId','previewToken','confirmSource'},{'requestId','previewToken','confirmSource'})
        _confirmation(value,'confirmSource')
        token = value['previewToken']
        if type(token) is not str or not 20<=len(token)<=12000 or not token.isascii():
            raise InventoryAPIError('invalid')
        try:
            # Authenticate the signature now. Age is checked only for a new
            # operation, so an expired original token can recover its receipt.
            signed,issued = signer.loads(token,return_timestamp=True)
        except BadSignature:
            raise InventoryAPIError('invalid') from None
        with api.transaction(True) as (con,actor):
            context = _identity(api,con,actor)
            if (type(signed) is not dict or set(signed)!={'version','owner','context','plan','sourceDigest'}
                    or type(signed['version']) is not int or signed['version']!=1
                    or signed['owner']!=actor or type(signed['context']) is not str
                    or not secrets.compare_digest(signed['context'],context)
                    or type(signed['plan']) is not dict):
                raise InventoryAPIError('forbidden')
            plan = _plan(signed['plan'])
            if value['requestId']!=plan['requestId']:
                raise InventoryAPIError('request_conflict')
            item,lot = _managed(con,actor,plan['acquisitionId'])
            def action():
                age = time.time()-issued.timestamp()
                if not 0<=age<=PREVIEW_SECONDS:
                    raise core.InventoryError('invalid')
                current,batch,_,_,_,digest = _assess(con,actor,plan)
                if digest!=signed['sourceDigest']:
                    raise core.InventoryError('conflict')
                now = core._stamp()
                if plan['operation']=='attach':
                    core._capacity(con,'inventory_source_links')
                    source_id,source_revision = secrets.token_hex(12),1
                    con.execute('''INSERT INTO inventory_source_links
                        (id,owner,acquisition_id,order_id,line_key,source_digest,source_revision,
                         settlement_id,status,revision,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,NULL,'active',1,?,?)''',
                        (source_id,actor,batch['id'],plan['orderId'],plan['lineKey'],digest,plan['orderRevision'],now,now))
                else:
                    source_id,source_revision = plan['sourceLinkId'],plan['sourceRevision']+1
                    if con.execute("""UPDATE inventory_source_links SET status='detached',revision=revision+1,updated_at=?
                        WHERE id=? AND owner=? AND acquisition_id=? AND revision=? AND status='active'""",
                        (now,source_id,actor,batch['id'],plan['sourceRevision'])).rowcount!=1:
                        raise core.InventoryError('conflict')
                core._bump(con,'inventory_items',current)
                core._bump(con,'inventory_acquisitions',batch)
                return dict(itemId=current['id'],itemRevision=current['revision']+1,
                            acquisitionId=batch['id'],acquisitionRevision=batch['revision']+1,
                            sourceLinkId=source_id,sourceRevision=source_revision)
            operation = core.apply_with_receipt(con,actor,plan['requestId'],plan['operation']+'_source',
                dict(plan=plan,sourceDigest=signed['sourceDigest']),action,item_id=item['id'],
                item_revision=plan['itemRevision'],acquisition_id=lot['id'],acquisition_revision=plan['revision'])
            api.audit(con,actor,plan['operation']+'_source',operation)
            result = api.result(con,actor,operation)
        return jsonify(result)
