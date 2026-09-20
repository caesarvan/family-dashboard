"""Member-owned portable data, without credentials or another member's ledger."""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from io import BytesIO, StringIO
from itertools import chain
import csv
import json
from finance_hub import export_import_receipts
import calendar_privacy as calendar_acl
from threading import BoundedSemaphore
from zipfile import ZipFile, ZIP_DEFLATED

from flask import g, jsonify, send_file
from finance_accounts import export_owned_accounts
from finance_analysis import export_owned_analysis
from finance_baseline import shared_baselines
from finance_source_bridge import ImportSession
from shopping_settlement import export_owned_settlements
from household_routines import export_shared_routines
from spending_observations import export_owned_spending_observations
from journey_documents import exported_documents
from journey_places import coordinate_projection
from journey_routes import route_context
from household_media import ITEM_VIEW, MediaError
from inventory_core import export_inventory, InventoryError

EXPORT_SLOT = BoundedSemaphore(1)
MAX_EXPORT_BYTES = 64 * 1024 * 1024
MAX_REFERENCE_FX_ROWS = 10000
ANALYSIS_TABLES = frozenset({'finance_account_profiles', 'finance_account_cashflows',
                           'finance_account_reviews', 'finance_analysis_operations'})


def exported_reference_fx(con):
    """Bounded public reference observations, separate from all personal records."""
    total = con.execute('SELECT count(*) FROM finance_fx_rates').fetchone()[0]
    rows = [dict(row) for row in con.execute(
        'SELECT version,rate_date AS rateDate,currency,units_per_eur AS unitsPerEur,'
        'source_url AS sourceUrl,body_sha256 AS bodySha256,fetched_at AS fetchedAt,'
        'last_checked_at AS lastCheckedAt FROM finance_fx_rates '
        'ORDER BY rate_date DESC,currency,version LIMIT ?', (MAX_REFERENCE_FX_ROWS,))]
    return rows, {'scope': 'public_ecb_reference_cache', 'totalRows': total, 'includedRows': len(rows),
                  'rowLimit': MAX_REFERENCE_FX_ROWS, 'complete': total == len(rows),
                  'selection': 'rate_date_desc_currency_version', 'historicalReportReconstruction': False}
ENTITY_FIELDS = {'title','owner','done','due','priority','tripId','journeyId','quantity','budget','actual','note',
                 'photoIds','start','end','allDay','location','source','imported','destination','saved','paid',
                 'travelTiming','startDate','endDateExclusive','workflowKey','dependsOn','visibility','createdBy'}
INVENTORY_ITEM_FIELDS = {'id','owner','visibility','title','variant','unit','location','revision',
                         'onHandQty','inTransitQty','plannedQty','reorderPoint','belowThreshold','createdAt','updatedAt'}
INVENTORY_ACQUISITION_FIELDS = {'id','itemId','shoppingId','kind','orderedQty','orderState','orderedOn',
    'expectedOn','warrantyUntil','afterSalesState','note','revision','createdAt','updatedAt',
    'onHandQty','receivedQty','returnedQty','remainingExpectedQty','fulfillmentState'}
INVENTORY_MOVEMENT_FIELDS = {'id','acquisitionId','actor','kind','deltaQty','occurredOn','reason','reversesId','createdAt'}
INVENTORY_SOURCE_FIELDS = {'id','acquisitionId','orderId','settlementId','status','revision'}
INVENTORY_OPERATION_FIELDS = {'id','operation','itemId','acquisitionId','createdAt'}
REMINDER_OPERATION_FIELDS = {'taskId': str, 'occurrence': str, 'action': str, 'revision': int,
                             'readAt': (str, type(None)), 'snoozedUntil': (str, type(None)),
                             'committedAt': str}


def exported_calendar_events(con, actor, include_shared=False):
    result = {'personal': [], 'shared': []}
    for row in con.execute("SELECT id,data,revision,updated_at FROM entities WHERE kind='events' ORDER BY id"):
        value = json.loads(row['data'])
        if not calendar_acl.visible(value, actor):
            continue
        target = 'personal' if calendar_acl.scope(value) == 'private' else 'shared'
        if target == 'shared' and not include_shared:
            continue
        result[target].append({**{k: v for k, v in value.items() if k in ENTITY_FIELDS},
                               'id': row['id'], 'revision': row['revision'], 'updatedAt': row['updated_at']})
    return result


