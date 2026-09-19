# 家庭助理：旅行资料搜索

状态：已随资料／照片搜索批次发布；实际激活、独立审计与分段证据见[使用与集中验收](ASSISTANT-DOCUMENT-SEARCH-ACCEPTANCE.md#assistant-document-search-release)。下文作者验证记录保留其历史边界。本批只扩展现有 `/api/assistant/search` 与本地查询计划，不新增接口、数据表、索引、OCR、模型调用或自动下载。资料原有规则见 [JOURNEY-DOCUMENTS.md](JOURNEY-DOCUMENTS.md)。

## 查询与返回值

`GET /api/assistant/search?q=凭证&limit=20&offset=0` 保留原有参数与响应：`{query,matches,total,limit,offset,nextOffset}`。`q` 去除首尾空白后为 1–100 字符，`limit` 为 1–30、默认 20；`offset` 为 0–20000、默认 0。未知或重复参数继续拒绝，不能指定 owner 或其他家庭。

在既有 tasks、shopping、events、trips、inventory、media、places 类型之外，新增资料结果：

```json
{
  "kind": "documents",
  "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "title": "合成酒店凭证",
  "filename": "synthetic-hotel.pdf",
  "mimeType": "application/pdf",
  "revision": 1,
  "visibility": "private",
  "journey": {
    "id": "bbbbbbbbbbbbbbbbbbbbbbbb",
    "tripId": "cccccccccccccccccccccccc",
    "title": "合成旅行"
  }
}
```

资料 ID 为 32 位小写十六进制，旅行与 trip ID 为 24 位；revision 为正整数。当前资料域只保存 `application/pdf` 或 `image/jpeg`。`visibility` 为有效的 `private` 或 `shared`；本人未关联资料的 `journey` 为 null、visibility 为 private，即使其历史存储值仍为 shared。

匹配资料标题、文件名和现存关联旅行标题，使用字面子串与 Unicode casefold；`%`、`_`、引号不作为 SQL 通配符。不会匹配 PDF/图片内容、预订凭证内文字、分段内容或请求幂等信息，也不会推断预订已确认。关联旅行仅返回 id、tripId、title。结果不含 owner、大小、时间、分段、内容、文件哈希、requestId 或 downloadUrl。

全部可见类型合并后按 `(kind,id)` 排序，再计算 total、分页及 nextOffset。旧 kind 的返回字段保持不变。数据不变时分页顺序稳定；offset 不是固定快照，并发增删后应重新搜索，而不能把跨请求分页描述为冻结的数据集。

## 权限、只读与并发边界

成员身份与家庭仍由已签名会话及现有家庭路由决定。匿名为 401，电视为 403；本地查询计划继续要求同源 JSON 和 CSRF。每次资料查询位于原成员／家庭上下文的授权事务中，复用 `journey_documents.can_view_metadata` 与 `metadata`：上传者可以搜索本人未删除资料；伙伴仅能搜索仍关联本户现存旅行的 shared 资料。删除、解除关联、取消共享以及其他成员的私有资料，不进入伙伴结果或 total。

搜索只选取元数据，不读 BLOB、文件摘要或上传请求键。资料域函数 `search_metadata` 要求已有授权事务，由家庭助理传入当前成员，不负责建立新的会话或初始化数据库。查询不修改资料、旅行、计划、审计、日程或清单；现有认证层维护会话的行为保持。

先在授权事务中采集结果，释放旧 SQLite 快照后，再使用相同的会话上下文读取当前可见资料并重算资料匹配及全局总数，防止旧快照中的共享资料继续返回。最后释放读取快照，重新核对实际会话及 browser generation；已撤销会话返回固定错误，不返回旧资料标题或计数。资料可见范围以第二次元数据读取快照为准，之后的共享变更以及最终会话核对后的在途 HTTP 响应不能被追撤；打开资料详情或下载时仍须由原资料接口重新验证身份、可见范围和 revision。

## 本地计划与模型边界

`POST /api/assistant/plan` 中以“搜索”“查找”“找一下”开头的请求复用上述搜索，返回 `mode:local`、`id:null`、`actions:[]`，不保存 assistant plan，也不触发动作。即使请求带 `useModel:true` 或 `includeHouseholdContext:true`，搜索仍留在本地。

普通可选模型计划的 context 白名单继续只有 today，以及明确选择时的 events/tasks；资料元数据和文件内容均不会自动加入。已有 `/api/assistant/brief`、state、日历和云任务描述也没有增加资料信息。

## 验证与交接

`tests/test_assistant_document_search.py` 使用真实临时 Flask/SQLite、真实成员会话及合成资料，覆盖精简投影、BLOB/业务写入禁读写保护、私有与共享计数、取消共享／删除／解除关联、全局分页、字面查询、跨家庭、电视、CSRF、重启和旧 Cookie、本地计划与模型 context 排除。并发边界通过独立 SQLite 写入者在查询读快照期间变更权限、session、有效期、auth_version 或 browser generation 验证，不伪造“已认证”返回值。

前端由独立分支处理当前资料列表的重新核权与详情入口；本批不改前端，不根据搜索快照自动下载，不对外发送内容。实际浏览器、真实账号和生产部署结果须分别记录，不能由本地 API 测试推出。

作者本地验证：R1 为 34 passed、1 failed（34 项新专项及 1 项既有库存投影检查）。失败是测试误把删除旅行后仍保留的旧日程算作资料，修正为仅检查 documents 后，与原资料／会话组一起实跑 95/95；发布实现未因此修改。原助理相关组 45/45，筛选额外排除的两项 browser generation 单独 2/2 通过；真正浏览器用例未执行。合计当前 175 个不同节点有通过证据，分批执行，不声称一次全量运行；初次失败日志保留。
