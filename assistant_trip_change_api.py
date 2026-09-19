"""Read-only trip-change suggestions handed to the existing reschedule engine.

No new business storage, preview signer, execution path, or model transport.
Selection tickets preserve one suggestion, but never preserve authorization.
"""
from __future__ import annotations

import hashlib
from http.client import HTTPException
import json
import re
from urllib.error import HTTPError, URLError

from flask import jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import home_assistant
from assistant_trip_intent import (
    MAX_CANDIDATES, TripIntentError, decode_model_intent, model_trip_intent,
    plan_existing_trip, project_trip_candidates,
)
from finance_source_bridge import ImportSession


SELECTION_TTL = 600
SELECTION_SALT = 'household-assistant-trip-selection-v1'
MAX_TOKEN_LENGTH = 16000
MAX_REQUEST_BYTES = 24000


class TripChangeError(Exception):
    def __init__(self, message, code, status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _intent_error(error):
    # Only fixed domain messages cross this boundary; never include a provider
    # response, stored JSON, candidate text, or arbitrary exception text.
    message, status = {
        'access_denied': ('旅行权限暂时无法核对，请重新登录。', 403),
        'invalid_candidate': ('当前旅行来源无法核对，请重新打开旅行。', 409),
        'candidate_limit': ('旅行候选过多，请从旅行列表打开目标旅行后调整日期。', 400),
        'model_candidate_limit': ('AI 候选过多，请在需求中写明旅行名称以缩小范围。', 400),
        'invalid_model_output': ('AI 建议格式无法核对，请修改需求后重试；尚未改期。', 502),
        'stale_selection': ('所选旅行不在当前候选中，请重新整理需求。', 409),
        'selection_mismatch': ('所选旅行与原需求不一致，请重新选择。', 400),
    }.get(error.code, ('旅行需求格式无效，请核对文字、日期和选择。', 400))
    return TripChangeError(message, error.code, status)


def _catalogue(con, current):
    """Only this authenticated household's shared workflow trips are candidates.

    The same shared-trip policy is used by /journeys; created_by is provenance,
    not an owner-only ACL. No request-supplied detail object reaches projection.
    """
    rows = con.execute('''SELECT w.id,w.trip_id,w.plan,w.revision,
        l.entity_id,l.kind AS link_kind,e.kind,e.data,e.revision AS trip_revision
        FROM journey_workflows w
        LEFT JOIN journey_links l ON l.journey_id=w.id AND l.item_key='trip'
        LEFT JOIN entities e ON e.id=l.entity_id
        ORDER BY w.id LIMIT ?''', (MAX_CANDIDATES + 1,)).fetchall()
    if len(rows) > MAX_CANDIDATES:
        raise TripIntentError('bounded catalogue', 'candidate_limit')
    details, versions = [], {}
    for row in rows:
        if (row['entity_id'] != row['trip_id'] or row['kind'] != 'trips'
                or row['link_kind'] != 'trips' or type(row['trip_revision']) is not int
                or not 1 <= row['trip_revision'] <= 9_007_199_254_740_991):
            raise TripIntentError('incomplete workflow trip', 'invalid_candidate')
        try:
            trip, plan = json.loads(row['data']), json.loads(row['plan'])
            if type(trip) is not dict or type(plan) is not dict:
                raise ValueError()
        except (ValueError, TypeError, RecursionError):
            raise TripIntentError('invalid stored source', 'invalid_candidate') from None
        details.append({'id': row['id'], 'tripId': row['trip_id'], 'revision': row['revision'],
                        'trip': {**trip, 'id': row['trip_id']}, 'plan': plan})
        versions[row['id']] = row['trip_revision']
    authorized_ids = set(versions)
    candidates = project_trip_candidates(details, role=current.actor['role'],
        authorize=lambda detail: detail['id'] in authorized_ids)
    sources = {}
    for candidate in candidates:
        source = {key: candidate[key] for key in ('journeyId', 'tripId', 'revision', 'title', 'start', 'end')}
        source['tripRevision'] = versions[candidate['journeyId']]
        source['sourceVersion'] = _digest({'candidate': candidate, 'tripRevision': source['tripRevision']})
        sources[candidate['ref']] = source
    return candidates, sources, _digest({'candidates': candidates, 'sources': sources})


def register_assistant_trip_change(app, db, Problem, body, require_member, limited, *, invoke_model=None):
    """Register after journeys/member sessions; initialization performs no SQL.

    invoke_model is only a test/dependency injection seam. Production defaults
    to the configured, fixed-provider home_assistant._model_json transport.
    """
    signer = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt=SELECTION_SALT)

    @app.errorhandler(TripChangeError)
    def assistant_trip_change_error(error):
        response = jsonify(error=error.message, code=error.code)
        response.headers['Cache-Control'] = 'no-store'
        return response, error.status

    def read_selection(value, current, identity):
        token, selected = value.get('selectionToken'), value.get('selectedRef')
        if (set(value) != {'selectionToken', 'selectedRef'} or type(token) is not str
                or not 1 <= len(token) <= MAX_TOKEN_LENGTH or type(selected) is not str
                or not re.fullmatch(r'trip_[a-f0-9]{24}', selected)):
            raise TripChangeError('请选择本次建议中的旅行。', 'invalid_selection')
        try:
            claim = signer.loads(token, max_age=SELECTION_TTL)
        except SignatureExpired:
            raise TripChangeError('旅行建议已过期，请重新整理需求。', 'selection_expired', 409) from None
        except BadSignature:
            raise TripChangeError('旅行选择凭据无法核对，请重新整理需求。', 'invalid_selection') from None
        if (type(claim) is not dict or set(claim) != {
                'v', 'actor', 'household', 'identity', 'prompt', 'catalogueDigest', 'model'}
                or claim.get('v') != 1):
            raise TripChangeError('旅行选择凭据无法核对，请重新整理需求。', 'invalid_selection')
        if (claim['actor'] != current.owner or claim['household'] != current.household
                or claim['identity'] != identity):
            raise TripChangeError('此旅行建议不属于当前登录会话，请重新整理需求。', 'selection_identity', 403)
        return claim, selected

    def response_for(result, sources, current, identity, prompt, catalogue_digest, advisory):
        token = None
        if result['status'] == 'choose_trip':
            token = signer.dumps({'v': 1, 'actor': current.owner, 'household': current.household,
                'identity': identity, 'prompt': prompt, 'catalogueDigest': catalogue_digest, 'model': advisory})
            if len(token) > MAX_TOKEN_LENGTH:
                raise TripChangeError('旅行建议过长，请精简需求后重试。', 'selection_too_large')
        selected = result['selected']
        response = jsonify(version=1, **result, source=sources[selected['ref']] if selected else None,
                           selectionToken=token, selectionExpiresIn=SELECTION_TTL if token else None)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/api/assistant/trip-change')
    def assistant_trip_change():
        current = ImportSession(app, db, Problem, require_member)
        current.fresh()
        if request.content_length is not None and request.content_length > MAX_REQUEST_BYTES:
            raise TripChangeError('旅行请求过长，请精简后重试。', 'request_too_large', 413)
        value = body()
        selecting = 'selectionToken' in value or 'selectedRef' in value
        if not selecting:
            if (not {'prompt'} <= set(value) <= {'prompt', 'useModel'}
                    or type(value['prompt']) is not str or not 1 <= len(value['prompt'].strip()) <= 2000
                    or type(value.get('useModel', False)) is not bool):
                raise TripChangeError('请填写 1～2000 字的需求，useModel 须为布尔值。', 'invalid_request')
        # limited() commits. It must never run inside an ImportSession read or
        # while retaining a SQLite/platform lock across a provider request.
        limited('assistant_trip_selection' if selecting else 'assistant_plan', 60 if selecting else 30,
                600 if selecting else 3600)
        try:
            with current.read() as con:
                identity = current.check()
                claim, selected = read_selection(value, current, identity) if selecting else (None, None)
                candidates, sources, catalogue_digest = _catalogue(con, current)
                if selecting:
                    if claim['catalogueDigest'] != catalogue_digest:
                        raise TripChangeError('旅行来源已变化，请重新整理需求并核对日期。', 'stale_source', 409)
                    result = plan_existing_trip(claim['prompt'], candidates, selected_ref=selected,
                                                model_output=claim['model'])
                    response = response_for(result, sources, current, identity, claim['prompt'],
                                            catalogue_digest, claim['model'])
            if selecting:
                return response

            prompt, advisory = value['prompt'].strip(), None
            result = plan_existing_trip(prompt, candidates)
            if value.get('useModel', False) and result['status'] != 'not_applicable':
                if home_assistant.model_settings(app.config) is None:
                    raise TripChangeError('AI 模型尚未配置；可关闭 AI 后整理本地日期建议。', 'model_unavailable', 503)

                def invoke(config, payload):
                    nonlocal advisory
                    raw = (invoke_model or home_assistant._model_json)(config, payload)
                    advisory = decode_model_intent(raw, prompt, candidates)
                    return advisory

                try:
                    result = model_trip_intent(app.config, prompt, candidates, invoke=invoke)
                except home_assistant.ModelProviderError as error:
                    raise TripChangeError(error.message, 'model_unavailable', error.status) from None
                except (HTTPError, URLError, TimeoutError, OSError, HTTPException,
                        ValueError, KeyError, TypeError, OverflowError, RecursionError) as error:
                    if isinstance(error, TripIntentError):
                        raise
                    raise TripChangeError('AI 建议暂不可用或格式无效；尚未改期。', 'invalid_model_output', 502) from None
                finally:
                    # Revocation wins even over a failed provider response.
                    current.fresh()

            with current.read() as con:
                _, fresh_sources, fresh_digest = _catalogue(con, current)
                if fresh_digest != catalogue_digest:
                    raise TripChangeError('旅行来源已变化，请重新整理需求并核对日期。', 'stale_source', 409)
                response = response_for(result, fresh_sources, current, identity, prompt, catalogue_digest, advisory)
            return response
        except TripIntentError as error:
            # Projection/selection errors also leave through a fresh auth check.
            current.fresh()
            raise _intent_error(error) from None
        except TripChangeError:
            current.fresh()
            raise
