# 成员显示偏好 API

本轮开发候选，尚未发布。复用 `household_spaces.py` 的 `/api/preferences` 与现有 `member_preferences(owner,data)`，无表、列、依赖或路由新增。外观偏好与本人首页卡片布局、每台电视设置分别保存。

## 读取与默认值

有效成员 `GET /api/preferences` 返回平铺对象：

```json
{"theme":"forest","density":"comfortable","homeView":"today","colorMode":"light","revision":0}
```

| 字段 | 允许值 | 默认 |
| --- | --- | --- |
| `theme` | `forest`、`light`、`ocean` | `forest` |
| `density` | `comfortable`、`compact` | `comfortable` |
| `homeView` | `today`、`week`、`around` | `today` |
| `colorMode` | `light`、`dark` | `light` |
| `revision` | 0～9007199254740991 的整数，拒绝布尔及浮点值 | `0` |

无行或旧 JSON 缺少字段时仅在响应中补默认值，不因 GET 写回；旧行缺少 `colorMode`／`revision` 时分别为 `light`／`0`。已有未知 JSON 字段不投影到响应。存量 JSON 结构、已知枚举或版本损坏时返回 503，不回退为版本 0、不暴露原始值。

## 明确保存与并发

`PUT /api/preferences` 必须为同源 JSON，携带有效成员会话及 CSRF；只接受下列两个顶层字段：

```json
{"revision":0,"changes":{"colorMode":"dark","density":"compact"}}
```

`changes` 是非空、已知偏好字段的子集，不接受 `owner`、`revision` 或未知字段。未提交的偏好保持；现存未知 JSON 字段也保持。只按当前成员及签名家庭定位，不接受客户端指定归属。成功返回包含四个偏好和当前版本的完整平铺对象。

- 版本不匹配返回 409，整次不写；即使变化值与当前相同，旧版本也不能绕过比较。
- 同版本、同值保存为 no-op：不增加版本、不创建默认行、不修改原 JSON、不写审计或全局 revision。
- 实际变化增加一次版本，并在同一事务写入偏好和 `preferences_update` 审计。版本已达安全整数上限时，仍允许同值 no-op，但拒绝会溢出的修改（409）。
- 旧的三字段完整对象或缺少版本的请求返回 400 并提示刷新；没有兼容的无版本写通道。其他格式、类型或枚举错误也返回 400。
- 匿名返回 401，电视身份返回 403；成员 CSRF／同源检查沿用全局守卫。凭证失效返回 401。

接口没有幂等请求编号或操作回执。已尝试 PUT 后丢响应或后置身份核验失败，客户端应保留原意图，先 GET 当前偏好，再由本人明确采用或保留修改；读到相同内容不能证明原请求是否执行，不自动重发。

## 事务与隔离

PUT 在 `BEGIN IMMEDIATE` 取得写锁后读取真实 `member_sessions`，核对当前成员、认证版本、具体会话和家庭，再读版本、比较及保存；提交前再次核对，异常显式 rollback，审计和全局 revision 一并回滚。SQLite 写锁确保两次同版本修改最多一次成功，等待写锁期间撤销的会话不能继续保存。

GET 在读取快照内核对真实凭证，读取后先释放快照，再 fresh 核对，拒绝读取期间发生的撤权。JSON 解析失败同样释放事务。成员会话引擎的正常认证维护不等同于偏好数据写入。

## 接线与验证

所有旧客户端须同步更新为 `{revision,changes}`；日程范围切换也需先读版本并采用同一 CAS 契约。经典 `theme` 与 Expo 的 `colorMode` 分开，不把未编辑字段重新覆盖；主题／密度如何呈现由前端负责，API 保存成功不证明物理设备显示效果。

真实临时 Flask／SQLite 专项位于 [test_member_preferences.py](../tests/test_member_preferences.py)，与现有 [家庭隔离](../tests/test_household_spaces.py)、[首页布局](../tests/test_dashboard_layout.py) 测试一起执行。测试只使用合成家庭与真实本地会话，包含独立连接撤权、真实写锁等待和并发 CAS；不使用生产数据库或真实云服务。

本轮三个模块实际 **64 项通过**（新增偏好 38、家庭隔离 9、首页布局 17），零失败／错误／跳过，耗时 50.83 秒。私有 `expo-appearance-api/test-results/member-preferences-r1.xml` 的 SHA256 为 `41c692884757c5124ba5eecdeabacc88ef1e8df40c6faa3e7bdcf9fbffc15947`。这不包含前端组合浏览器、生产部署、真实云或实体设备验收；后续按 [Git 协作约定](GIT-WORKFLOW.md) 审查与集成。