def exported_task_reminders(con, owner):
    """Owner history only, including removed-task references; never receipt blobs."""
    result = {'states': [], 'operations': []}
    available = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'task_reminders' in available:
        result['states'] = [dict(row) for row in con.execute(
            'SELECT task_id AS taskId,due,read_at AS readAt,snoozed_until AS snoozedUntil,'
            'revision,created_at AS createdAt,updated_at AS updatedAt '
            'FROM task_reminders WHERE owner=? ORDER BY task_id,due', (owner,))]
    if 'task_reminder_operations' in available:
        for row in con.execute('SELECT result FROM task_reminder_operations WHERE owner=? '
                               'ORDER BY created_at,request_id', (owner,)):
            receipt = json.loads(row['result'])
            result['operations'].append({key: receipt[key] for key, allowed in REMINDER_OPERATION_FIELDS.items()
                if key in receipt and type(receipt[key]) in (allowed if isinstance(allowed, tuple) else (allowed,))})
    return result


def cell(value):
    """CSV is spreadsheet-safe; JSON retains the exact original text."""
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    text = str(value)
    if text.lstrip(' \t\r\n\ufeff').startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


def decimal_amount(value):
    return '' if value is None else format(Decimal(value) / Decimal(100), '.2f')


def exported_places(con, owner, include_shared=False):
    """Only live places, with the same coordinate projection as their API.

    Receipts/tombstones remain in database backups, not in personal downloads.
    Explicit fields prevent later internal/credential columns from leaking.
    """
    result = {'personal': [], 'shared': []}
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='journey_places'").fetchone():
        return result
    rows = con.execute("SELECT * FROM journey_places WHERE deleted_at IS NULL AND (owner=? OR (? AND visibility='shared')) ORDER BY id",
                       (owner, bool(include_shared))).fetchall()
    for row in rows:
        own = row['owner'] == owner
        point, precision, grid = coordinate_projection(row, 'exact' if own else row['coordinate_disclosure'])
        fields = {'id': 'id', 'owner': 'owner', 'name': 'name', 'country': 'country', 'city': 'city',
                  'status': 'status', 'journeyId': 'journey_id', 'startDate': 'start_date', 'endDate': 'end_date',
                  'visibility': 'visibility', 'coordinateDisclosure': 'coordinate_disclosure',
                  'visitedConfirmedAt': 'visited_confirmed_at', 'visitedConfirmedBy': 'visited_confirmed_by',
                  'revision': 'revision', 'createdAt': 'created_at', 'updatedAt': 'updated_at'}
        item = {public: row[stored] for public, stored in fields.items()}
        item.update(coordinates=point, coordinatePrecision=precision, coordinateGridDegrees=grid)
        result['personal' if own else 'shared'].append(item)
    return result


def exported_routes(con, owner, household, secret, include_shared=False):
    """Current API projection only; never export raw stops or historical receipts."""
    result = {'personal': [], 'shared': []}
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='journey_routes'").fetchone():
        return result
    secret = secret.encode('utf-8') if isinstance(secret, str) else secret
    route_fields = {'id', 'title', 'journeyId', 'visibility', 'revision'}
    place_fields = {'id', 'owner', 'name', 'country', 'city', 'status', 'journeyId',
        'startDate', 'endDate', 'visibility', 'coordinateDisclosure', 'visitedConfirmedAt',
        'visitedConfirmedBy', 'revision', 'createdAt', 'updatedAt', 'coordinates',
        'coordinatePrecision', 'coordinateGridDegrees'}
    rows = con.execute("SELECT * FROM journey_routes WHERE deleted_at IS NULL "
        "AND (owner=? OR (? AND visibility='shared')) ORDER BY id", (owner, bool(include_shared)))
    for row in rows:
        detail, _ = route_context(con, row, owner, household, secret)
        item = {key: value for key, value in detail['route'].items() if key in route_fields}
        item['stops'] = []
        for stop in detail['route']['stops']:
            slot = {'index': stop['index'], 'state': stop['state']}
            if stop['state'] == 'available':
                slot['place'] = {key: value for key, value in stop['place'].items() if key in place_fields}
            item['stops'].append(slot)
        item['segments'] = [{'fromIndex': segment['fromIndex'], 'toIndex': segment['toIndex']}
                            for segment in detail['segments']]
        result['personal' if row['owner'] == owner else 'shared'].append(item)
    return result


