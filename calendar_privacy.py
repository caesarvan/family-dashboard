"""Local calendar object ACL; participant/owner is never an access credential.

Records without both privacy keys predate this contract and remain shared.
Cloud mirrors and journey-generated entries retain that explicit legacy policy.
"""


class CalendarPrivacyError(ValueError):
    def __init__(self, message, status=400, code='invalid_calendar_privacy'):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def legacy(item):
    return 'visibility' not in item and 'createdBy' not in item


def scope(item):
    if legacy(item):
        return 'shared'
    creator = item.get('createdBy')
    if isinstance(creator, str) and creator and item.get('visibility') in ('private', 'shared'):
        return item['visibility']
    return None  # Partial or corrupt privacy metadata must never become shared.


def visible(item, actor):
    if not actor or actor.get('role') not in ('member', 'tv'):
        return False
    mode = scope(item)
    return mode == 'shared' or (mode == 'private' and actor.get('role') == 'member'
                                and item.get('createdBy') == actor.get('id'))


def require_visible(item, actor):
    if not visible(item, actor):
        raise CalendarPrivacyError('日程不存在或当前不可访问', 404, 'calendar_event_unavailable')


def creation(incoming, actor):
    if 'createdBy' in incoming:
        raise CalendarPrivacyError('创建者由当前登录身份确定，不能自行填写')
    mode = incoming.get('visibility', 'private')
    if mode not in ('private', 'shared'):
        raise CalendarPrivacyError('请选择仅自己可见或家庭共享')
    if not actor or actor.get('role') != 'member':
        raise CalendarPrivacyError('请使用成员账户创建日程', 403, 'calendar_privacy_forbidden')
    return {'visibility': mode, 'createdBy': actor['id']}


def update(original, incoming, actor):
    require_visible(original, actor)
    if legacy(original):
        if 'visibility' in incoming or 'createdBy' in incoming:
            raise CalendarPrivacyError('旧共享日程没有可核对的创建者，不能改为私人日程',
                                       403, 'calendar_privacy_forbidden')
        return {}
    if 'createdBy' in incoming and incoming['createdBy'] != original['createdBy']:
        raise CalendarPrivacyError('日程创建者不能更改')
    mode = incoming.get('visibility', original['visibility'])
    if mode not in ('private', 'shared'):
        raise CalendarPrivacyError('请选择仅自己可见或家庭共享')
    if mode != original['visibility'] and actor['id'] != original['createdBy']:
        raise CalendarPrivacyError('只有创建者可以更改日程共享范围', 403, 'calendar_privacy_forbidden')
    return {'visibility': mode, 'createdBy': original['createdBy']}
