# Expo 更新资产来源

此页是独立实现候选，尚未完成接线、组合浏览器或发布验收。它使用现有导入协议，不创建新路由、表或外部刷新任务。

## 使用步骤

1. 选择“完整资产来源”或“仅更新消费观察”。前者更新本人来源记录及已批准的家庭资产／负债小计；后者只更新消费观察，不改变资产基线、持仓、交易账本或荷包。
2. 选择已有转换工具生成的 JSON 文件，或粘贴其内容。文件须非空、小于 1.95 MB；页面不登录邮箱、不调用金融机构、不修补来源金额。
3. 点击“预览来源变化”。服务器校验真实来源结构、记录映射、金额、日期与覆盖范围。错误说明按原协议展示，不在客户端重新计算财务结果。
4. 核对新增／更新／保留数量、资产日期、消费覆盖窗口、缺口、共享小计和逐项明细。记录可搜索并按 10 项分页；警告、文件名与滚出月份按 5 项分页。未估值金额显示待核对，零仍显示零；外币不换算合并。
5. 勾选“我已核对来源日期、变化和共享范围”，再点击“确认保存来源”。确认进行中禁止再次提交。正常成功会显示操作回执，并另行读取当前来源状态。

只有本人可更新、读取详细来源和历史回执。伴侣只获得原有批准的共享小计；电视不能访问这些导入接口。浅色／深色、标准／紧凑沿用成员主题；操作按钮至少 44px。

## 冲突、不确定结果与隐私

- 预览使用刚读取的版本与来源摘要，确认提交原候选和原预览凭据。明确版本冲突需再次读取、重新预览和再次确认，不自动覆盖。
- `/me` 前置核验失败不会发确认，也不会创建未知写入状态。只有进入实际确认回调后，才保留操作编号。
- 断网、非法成功响应或后置身份核验失败均不能当成保存失败。此时“核对操作结果”只 GET 精确操作编号；同一可见会话仍持有原载荷时，可明确“按原请求重试”。不会自动换候选、编号或 token。
- `found:false` 只表示当前未找到回执，不表示没有执行。通用 400／403／409 也不能解除既有未知操作。
- 只有 mutation 明确返回 `410 preview_expired` 或 `409 preview_repreview_required`，且后置完整身份核验成功，才能根据服务端拒绝结束原未知操作并要求重新预览。旧的未绑定、无回执凭据不能产生新写入。
- 若已清除原 token，核对仍无回执：先通过 fresh `/me`、当前 status、精确编号 GET `found:false` 和后置 `/me`，才提供“结束本次核对”。二次确认明确说明“暂未查到历史结果，不能证明未提交；结束后可重新选择文件，核对最新版本再预览”。这是用户结束核对的决定，不是未执行的结论；原编号在确认页及结束后仍可复制查询。不会自动 POST 或预览，新确认仍受当前 CAS 保护。
- 后台、失焦、离线、离开或身份变化会清除 JSON、文件内容、预览、私密状态和 token，并取消异步；不会把迟到响应重新显示。
- 已尝试确认的恢复句柄只包含 `{mode, operationId}`，在应用内存按家庭＋成员隔离。不会写入 localStorage、URL、日志或持久缓存。相同本人重新登录可读取历史回执。
- “保留操作编号并返回”须明确确认，清除私密载荷后返回。刷新或关闭应用会丢失内存编号；可自行保留编号，再用“已有操作编号”读取本人历史。编号不是重新执行写入的凭据。
- 已取得成功回执后，后续当前状态 GET 失败只显示历史回执与明确重新读取入口；不会恢复旧预览、旧可保存操作或假称当前状态已更新。

## 组件与协议

`FinanceSourceImportPanel` 默认导出，props 为 `{onBack, onPendingChange?}`。接线由集成人负责。草稿、文件读取、请求及未知结果同步报告 pending；明确返回先清父导航锁，再调用 `onBack`。根导航需尊重该锁，页面自身提供离开确认和 `beforeunload` 提示。

| 范围 | 现有协议 |
| --- | --- |
| 身份 | GET `/api/me`，请求前后完整比较 role、householdId、id、auth_version、csrf |
| 当前状态 | GET `/api/finance-baseline/imports/status?mode=baseline` 或 `mode=spending_observation` |
| 精确历史 | 同一路径追加单个 `operationId=<64 位小写十六进制>` |
| 预览 | POST `/api/finance-baseline/imports/preview` |
| 确认 | POST `/api/finance-baseline/imports/confirm` |

完整来源预览为 `{candidate, expectedRevision, expectedSourceDigest}`；确认仅 `{candidate, previewToken}`。
消费观察预览额外带 `mode`、四项 `expected` 和明确的 `acknowledgeUnknownPreviousCoverage`；确认仅 `{mode, candidate, previewToken}`。
预览的 `operationId` 与确认回执 `receiptId` 必须一致。成功 GET 返回 `{mode, operationId, found:true, receipt}`；回执是历史记录，不能回写当前来源状态。

客户端请求只允许固定同源路径，显式 same-origin、no-store、redirect:error 和 30 秒超时。请求少于 2 MB、响应至多 4 MB；文件使用 UTF-8 严格解码，JSON 有体积、深度和节点限制。外部字段作为文本展示，不执行文件内容。

## 当前验证与后续边界

- 固定 API `05ee656825a7209c8b5c903c3eb94067fc7d00a0` 的真实 Flask／SQLite 临时合成来源，独立 Node 模型 **15 项通过**。包括两 lane、预览零写、确认与原请求重放、真实新登录回执、伙伴隔离、TV／匿名拒绝、锁内过期代码、null／0／外币、完整身份／epoch、限制和不确定恢复；明确决定才解除核对、单独 false 不解锁、旧句柄不清其他家庭或新操作。
- 所有测试数据库连接显式关闭，临时目录自动清理，测试禁止外部网络。没有个人真实输入或生产请求。
- 严格 model＋Panel 定向 TypeScript **0 个诊断**；只读映射现有物理依赖，不新增依赖或安装。
- 本分支未接入 FinanceScreen；全量组合类型检查、真实浏览器导入／恢复／导航锁、四宽视觉及实际账号流程均待独立验收。

运行模型测试（PowerShell，路径按实际工作树设置）：

```powershell
$env:SOURCE_IMPORT_BACKEND_ROOT = '<完整 API 源工作树>'
$env:SOURCE_IMPORT_TEST_PYTHON = '<已安装项目依赖的 python.exe>'
node --experimental-transform-types --test --test-reporter=tap tests/test_expo_finance_source_import.mjs
```

现有时间显示 helper 使用 TypeScript 参数属性，所以 Node 需 `--experimental-transform-types`，仅 strip 模式不能启动。模型测试不替代浏览器完成边界；消费记录的来源正确性仍由原始来源材料决定。

协议依据：[来源桥接](FINANCE-SOURCE-BRIDGE.md)、[消费观察](SPENDING-OBSERVATIONS.md)。会话与精确回执增强来自独立 API 分支 `05ee6568`，组合后参见其 `FINANCE-IMPORT-SESSION-RECOVERY.md`。