def exported_household_media(con, engine, owner, include_shared=False):
    """Export only saved photo/video descriptions; never ciphertext, grants or URLs."""
    result = {'personal': [], 'shared': []}
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_items'").fetchone():
        return result
    if engine is None:
        raise RuntimeError('Media library must be registered before exporting photo records')
    fields = {'id','revision','caption','width','height','contentType','visibility','journey','createdAt','mediaType','durationMs','hasAudio'}
    rows = con.execute('SELECT '+ITEM_VIEW+" FROM media_items WHERE state='ready' AND (owner=? OR (? AND visibility='shared')) ORDER BY id",
                       (owner, bool(include_shared))).fetchall()
    for row in rows:
        own = row['owner'] == owner
        if not own and not engine._media_authority(con,row):
            continue
        item = engine._item_dto(con,row,owner)
        allowed = fields | ({'source','displayFilename','sourceCreatedAt','sourceTimeState'} if own else set())
        result['personal' if own else 'shared'].append({k:v for k,v in item.items() if k in allowed})
    return result


def validate_media_snapshot(con, engine, owner, exported):
    """A ZIP built from an earlier snapshot cannot retain revoked photo shares."""
    for item in chain(exported['personal'],exported['shared']):
        row = engine._item(con,item['id'],owner)
        if row['revision'] != item['revision']:
            raise MediaError('conflict')


