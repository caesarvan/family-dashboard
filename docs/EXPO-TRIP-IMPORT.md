# Expo 旅行 JSON 导入

状态：已于 2026-09-18 04:42:28（北京时间）发布，04:43:27 正常 TLS 读回通过；完整身份、本地／Linux 实际结果及边界见[集中验收记录](EXPO-TRIP-IMPORT-ACCEPTANCE.md#expo-trip-import-release)。
首批范围遵循 [实现契约](EXPO-TRIP-IMPORT-PLAN.md)：一份文件／粘贴 → 服务端预览 → 明确确认 → 当前旅行详情。
只创建新旅行，不覆盖已有旅行，不代订、自动记账或写云日历。

## 使用流程

1. 从旅行计划列表的「导入旅行」进入，选择 JSON 文件或粘贴到「旅行 JSON」。Web 可下载原有第 1／2 版虚构示例。
2. 点「预览导入」，核对日期、同行成员、预算／预留／已付、将新增的数量、服务端警告。
   「目的地」「准备事项」「采购」「行程分段」可展开全部内容，每页五项；显示负责人、日期、金额、备注及各类时间语义。
3. 点「确认创建旅行」。保存回执通过核验后重新读取当前详情，再由父页面读取并打开原旅行；两次读取任一次失败都保留已知回执。
   要改计划时点「修改输入」重新预览；保存后复用已有行程分段编辑。

文件和粘贴均最多 200,000 UTF-8 字节。允许开头 BOM，拒绝空文件、坏编码／JSON、超限与过深嵌套。
只接受计划或仅含 `plan` 的包装；已有目标编号、实体版本、外部令牌、幂等键和冲突决策不可随文件带入。
省略字段保留给服务端处理：默认准备模板与默认目的地分段不等同于显式空数组，预览展示最终采用的真实事项。
金额沿现有 CNY 整数分；采购预算未知与零区分。不得根据浏览器时区猜 DST 或未知住宿时刻，服务端错误提供字段／可选偏移时由用户修改 JSON 后重预览。

## 恢复与隐私

- 普通保存失败保留输入。只有已实际尝试 apply 才保留未知操作；确认前身份检查失败不制造未知写入。
- 未知结果停在「核对保存结果」，没有自动 GET 或自动 POST。用户先读取当前旅行列表和原操作回执；未查到不代表未保存。
  仍有原令牌时可明确「按原请求重试」，始终使用同一个 token／key。未知请求后来返回 400／409 也不自动清除意图。
- 普通新建 token 1800 秒过期后 apply 在查旧回执前返回 409；必须用原 operations GET 恢复，不能套用改期或例行计划的其他语义。
- 查到历史回执不当作当前详情。已确认保存后的读取失败仅提供「重新读取旅行」，不恢复旧确认按钮或重复 apply。
- fresh 身份、当前列表、精确原回执 404 及后验身份均通过后，才可「结束本次核对」并二次明确「结束核对并清空输入」。
  提示原请求仍可能完成、重新创建可能重复；只清本地意图，原编号保留为可选中文本，可以「查询原操作」。
- hidden、窗口 blur、导航失焦、offline、pagehide 中止旧异步并隐藏全部输入／预览；同一完整身份保留内存草稿与未知意图。
  回来先重新核对身份及能力再展示。真身份变化清载荷；跨会话最多保留按家庭＋成员隔离的操作编号，仅供本人只读查询。
- 新读写复用 `SegmentFence` 的完整 role／household／member／authVersion／CSRF 前后检查与当前 CSRF；读取、回执和父交接都带 epoch。
  客户端围栏不替代服务端事务权限校验；组合版本的服务端检查见[旅行会话契约](JOURNEY-IMPORT-SESSIONS.md)。
- dirty、文件读取、busy、unknown、等待当前详情都报告独立导航 pending；明确放弃草稿才返回。旧回调不能释放新面板的锁。
  无 localStorage、URL 私人载荷或云端调用；关闭浏览器不保证恢复内存草稿，也不会撤回已发送请求。

## 接口与文件

- `TripImportPanel({onBack,onSaved,onPendingChange?})`；`onSaved` 只传 `{journeyId,tripId}`，等待父页面完成受身份与路由保护的读取。
  本面板在父交接完成前保留已知回执。入口、全局导航与返回由独立接线分支负责。
- [tripImport.ts](../frontend/src/lib/tripImport.ts) 复用归一化 `readPlan/readJourneyDetail`、身份围栏与受限请求。
  专属薄 reader 区分新建 apply、operations 与当前状态；GET `/journeys` 仅用于明确核对未知结果，不改共享请求白名单。
- [TripImportPanel.tsx](../frontend/src/components/TripImportPanel.tsx) 使用现有 Paper 主题／密度，44px 新控件；不增加第二套编辑表单或依赖。
- 稳定 testID：`trip-import-panel`、`trip-import-input`、`trip-import-file`、`trip-import-preview`、`trip-import-unknown`、`trip-import-saved`。
  输入标签「旅行 JSON」「原操作编号」；草稿退出对话框「放弃导入草稿？」；未知退出对话框「结束本次核对？」。

## 实际验证与边界

- [Node 模型测试](../tests/test_expo_trip_import.mjs) 内嵌真实临时 Flask／SQLite 合成 fixture，网络连接禁止，显式关闭额外 SQLite 连接。
  使用本分支固定父后端，两个仓库 JSON 示例、默认／空集合、重复提交、重启、本人新会话回执及真实 DST 双选择均由实际 API 返回。
  加上输入边界、畸形 DTO、未知状态、操作句柄隔离、晚回调及前置身份失败等，最终 **13/13 通过**。
  命令：设置 `TRIP_IMPORT_TEST_PYTHON` 后运行 `node --experimental-transform-types --test-reporter=tap --test tests/test_expo_trip_import.mjs`。
  可用 `TRIP_IMPORT_BACKEND_ROOT` 指向固定完整源码；不得把多个浮动树拼成后端。
- 私有结果：`W/expo-trip-import-ui/test-results/trip-import-final/`，Node 执行前后三个源码 SHA 相同；`node.tap` SHA
  `29dd20e6c698cd81b353ba18439aaeaccf9884a638d30fe6a77b7d855f677e24`。
- 定向 model＋Panel 严格 `noEmit` TypeScript 为 0 diagnostics，只读使用已安装的物理依赖映射；未安装依赖／改 lock，也未代替最终全应用检查。
- R1 12/13 的失败原件保留：测试误要求服务端 v1 正规化必须带 `schemaVersion:1`，改按合法缺省 v1 语义核对。
  初次类型 runner 的 Windows ESM 路径错误和后续类型窄化／弃用选项诊断均保留；最终修正通过，不抑制诊断。
- 以上为 UI 作者分支的历史结果。后续 R2 真实浏览器 12 组、四宽 12 图、完整类型检查、实际发布与 Linux 287 通过／1 跳过另见[集中验收](EXPO-TRIP-IMPORT-ACCEPTANCE.md)。原生系统选择框、本人真实文件、云日历与实体电视仍未在本轮验收。
