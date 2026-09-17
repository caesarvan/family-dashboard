# Expo 来源导入界面：组合验收

<a id="expo-finance-source-candidate"></a>
## 当前候选与边界

来源导入 UI 尚未发布。固定组合 `c148699601d6234e5acc6f6e4f970b24700ccd1d`、tree `4f6a3451056ed8d2e64f3b178fa1d2aa10f83233` 已完成 Node、全量类型、构建与 R1 浏览器功能检查；12 张原始截图已由 UI 审查者逐张核 hash 并查看，`PASS_VISIBLE_VIEWPORT`，当前可见区域无阻断。本批不改后端、金额算法、依赖、表或共享规则，从财务页「更新资产来源」使用已发布的 preview／confirm／status 协议。

已由非作者审查并合入的四部分：UI／model `efdaeb0d3b623e503ebca122f7edf9e699153a32`，入口与导航 `39397e97b1a06b14c4cc8443e2bf618104dadcc4`，浏览器 `bf0cbc1c1a6172918fd056fa7659243546436895`，发布适配器 `d29f15e42e6c2f9bdae75fbd7899f34903c5faed`。这四项审查不代替最终组合或生产验收。

本地私有路径以下以 `A=family-dashboard-access`、`W=A/worktrees` 简写；原件不提交 Git。

| 实证 | 实际结果与固定原件 |
| --- | --- |
| Node 模型 | 固定真实 API `05ee6568` 的临时 Flask／SQLite 合成来源，15 passed／0 failed。`W/expo-finance-source-ui/test-results/source-import-node-final.tap` SHA `bd59a03f0fff6a3fbde9b9f7df14bc32cc1384fb7eef01db72adb97e07e2e3f1`；原作者调试 r1–r5 日志保留，不合计。 |
| TypeScript | 严格 model／Panel 定向 0 诊断；组合 `4b6d6c5aeba98386e0aafe712313a3fce2524359` 直接执行 `node frontend/typecheck.mjs` exit 0（主配置＋测试配置），其前端字节与 `c1486996` 相同。`A/expo-finance-source-typecheck-r1.log` SHA `e06b5185cf9fa8d032487267733caf2325010e36aa77dbb49fbb7d34726c23fc`。 |
| Expo 构建 | `A/expo-finance-source-build-20260917-r1/build-evidence.json` SHA `c73d2bb7d578f040472a0583a07307a6c54d4907fdb6d39f2b25fe72da0020e9`；来源为上述 head／tree，184 个构建输入、23 个导出。 |
| 浏览器功能 R1 | 一次真实运行 12／12、12 PNG。`W/expo-finance-source-browser/test-results/expo-finance-source-20260917T140931825859Z/result.json` SHA `ba01e02acccecdd6ed7643c7bdc2902356a131bdff0d1ee8e890e13a0e90fd03`。源码／导出前后 649／23 相同、clean、12 案例清理完成；0 页面错误／外部请求／生产写入。 |
| 视觉 | 同一浏览器目录的 `visual-review.json` SHA `40d6fd64e8236d8574ffed4f454d1f7954a203ead258991e0abd3d3d18cf85c3`；审查者 `/root/expo_finance_ui` 实际查看全部 12 PNG，没有重跑浏览器。 |
| 发布适配器 | 20 passed；XML SHA `04650ea3708ee861655114e2cf754375feb3cdc00b3b5f1c083facb58d6d7030`。真实父九工具 CLI 7 个未绑定拒绝、33 个坏 freeze、37 个后端字节变更拒绝通过；完整范围见 [发布说明](EXPO-FINANCE-SOURCE-RELEASE.md)。 |
| Python collection | `A/expo-finance-source-validation-20260917-r1/collection.json` SHA `cbe997970fdbd3e592cc7ddc973e16bcd7b4aee6d22c43be04cba507a777ce45`；同一冻结 head 实际 8 模块／184 唯一 nodeId，`collectedOnly=true`、`executed=false`，不是 184 passed。 |

浏览器 invocation 原件为 `W/expo-finance-source-browser/test-results/source-r1-invocation-20260917T1409303354110Z/`，stdout SHA `4f4c76f43a5390f778333a9f2b7b06f18b19d9a0ec18b2c1c0a339cb74e537bf`，stderr 空。R1 无失败案例；未重新运行浏览器或修改成功响应来取得通过。Node、适配器、浏览器和 collection 彼此不累加为总通过数；构建输入 184 与收集测试 184 不是同一集合。

## 本轮实际覆盖

真实临时 Flask／SQLite／HTTPS loopback／Edge 覆盖两条来源流程、预览零业务写、明确确认与后端重启、消费观察不改资产／账本／持仓、格式／体积／金额拒绝、真实并发冲突、提交后丢响应的精确 GET 与原请求重试、未送达时 found=false 仍未知及明确结束核对、过期与新会话历史回执、两成员／跨户／匿名／配对 TV、迟到身份、隐藏／断网和导航返回。成功业务 DTO 均来自实际 API；来源 JSON 全为合成，故障只丢弃或延迟真实请求／响应。

12 PNG 包含 320／390／1280／1920 四宽的浅色完整来源、深色紧凑消费预览及成功回执；自动检查横向溢出、长文本和两个主按钮的 44px 尺寸。独立逐图视查确认长标题／路径／操作编号换行，未知金额、零、负净额及历史回执区别可读。浅色图只覆盖列表中段，窄屏消费图不包含底部确认区，回执下方输入也未完整覆盖；不能扩称整个内层滚动页面或真实手机验收。

后台使用可见性事件模拟，断网使用浏览器 offline；到期由真实 signer 时间夹具推进，未等待真实 20 分钟。本人真实财务文件、银行／邮箱访问、新云操作、实体电视和原生设备均未验收。完整使用与恢复语义见 [操作说明](EXPO-FINANCE-SOURCE-IMPORT.md)、[入口接线](EXPO-FINANCE-SOURCE-INTEGRATION.md) 和 [浏览器范围](EXPO-FINANCE-SOURCE-BROWSER.md)。

## 当前线上父版本

父 baseline 已于 2026-09-17 21:58:49 激活、21:59:22 TLS 读回、22:01:55 独立只读核验通过（北京时间）。实际 main `0bd330a6`／source `f0317fb6`／tree `f9f14984`，镜像、archive 和 manifest 见 [发布适配器](EXPO-FINANCE-SOURCE-RELEASE.md)。独立审计 `A/expo-baseline-published-audit-20260917T135020363048Z/audit.json` SHA `86358d4a77f074f9ff581c0efdab7e3c5ef2aed4d096494658a245f7afb8ac87` 已核。

父版本实际 Linux 347 passed＋1 精确 Windows junction skip、55 张户内表及注册库保持、1 户两库备份，四服务运行／零重启，仅 app 配置 healthcheck 且 healthy；发布后逐库在线备份不等于全局事务或重新核对 live 全组快照。这些是父发布事实，不是本批来源 UI 的生产验证。新组合正式合入、freeze、九工具独立审查、Linux 和发布仍待完成。
