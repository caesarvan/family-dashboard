"""Local shared-task dependencies. No schema, scheduler, provider or implicit write.

Writers call check_write/check_delete after BEGIN IMMEDIATE and retain that
transaction through the entity write. Projections use the caller's read snapshot.
"""
import json

MAX_DEPENDENCIES = 20


class DependencyError(ValueError):
    def __init__(self, message, code='invalid_task_dependencies', status=400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def ids(value):
    if (not isinstance(value, list) or len(value) > MAX_DEPENDENCIES
            or any(not isinstance(uid, str) or not uid or len(uid) > 128
                   or uid != uid.strip() for uid in value)
            or len(set(value)) != len(value)):
        raise DependencyError('前置事项须为最多 20 个不同的本地任务编号')
    return list(value)


def task_graph(con):
    return {row['id']: json.loads(row['data']) for row in con.execute(
        "SELECT id,data FROM entities WHERE kind='tasks'")}


def project(value, graph):
    dependencies = ids(value.get('dependsOn', []))
    blocked = [uid for uid in dependencies if uid not in graph
               or graph[uid].get('sync') or graph[uid].get('done') is not True]
    return {**value, 'dependsOn': dependencies, 'blockedBy': blocked,
            'dependencyStatus': 'done' if value.get('done') is True else 'blocked' if blocked else 'ready'}


def check_write(con, uid, value, original=None):
    if not con.in_transaction:
        raise RuntimeError('task_dependency_write_requires_transaction')
    dependencies = ids(value.get('dependsOn', []))
    if dependencies and value.get('sync'):
        raise DependencyError('云端清单不支持前置事项，请改用看板本地任务')
    graph = task_graph(con)
    for target in dependencies:
        if target == uid:
            raise DependencyError('任务不能依赖自身')
        if target not in graph or graph[target].get('sync'):
            # Missing, foreign household and cloud references share one message.
            raise DependencyError('前置事项不可用，请重新选择当前家庭的本地任务',
                                  'task_dependency_unavailable', 409)
    # Iterative DFS avoids Python recursion limits for long, valid task chains.
    graph[uid] = value
    visiting, visited = set(), set()
    stack = [(uid, False)]
    while stack:
        current, leaving = stack.pop()
        if leaving:
            visiting.remove(current)
            visited.add(current)
            continue
        if current in visiting:
            raise DependencyError('前置事项形成循环，请调整选择', 'task_dependency_cycle', 409)
        if current in visited:
            continue
        node = graph.get(current)
        if node is None or node.get('sync'):
            raise DependencyError('前置事项不可用，请先核对依赖关系',
                                  'task_dependency_unavailable', 409)
        visiting.add(current)
        stack.append((current, True))
        stack.extend((target, False) for target in reversed(ids(node.get('dependsOn', []))))
    # Completion is historical. Reopening a predecessor never silently reopens
    # an already completed successor or prevents unrelated edits to its record.
    if value.get('done') is True and (original or {}).get('done') is not True:
        if project(value, graph)['blockedBy']:
            raise DependencyError('前置事项尚未完成，请先处理后再完成这项任务',
                                  'task_dependencies_incomplete', 409)


def check_delete(con, uid):
    if not con.in_transaction:
        raise RuntimeError('task_dependency_delete_requires_transaction')
    if any(uid in ids(value.get('dependsOn', [])) for value in task_graph(con).values()):
        raise DependencyError('还有任务依赖此事项，请先明确解除依赖再删除',
                              'task_has_dependents', 409)