def exported_inventory(con, owner, include_shared=False):
    """Core ACL projection plus a stable ZIP allowlist, never raw source/receipt rows."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inventory_items'").fetchone():
        return {'personal':[], 'shared':[], 'sources':[], 'operations':[]}
    value = export_inventory(con,owner,include_shared)
    def fields(row, allowed):
        return {key:item for key,item in row.items() if key in allowed}
    result = {'personal':[], 'shared':[]}
    for scope in result:
        for row in value[scope]:
            item = fields(row,INVENTORY_ITEM_FIELDS)
            item['acquisitions'] = [fields(lot,INVENTORY_ACQUISITION_FIELDS) for lot in row['acquisitions']]
            item['movements'] = [fields(event,INVENTORY_MOVEMENT_FIELDS) for event in row['movements']]
            result[scope].append(item)
    result['sources'] = [fields(row,INVENTORY_SOURCE_FIELDS) for row in value['sources']]
    result['operations'] = [fields(row,INVENTORY_OPERATION_FIELDS) for row in value['operations']]
    return result


def register_portability(app, db, Problem, body, require_member, audit, limited):
    def tables(con):
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def owned_rows(con, table):
        # Table names come only from fixed call sites, never from request fields.
        return [dict(r) for r in con.execute(f'SELECT * FROM {table} WHERE owner=? ORDER BY rowid', (g.actor['id'],))]

    def decoded_rows(con, table):
        return [{**json.loads(r['data']), 'id': r['id'], 'revision': r['revision']} for r in owned_rows(con, table)]

    @app.get('/api/portability/summary')
    def export_summary():
        access = ImportSession(app, db, Problem, require_member)
        con, uid = access.con, access.owner
        con.rollback()
        con.execute('BEGIN')
        access.check()
        counts = {name: con.execute(f'SELECT count(*) FROM {table} WHERE owner=?', (uid,)).fetchone()[0]
                  for name, table in [('transactions','hub_transactions'),('investments','hub_investments'),
                                      ('budgets','hub_budgets'),('financeBaselines','finance_baselines'),
                                      ('assistantPlans','assistant_plans')]}
        for name, table in (('taskReminderStates', 'task_reminders'), ('taskReminderOperations', 'task_reminder_operations')):
            counts[name] = con.execute('SELECT count(*) FROM '+table+' WHERE owner=?', (uid,)).fetchone()[0] if table in tables(con) else 0
        shared = {r[0]: r[1] for r in con.execute('SELECT kind,count(*) FROM entities GROUP BY kind')}
        calendars = exported_calendar_events(con, g.actor, include_shared=True)
        counts['calendarEvents'] = len(calendars['personal'])
        shared['events'] = len(calendars['shared'])
        documents = exported_documents(con, uid, include_shared=True) if 'journey_documents' in tables(con) else {'personal': [], 'shared': []}
        counts['journeyDocuments'] = len(documents['personal'])
        shared['journeyDocuments'] = len(documents['shared'])
        places = exported_places(con, uid, include_shared=True)
        counts['journeyPlaces'] = len(places['personal'])
        shared['journeyPlaces'] = len(places['shared'])
        counts['journeyRoutes'] = shared['journeyRoutes'] = 0
        if 'journey_routes' in tables(con):
            counts['journeyRoutes'] = con.execute('SELECT count(*) FROM journey_routes WHERE owner=? AND deleted_at IS NULL', (uid,)).fetchone()[0]
            shared['journeyRoutes'] = con.execute("SELECT count(*) FROM journey_routes WHERE owner!=? AND visibility='shared' AND deleted_at IS NULL", (uid,)).fetchone()[0]
        media = exported_household_media(con,app.extensions.get('household_media'),uid,include_shared=True)
        counts['householdMedia'] = len(media['personal'])
        shared['householdMedia'] = len(media['shared'])
        counts['inventoryItems'] = shared['inventoryItems'] = 0
        if 'inventory_items' in tables(con):
            counts['inventoryItems'] = con.execute('SELECT count(*) FROM inventory_items WHERE owner=? AND deleted_at IS NULL',(uid,)).fetchone()[0]
            shared['inventoryItems'] = con.execute("SELECT count(*) FROM inventory_items WHERE owner!=? AND visibility='shared' AND deleted_at IS NULL",(uid,)).fetchone()[0]
        if 'finance_accounts' in tables(con):
            counts['financeAccounts'] = con.execute('SELECT count(*) FROM finance_accounts WHERE owner=?', (uid,)).fetchone()[0]
        if ANALYSIS_TABLES <= tables(con):
            counts['financeAnalysis'] = {name: con.execute('SELECT count(*) FROM ' + table + ' WHERE owner=?', (uid,)).fetchone()[0]
                for name, table in [('profiles', 'finance_account_profiles'), ('cashflows', 'finance_account_cashflows'),
                                    ('reviews', 'finance_account_reviews'), ('operations', 'finance_analysis_operations')]}
        con.rollback()
        access.fresh()
        return jsonify(personal=counts, shared=shared, format='zip',
                       note='导出的是当前保存的记录，并非已覆盖全部金融账户。家庭相册、采购图片和旅行资料仅含说明与元数据，不包含图片或文件；照片原图仍在来源平台，旅行文件可在资料夹逐份下载。账号连接需要重新授权。')

    @app.post('/api/portability/export')
    def export_data():
        require_member()
        value = body()
        if set(value) - {'includeShared'} or type(value.get('includeShared', False)) is not bool:
            raise Problem('请指定是否附带家庭共同记录')
        limited('data_export', 6, 3600)
        if not EXPORT_SLOT.acquire(blocking=False):
            raise Problem('正在准备另一份数据副本，请稍后重试', 429)
        try:
            access = ImportSession(app, db, Problem, require_member)
            con, uid = access.con, access.owner
            con.rollback()
            con.execute('BEGIN')
            access.check()
            available = tables(con)
            exported = datetime.now(timezone.utc)
            snapshot = {'schemaVersion': 1, 'exportedAt': exported.isoformat(),
                        'household': app.config.get('HOUSEHOLD_INFO') or {'id':'default','name':'我们的家','slug':'home'},
                        'member': dict(con.execute('SELECT id,username,name FROM users WHERE id=?', (uid,)).fetchone()),
                        'coverage': {'includesShared': value.get('includeShared',False), 'photos':'metadata_only',
                                     'journeyDocuments': 'metadata_only',
                                     'householdMedia': 'saved_metadata_only',
                                     'inventory': 'manual_records',
                                     'externalCredentialsIncluded': False, 'completeFinancialCoverage': False}, 'personal': {}}
            personal = snapshot['personal']
            calendars = exported_calendar_events(con, g.actor, value.get('includeShared', False))
            personal['calendarEvents'] = calendars['personal']
            snapshot['coverage']['calendarEvents'] = 'own_private_and_explicitly_included_shared_without_sync_credentials'
            personal['taskReminders'] = exported_task_reminders(con, uid)
            snapshot['coverage']['taskReminders'] = 'owner_state_and_minimal_operation_history_without_task_content'
            documents = exported_documents(con, uid, include_shared=value.get('includeShared', False)) if 'journey_documents' in available else {'personal': [], 'shared': []}
            personal['journeyDocuments'] = documents['personal']
            places = exported_places(con, uid, include_shared=value.get('includeShared', False))
            personal['journeyPlaces'] = places['personal']
            routes = exported_routes(con, uid, current_household := app.config.get('HOUSEHOLD_INFO', {}).get('id', 'default'),
                                     app.config['SECRET_KEY'], include_shared=value.get('includeShared', False))
            personal['journeyRoutes'] = routes['personal']
            snapshot['coverage']['journeyRoutes'] = 'current_visible_ordered_stops_without_receipts'
            media_engine = app.extensions.get('household_media')
            media = exported_household_media(con,media_engine,uid,include_shared=value.get('includeShared',False))
            personal['householdMedia'] = media['personal']
            inventory = exported_inventory(con,uid,include_shared=value.get('includeShared',False))
            personal['inventory'] = {'items':inventory['personal'], 'sources':inventory['sources'],
                                     'operations':inventory['operations']}
            personal['transactions'] = decoded_rows(con, 'hub_transactions')
            for transaction in personal['transactions']:
                transaction.setdefault('provenance', {'status': 'unknown'})
            personal['transactionImportReceipts'] = export_import_receipts(con, uid)
            if {'finance_accounts', 'finance_account_valuations', 'finance_account_operations'} <= available:
                personal['financeAccounts'] = export_owned_accounts(con, uid)
                snapshot['coverage']['financeAccounts'] = 'manual_accounts_and_dated_valuations'
            if ANALYSIS_TABLES <= available:
                personal['financeAnalysis'] = export_owned_analysis(con, uid)
                snapshot['coverage']['financeAnalysis'] = 'owner_profiles_cashflows_reviews_and_minimal_operations'
            if 'finance_fx_rates' in available:
                rates, coverage = exported_reference_fx(con)
                snapshot['referenceData'] = {'financeFxRates': rates}
                snapshot['coverage']['financeFxRates'] = coverage
            personal['investments'] = decoded_rows(con, 'hub_investments')
            personal['investmentOperations'] = []
            if 'hub_investment_operations' in available:
                investment_fields = {'id': str, 'revision': int, 'name': str, 'institution': str,
                    'assetType': str, 'currency': str, 'quantity': (str, type(None)),
                    'costCents': int, 'valueCents': (int, type(None)), 'asOf': str,
                    'note': str, 'valuationSource': str, 'visibility': str}
                for row in con.execute(
                        'SELECT request_id AS requestId,kind,record_id AS recordId,result,completed_at AS completedAt '
                        'FROM hub_investment_operations WHERE owner=? ORDER BY completed_at,request_id', (uid,)):
                    operation, result = dict(row), json.loads(row['result'])
                    fields = {'deleted': bool} if row['kind'] == 'delete' else investment_fields
                    operation['result'] = {key: result[key] for key, allowed in fields.items()
                        if key in result and type(result[key]) in (allowed if isinstance(allowed, tuple) else (allowed,))}
                    personal['investmentOperations'].append(operation)
            if 'hub_investment_sources' in available:
                personal['investmentSources'] = [dict(r) for r in con.execute(
                    'SELECT source_name AS sourceName,revision,updated_at AS updatedAt '
                    'FROM hub_investment_sources WHERE owner=? ORDER BY source_name', (uid,))]
            if 'hub_investment_links' in available:
                # A deleted holding can retain its link as an import tombstone.
                # Keep that business history without joining another owner's data.
                personal['investmentLinks'] = [dict(r) for r in con.execute(
                    'SELECT source_name AS sourceName,holding_key AS holdingKey,investment_id AS investmentId,created_at AS createdAt '
                    'FROM hub_investment_links WHERE owner=? ORDER BY source_name,holding_key', (uid,))]
            if 'hub_investment_import_receipts' in available:
                personal['investmentImportReceipts'] = []
                for row in con.execute(
                        'SELECT id,source_name AS sourceName,source_digest AS sourceDigest,result,confirmed_at AS confirmedAt '
                        'FROM hub_investment_import_receipts WHERE owner=? ORDER BY confirmed_at,id', (uid,)):
                    receipt, result = dict(row), json.loads(row['result'])
                    # Explicit business fields only: a future receipt extension must
                    # not accidentally export preview or authentication context.
                    field_types = {'created':int, 'updated':int, 'unchanged':int, 'replayed':bool,
                                   'receiptId':str, 'confirmedAt':str}
                    receipt['result'] = {key:result[key] for key,kind in field_types.items()
                                         if key in result and type(result[key]) is kind}
                    personal['investmentImportReceipts'].append(receipt)
            personal['budgets'] = [{k:v for k,v in row.items() if k!='owner'} for row in owned_rows(con, 'hub_budgets')]
            personal['imports'] = [{k:v for k,v in row.items() if k!='owner'} for row in owned_rows(con, 'hub_imports')]
            if 'finance_source_receipts' in available:
                receipt_fields = {'id','candidate_digest','source_digest','expected_revision','expected_source_digest','baseline_revision','status','accepted_at'}
                personal['financeSourceReceipts'] = [{k:v for k,v in row.items() if k in receipt_fields}
                                                    for row in owned_rows(con, 'finance_source_receipts')]
            if 'hub_reconciliations' in available:
                personal['reconciliations'] = [dict(r) for r in con.execute(
                    'SELECT id,kind,left_id AS leftId,right_id AS rightId,amount_cents AS amountCents,status,revision,created_at AS createdAt,updated_at AS updatedAt '
                    'FROM hub_reconciliations WHERE owner=? ORDER BY id', (uid,))]
            if {'hub_shopping_settlements', 'hub_shopping_settlement_receipts'}.issubset(available):
                personal['shoppingSettlements'] = export_owned_settlements(con, uid)
            personal['monthlyFinance'] = [dict(data=json.loads(r['data']), revision=r['revision']) for r in owned_rows(con, 'private_finance')]
            personal['financeBaselines'] = [{'data':json.loads(r['private_data']), 'revision':r['revision'], 'updatedAt':r['updated_at']} for r in owned_rows(con, 'finance_baselines')]
            if {'finance_spending_observations', 'finance_spending_receipts'}.issubset(available):
                personal['spendingObservations'] = export_owned_spending_observations(con, uid)
            personal['preferences'] = [json.loads(r['data']) for r in owned_rows(con, 'member_preferences')]
            if 'member_dashboard_layout' in available:
                personal['dashboardLayout'] = [dict(data=json.loads(r['data']),revision=r['revision']) for r in owned_rows(con, 'member_dashboard_layout')]
            personal['assistantPlans'] = [{'id':r['id'],'createdAt':r['created_at'],'appliedAt':r['applied_at'],
                                           'data':json.loads(r['data']),'result':json.loads(r['result']) if r['result'] else None}
                                          for r in owned_rows(con, 'assistant_plans')]
            # Connections export useful member-owned labels, never subjects, app
            # secrets, token ciphertext, OAuth state, PKCE or password hashes.
            personal['connections'] = []
            for account in con.execute('SELECT id,provider,name,email FROM cloud_accounts WHERE owner=? ORDER BY id', (uid,)):
                sources = [dict(r) for r in con.execute('SELECT name,kind,is_primary AS isPrimary FROM cloud_sources WHERE account_id=? ORDER BY id',(account['id'],))]
                personal['connections'].append({'provider':account['provider'],'name':account['name'],'email':account['email'],'sources':sources})
            if value.get('includeShared', False):
                shared = {'people':[dict(r) for r in con.execute('SELECT id,name FROM users ORDER BY id')], 'entities':{},
                          'financeBaselines':shared_baselines(con), 'journeyDocuments': documents['shared']}
                for r in con.execute('SELECT id,kind,data,revision,updated_at FROM entities ORDER BY kind,id'):
                    data = json.loads(r['data'])
                    if r['kind'] == 'events':
                        continue
                    shared['entities'].setdefault(r['kind'], []).append({**{k:v for k,v in data.items() if k in ENTITY_FIELDS},
                        'id':r['id'],'revision':r['revision'],'updatedAt':r['updated_at']})
                if calendars['shared']:
                    shared['entities']['events'] = calendars['shared']
                finance = con.execute("SELECT data,revision FROM settings WHERE id='finance'").fetchone()
                shared['finance'] = {'data':json.loads(finance['data']),'revision':finance['revision']}
                shared['journeys'] = [{'id':r['id'],'tripId':r['trip_id'],'plan':json.loads(r['plan']),'revision':r['revision']}
                                      for r in con.execute('SELECT id,trip_id,plan,revision FROM journey_workflows ORDER BY id')]
                shared['photoMetadata'] = [dict(r) for r in con.execute('SELECT id,size,width,height FROM photos WHERE EXISTS (SELECT 1 FROM photo_refs WHERE photo_id=photos.id) ORDER BY id')]
                if {'household_routines', 'routine_occurrences', 'routine_receipts'}.issubset(available):
                    shared['routines'] = export_shared_routines(con)
                snapshot['shared'] = shared
                shared['journeyPlaces'] = places['shared']
                shared['journeyRoutes'] = routes['shared']
                shared['householdMedia'] = media['shared']
                shared['inventory'] = {'items':inventory['shared']}
            personal['photoMetadata'] = [dict(r) for r in con.execute('SELECT id,size,width,height FROM photos WHERE created_by=? ORDER BY id',(uid,))]
            con.commit()
            output, digests = BytesIO(), {}
            total_size = 0
            with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
                def entry(name, chunks):
                    nonlocal total_size
                    digest, size = sha256(), 0
                    with archive.open(name, 'w') as stream:
                        for chunk in chunks:
                            raw = chunk.encode('utf-8') if isinstance(chunk,str) else chunk
                            size += len(raw)
                            total_size += len(raw)
                            if total_size > MAX_EXPORT_BYTES:
                                raise Problem('当前导出内容超过 64 MB，请联系管理员按家庭备份导出；未生成不完整副本', 413)
                            digest.update(raw)
                            stream.write(raw)
                    digests[name] = {'bytes':size,'sha256':digest.hexdigest()}

                def csv_chunks(columns, rows):
                    yield '\ufeff'
                    buffer = StringIO(newline='')
                    writer = csv.writer(buffer)
                    for row in chain([columns], rows):
                        writer.writerow([cell(x) for x in row])
                        yield buffer.getvalue()
                        buffer.seek(0)
                        buffer.truncate(0)

                entry('data.json', json.JSONEncoder(ensure_ascii=False,allow_nan=False,indent=2).iterencode(snapshot))
                entry('transactions.csv', csv_chunks(['id','date','title','amount','currency','kind','flow','category','source','externalId','visibility','revision'],
                    ([r.get('id'),r.get('date'),r.get('title'),decimal_amount(r.get('amountCents')),r.get('currency'),r.get('kind'),r.get('flow'),r.get('category'),r.get('source'),r.get('externalId'),r.get('visibility'),r.get('revision')] for r in personal['transactions'])))
                entry('investments.csv', csv_chunks(['id','institution','name','assetType','currency','cost','value','asOf','revision'],
                    ([r.get('id'),r.get('institution'),r.get('name'),r.get('assetType'),r.get('currency'),decimal_amount(r.get('costCents')),decimal_amount(r.get('valueCents')),r.get('asOf'),r.get('revision')] for r in personal['investments'])))
                entry('README.txt', ['家庭中枢 · 个人数据副本\n\n',
                    'data.json 保留当前成员的数据、原始文字、整数分金额、日期与覆盖说明。transactions.csv 和 investments.csv 便于表格查看；其中 amount/cost/value 为原币金额，不是分。\n',
                    '交易 CSV 是原始保存记录，不是自动去重后的支出报告；关系与核对结果以 data.json 为准。不同币种和旧日期记录不能直接相加。\n',
                    '持仓导入的来源、稳定关联和业务回执保存在 data.json；已删除持仓可能仍保留防重复导入的关联。预览暂存和授权上下文不包含在导出中。\n',
                    'personal.financeAccounts 包含本人手动账户（含归档）、所有按日估值及最小操作摘要；不含请求编号、载荷散列或历史回执原文。金额为原币整数分，未知为 null，不合并到持仓、来源报告或公共资金。\n',
                    '独立消费观察和接受回执保存在 data.json；其报告日期与覆盖范围不改变资产余额日期，不与账单、订单或基线消费重复相加。\n',
                    'CSV 的公式危险前缀加了单引号，JSON 保留原文。估值未知保持空白，不作为零。\n',
                    '勾选共同记录时含双方已共享的日程、待办、采购、旅行和资金汇总；不含伴侣私人账本。采购图片与旅行资料仅含元数据，不含文件。旅行资料夹可逐份下载文件。\n',
                    '本人旅行资料只在 personal.journeyDocuments 出现一次，含旅行已删除后保留的本人资料；shared.journeyDocuments 仅含仍关联有效旅行的伙伴共享资料，不含内容、文件网址、请求标识或内容散列。\n',
                    'personal.journeyPlaces 含本人未删除地点及精确坐标；shared.journeyPlaces 仅含伙伴明确共享地点，坐标按其隐藏、粗化或精确设置导出。地点创建回执与已删除记录不在本副本内，整库备份另行保留。\n',
                    'personal.journeyRoutes 含本人未删除路线；勾选共同记录才含 shared.journeyRoutes 中伙伴明确共享路线。站点按当前授权及原顺序投影，共享路线的作者也只看到共享坐标。不可用站点仅保留位置，不跨缺口连线；不含隐藏地点编号、历史回执或请求摘要。路线顺序不代表导航或实际到访。\n',
                    'personal.householdMedia 仅含本人已确认保存媒体的说明、尺寸、来源文件名与旅行关联；shared.householdMedia 仅含仍获授权的伙伴共享媒体说明，不包含原始文件名。没有照片文件、视频文件、下载网址、选片清单、令牌、TV许可或后台任务。媒体类型、视频时长和音轨状态属于说明字段；加密展示副本和后台记录仅在服务器整库备份中保留。\n',
                    'personal.inventory 包含本人物品及批次、实物流水；sources 和 operations 只含本人且在本次可见范围内的最小来源关联与操作摘要。shared.inventory 仅含伙伴当前共享物品及其批次、实物流水，不含伙伴的金融来源或操作回执。归档记录、请求标识、载荷散列、原回执内容不在此副本内；整库备份另行保留。数量不代表付款、退款或估值。\n',
                    'personal.taskReminders 仅含本人持久提醒状态与最小操作历史，含任务已删除或改期后保留的引用；不含任务标题快照、他人状态、请求编号、请求摘要、原回执或凭证。状态按导出快照保存，不表示任务当前仍适用或暂缓尚未到期。此私人历史不会因勾选共同记录而变成共享数据，不能用于导入或重放操作。\n',
                    '不含登录密码、令牌、应用密钥；迁移后须重新绑定第三方。此文件不是可直接覆盖 SQLite 的灾难恢复备份，当前没有一键还原此文件的接口。\n',
                    '本文件含个人资料和财务内容，请保存在你控制的设备上。\n'])
                entry('manifest.json', [json.dumps({'schemaVersion':1,'files':dict(digests),'exportedAt':exported.isoformat()},ensure_ascii=False,indent=2)])
            con.execute('BEGIN IMMEDIATE')
            access.check()
            if (exported_routes(con, uid, current_household, app.config['SECRET_KEY'],
                                include_shared=value.get('includeShared', False)) != routes
                    or exported_places(con, uid, include_shared=value.get('includeShared', False)) != places):
                raise Problem('路线、地点或共享范围已变化，请重新导出以获取最新内容',409)
            try:
                validate_media_snapshot(con,media_engine,uid,media)
            except MediaError:
                raise Problem('照片或共享范围已变化，请重新导出以获取最新内容',409) from None
            try:
                if exported_inventory(con,uid,include_shared=value.get('includeShared',False)) != inventory:
                    raise InventoryError('conflict')
            except InventoryError:
                raise Problem('物品或共享范围已变化，请重新导出以获取最新内容',409) from None
            if exported_calendar_events(con, g.actor, value.get('includeShared', False)) != calendars:
                raise Problem('日程或共享范围已变化，请重新导出以获取最新内容', 409)
            audit('personal_data_export', 'with_shared' if value.get('includeShared') else 'personal_only')
            con.commit()
            output.seek(0)
            response = send_file(output, mimetype='application/zip', as_attachment=True,
                                 download_name=f'family-data-{uid}-{exported:%Y%m%dT%H%M%SZ}.zip', etag=False, max_age=0)
            response.headers['Cache-Control'] = 'private, no-store'
            return response
        finally:
            EXPORT_SLOT.release()
