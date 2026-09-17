# 旅行编辑的来源快照

本增量已随新版旅行分段发布，实际身份见 [发布验收](EXPO-JOURNEY-SEGMENTS-ACCEPTANCE.md#expo-segments-release)。沿用现有旅行接口、表结构和确认流程，不新增路由、DDL 或云写入。

`GET /api/journeys/templates` 增加 `capabilities: {editSourceSnapshot: true}`。新版分段编辑必须先确认此能力，并在进入编辑或用户明确重新核对时，从 `GET /api/journeys/<id>` 的 `trip/tasks/shopping/events` 构建完整 `{id: revision}`。这个版本表与原草稿绑定；发送前不得用新 GET 的版本表替换旧草稿来源。

`POST /api/journeys/preview` 对已有 `journeyId` 增加可选字段 `expectedEntities`，其余字段与响应保持原契约：

```json
{
  "journeyId": "0123456789abcdef01234567",
  "revision": 3,
  "expectedEntities": {"abcdef0123456789abcdef01": 7},
  "plan": {}
}
```

示例仅展示字段结构；真实请求必须带完整计划和全部已关联实体，不能仅提交示例的一项。规则如下：

- 仅已有的 24 位小写十六进制 journeyId 可以提交该字段。实体键也必须是 24 位小写十六进制 ID；版本是 `1..9007199254740991` 的整数，拒绝 bool、浮点和字符串。
- 数量上限 302：旅行与概览各一项，加准备、采购、分段日程各最多 100 项。不接受新建／旧 tripId 升级附带此字段。格式或数量错误返回 400。
- 精确比较完整实体集合和版本。缺项、多项、删除／新增关联、旧实体版本、旧 workflow revision 或旅行已删除返回 409，含 `error` 与 `code: "stale_edit_source"`。无预览令牌、无业务写入，客户端保留草稿后显式核对。
- 旧客户端省略该字段仍兼容，不能据此声称旧客户端具备 GET→preview 的来源保护。

预览在同一 SQLite 只读事务中读取 workflow 与关联实体、比对版本、规范化、合并冲突并签名。期间另一 WAL 连接提交的改动不会混入该快照；原 apply 实体 CAS 仍会在确认时拒绝旧预览。apply 的账号锁顺序、写事务、幂等回执和完成状态保全均未修改。

成员详情、模板与预览在事务开始校验真实 Cookie 对应的捕获 session ID、成员、认证版本和家庭；释放读取快照后再 fresh 校验。兼容旧 Cookie 解析产生的隐式事务，并在结束时释放。电视详情继续保留原有只读 200 权限和上层投影；模板和 preview 仍只准成员。没有扩大电视可见范围。

## 验证

`tests/test_journey_edit_snapshot.py` 使用真实临时 Flask/SQLite，52 项专项首轮通过；覆盖四类实体独立 HTTP 更新、删除及关联集合变化、字段边界、旧客户端、WAL 并发读取／确认拒绝、读后撤销／过期／认证版本、捕获会话不匹配、旧 Cookie 和电视只读兼容。并发时序只在真实 SQL 读写处注入，不替换业务成功响应。

最终同次组合运行上述专项与原 `test_journey_workflows.py`、`test_journey_details.py`、`test_journey_reschedule.py`、`test_journey_transaction_session.py`，实际 152 项全部通过，101.58 秒，无失败／跳过。52 项包含在 152 项内，不相加。原件为本工作树 `test-results/journey-edit-snapshot-regression-r2.xml`，SHA-256 `044dd0d255ef34db5d259969430479a36ce0dc67e6d334d238884121b9fa07e0`；运行前后 API 与新测试文件散列一致。首轮原件仍保留。

上述作者专项仅覆盖 API；后续组合浏览器及生产结果见 [发布验收](EXPO-JOURNEY-SEGMENTS-ACCEPTANCE.md#expo-segments-release)。真实云仍未验收；专项没有读取生产数据库或写第三方服务。
