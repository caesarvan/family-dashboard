# 成员停用与日历／待办发布 worker

本候选只修改 [calendar_publish.py](../calendar_publish.py)、[task_publish.py](../task_publish.py)，使用 [成员关系领域](HOUSEHOLD-MEMBERSHIP-DESIGN.md) 的 active 状态；未合入、迁移或部署。专项 [test_membership_workers.py](../tests/test_membership_workers.py) 复用真实 Flask/SQLite 与现有 Google/Microsoft provider adapter，以合成 HTTP transport 执行，不访问任何真实云服务。

Worker 从一个短 SQLite 快照捕获整行发布绑定、发布者与云账户所有者的 member/membership ID、auth_version/revision，以及云账户身份和来源目标。每次后续 provider 方法调用前重新读取；本次 adapter.request 还套有限作用域的 fresh 检查，覆盖方法内部的分页及 POST/PATCH 后自动 GET，结束后恢复原 request。所有快照在网络调用前释放。锁顺序仍是原账户文件锁再短 SQLite 事务，不持 SQLite 锁等待网络。

所有 worker 队列修改、成功接受、错误转移和云端完成状态回流在 BEGIN IMMEDIATE 内重新检查原捕获值；由本 worker 已提交的中间状态重新捕获供下一步使用。退出、移除、角色／认证版本变化、来源重绑、暂停或其他队列变动胜出后，迟到成功／错误不能覆盖新状态。待办错误的 attempts 与终态现在同一事务写入，不再在两个事务之间留下可被暂停穿过的窗口。缺成员关系表或对应 active 行直接停止，不放行历史两人模式。

领域停用会保留本地及云端原件、令牌和不确定创建证据，将关联发布置 paused。已有外部请求可能已经完成；此处不宣称撤回它、不自动补写结果或再发送 POST。后续需要明确重新核对及授权。云同步 observe 对 inactive 的发布者仍抑制旧镜像，但不修改实体或调度状态。

同文件的手工冲突／时间变化预览也用原队列与成员指纹包住 provider 请求，返回前核对；待办采用云端内容、pause/resume/retry 在写事务核对原 queue。这样他端暂停或成员停用不会被网络后迟到的采用结果覆盖。现有签名、ETag、实体 revision、原成员会话校验继续保留，不改 HTTP 请求／响应合同。

验证分轮原件保留在 ignored `test-results/`。初始真实基线选择 12 项：8 FAIL、4 PASS，失败为读请求途中移除后仍 POST，或真实合成创建已完成的响应把 paused 改回 published；并未把已能拒绝的迟到错误算作新 bug。

| 原件目录 | 实际结果与受验范围 |
|---|---|
| `membership-workers-baseline-r1` | 8 FAIL / 4 PASS / 20 未选择，旧 worker 字节与最初领域 2855 复现 |
| `membership-workers-fixed-r1` | 首次修订专项 30 PASS，22.65 秒 |
| `membership-workers-compat-r1` | 原 calendar/task 90 项＋新增成员代次 8 项，98 PASS，81.49 秒 |
| `membership-workers-final-r1` | 每次 HTTP 检查后 worker 38 项＋原 calendar/task 90 项，同轮 128 PASS，103.28 秒 |
| `membership-workers-manual-r1` | 随后仅手工路径增量：新 6 项及相关 rebind/session/timing review/task conflict，共 160 PASS，133.72 秒 |

各轮保存 results.xml、stdout.txt、stderr.txt、record.json；最终两个通过轮的源码清单前后均一致、无 failure/error/skip。不能把不同轮次相加称为一次最终全套。后四轮独立加载已冻结领域 `754d2e1` / SHA `dad3afb0efa5bd8aa5cd0670185d023fb18c00c5b02d8468b682fbaeb7c9e757`；生产模块不使用外部路径。已有旧测试原断言保持，只由私有 `membership_compat_bootstrap.py` 在真实 env 夹具返回时初始化三张成员表；该测试夹具不代替 Root 的生产迁移／启动接线。

边界：这是 worker 及相关手工队列接受事务的保护，不替代 HTTP 会话／双 CSRF、个人账户跨库协调、cloud_accounts 的 owner 检查或完整成员运行接线。真实 provider 网络行为、已在途的外部动作和生产启用须单独验收。
