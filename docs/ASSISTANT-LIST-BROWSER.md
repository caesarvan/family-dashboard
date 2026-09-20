# 助理清单调整：真实浏览器验收工具

工具 `tests/browser_assistant_list_editing_check.py` 在独立临时目录启动真实 Flask、SQLite 和本地 HTTPS，并用固定 Expo 导出运行 Edge。开发基线为 `0b69b3996a989a444b1d6787d902f8a24985dc40`。当前只完成工具准备；前后端合并、正式构建和非作者审查完成后，由集成人运行。静态检查不是浏览器通过，也不是本人 A–D 验收。

公开接口以 [助理清单合同](ASSISTANT-LIST-EDITING.md) 为准；本文件不增加字段或更改保存语义。夹具复用现有 `browser_expo_local_photo_check.Run` 的真实应用、登录、外联禁止、有界响应完成、截图和清理，复用原正式构建核验方法，不替换业务 DTO。

## 两个有界流程

| case | 实际操作和断言 | 截图 |
|---|---|---|
| `mobile_edit_save_home` | 390px 下本地规则生成采购；逐项调整标题、负责人、截止、备注、数量、优先级及预算 `null / 0 / 15990` 分。编辑阶段数据库不变，明确保存后比对真实实体原 ID、每个字段及唯一审计。再保存任务并核对采购页刷新、首页分工和日期；财务、库存、媒体与旅行数据保持。 | 3 |
| `lost_reload_identity` | 1280px 下真实 apply 已提交后仅丢弃响应；GET 取原回执、整页 reload 恢复同一计划，全程恰好一次 apply POST，实体／审计不再写。实际离线隐藏；保持真实 owner GET 响应，在真实登录切成员后才交付，等待页面尾部 `/me` 和账户菜单完成，MutationObserver 检查迟到内容不安装，清除最小恢复标识。另用真实会话撤销核验 GET 401。 | 3 |

采购截止日期来自真实服务端 brief，不依赖硬编码过期日期。计划来自真实本地规则（分号分项），明确不调用模型或服务商。数据库只含虚构成员和事项；保存前后的原件仅来自本次临时库。settings 仅把已知 meta revision 单独核对恰加一，其余 settings 和关联业务表摘要必须保持；原计划回执和创建 ID 必须对应实际持久化结果。

恢复存储只允许 `family-assistant-plan-v1` 下 `{memberIdentity,planId}`，不保存提示词、金额、标题或令牌。超时、任何非预期 HTTP 5xx、页面异常、外联尝试或清理失败均不产生 PASS。响应丢弃和迟到响应使用 `route.fetch()` 获取实际状态／字节，不制造成功返回；`requestfinished` 与响应监听在触发前注册并设 15 秒上限，不使用无界 `Response.finished()`。

## 固定输入与运行

从经审查、干净的完整组合源码执行；以下占位值由集成人替换为实际身份：

```powershell
& '<现有Python路径>' -B -X utf8 tests/browser_assistant_list_editing_check.py `
  --source-root '<冻结组合目录>' --expected-head '<完整40位HEAD>' `
  --bundle '<正式Expo导出web目录>' --expected-build-evidence '<真实build-evidence SHA256>' `
  --temp-root 'C:/tmp'
```

默认运行两个 case；指定 `--case lost_reload_identity` 仅运行该流程，结果必须如实记作分轮补验。禁止因失败重跑已通过流程来覆盖原件。

默认构建与执行 source 相同。只有显式 `--build-source-head` 指向当前 HEAD 的祖先，且两者差异严格只有本工具和本文档，才允许复用原构建；仍核构建 commit/tree、完整 frontend/supplemental/additional 输入以及每个实际导出文件。业务或其它工具变动不能借此规则复用。

每次输出独占 `test-results/assistant-list-<UTC>/`：实际执行脚本、每流程真实 HTTP／数据库证据、三张截图、异常原件、`result.json`。报告分别写执行 source、构建 source、输入及导出前后散列和已加载夹具路径；父夹具 map 保留，新工具依赖使用独立 `listFixtureHashes`。上下文关闭、数据库连接显式 closing、请求线程 join、HTTPS listener 停止及临时目录删除都是成功条件。没有 SSH、生产访问、云发布、付款、扣库或外部账户验收。

控件接缝由前端作者明确约定：`assistant-list-action-<index>`、`action-edit-<index>`、`assistant-action-editor`、`action-title/due/note/quantity/budget`、`action-owner-<id>`、`action-priority-<value>`、`action-edit-save/cancel`、`assistant-list-apply/unknown/recheck/receipt`。正式执行前仍须对冻结 UI 核验这些名称；不能用隐藏控件或更宽断言掩盖契约不一致。
