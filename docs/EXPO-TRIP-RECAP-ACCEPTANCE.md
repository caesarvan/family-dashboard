# 旅行回顾组合验收（尚未部署）

R2 固定候选 `6453339dcc6fb8d3d60b1a21953c02b2ca205f74`、tree `a5d0ac7aa5be525a7b1059f635b759ec69d2a668` 已完成真实临时浏览器 10/10 流程和 12 张截图的可见视口审查。本页记录本地验收，不代表 Linux 发布验证、正式合入或生产上线。

入口为已有 workflow 的「旅行详情 → 旅行回顾」。[使用与隐私契约](EXPO-TRIP-RECAP.md)、[入口接线](EXPO-TRIP-RECAP-INTEGRATION.md)、[浏览器执行方式](EXPO-TRIP-RECAP-BROWSER.md)分别说明产品行为和验证方法。

## 已核对的证据

以下 `A` 指私有目录 `C:/Users/caesarf/Documents/Codex/family-dashboard-access`，`W` 为其 `worktrees`；原件和截图不入 Git。

| 检查 | 实际结果与来源 |
| --- | --- |
| DTO／Node | 作者执行 `node --experimental-transform-types --test --test-reporter=tap tests/test_expo_trip_recap.mjs`，11/11、零失败／跳过；真实临时 Flask／SQLite 与净化合成 JPEG。最终修复后的 `W/expo-trip-recap-ui/test-results/recap-review-fix/node.tap` SHA `446db6eb0dff67d6f1e5dcd3a66c0699c55753053500efd4f023e25b5feec255`。旧 `recap-final` 属于修复前阶段，保留但不代替这份结果。 |
| 全量 TypeScript | Root 在 R2 `6453339dcc6fb8d3d60b1a21953c02b2ca205f74` 实际执行 `node frontend/typecheck.mjs`，主／测试配置 exit 0，6.410 秒。`A/expo-trip-recap-build-20260918-r2/typecheck.json` SHA `8e1c0049a703fbbe1d158f35706ccdc4dcab4dff4eaf9eeae03a362fc30fd1e2`，绑定 source/tree、cleanAfter；stdout SHA `e06b5185cf9fa8d032487267733caf2325010e36aa77dbb49fbb7d34726c23fc`，stderr 为空。 |
| R2 构建 | `A/expo-trip-recap-build-20260918-r2/build-evidence.json` SHA `7c5026ea42e6030b9c29a4f501c1782569c6a35f00ca1d9c03058b659752320b`，绑定上述 source/tree、189 个输入、23 个导出。JS 为 `entry-d856069d1733bcc6a7cffbdc239ed21d.js`；R1／R2 全部导出字节相同。 |
| R2 浏览器 | `W/expo-trip-recap-browser/test-results/expo-trip-recap-20260917T163007486652Z/result.json` SHA `a94c09621e03b138b0a302e9684a86b62225d0a6325e2098ab7008ca8ddb4ac1`；10/10、12 PNG，677 个 tracked 源码与 23 个导出前后相同，HEAD／clean 保持，10 组临时目录全部清理，页面异常／外网请求／生产写入均为 0。 |
| R2 视觉 | 同目录 `visual-review.json` SHA `cca81d8b8f58b3a33ca735dc947ce65442be5d11504fce7f68256bf82bb5aafd`；Root 实际逐看 12 图，结论 `PASS_VISIBLE_VIEWPORT`。四宽 320／390／1280／1920，浅色行程、长地点、深色紧凑照片各四图。 |

## R1 失败与两处修正

R1 受验 `3ea70c27262f82898b66248e32dc4bd2bc450493`，构建证据 SHA `492ff549e02d5de770fcfff0e356d56e44848813df8d52fdbea49551a50fbd51`。原报告 `W/expo-trip-recap-browser/test-results/expo-trip-recap-20260917T162338214277Z/result.json` SHA `ba8b93686fc8857032554ec6f1748e0da1843f4bd0e40c5654e3595e0b73bc1e`，实际 9/10、12 图。唯一失败是 harness 在删除旅行后误期待 workflow 详情 200 且 `trip=null`；现有外键级联实际删除 workflow，接口正确返回 404。没有据此判断产品权限或回顾清屏失败。

Root 查看 R1 全部 12 图，原 `visual-review.json` SHA `7faad55dbe90f3f829cd1ff689c4cf29c3fd951b6cd463bc7f8ce048498b4c64`，结论为 `PASS_VISIBLE_VIEWPORT_WITH_COVERAGE_GAP`：320／390 深色图只到照片标题，未覆盖图片本体。

`c5983d4` 把删除后的详情断言改为精确 404，保留后续地点 404 与 UI 清屏断言；`2687db495c20ef0c3e0b973bed549b65c6a433e9` 将深色截图滚动目标由标题改为图片。两处均经 Root 审查后合入 R2；未改应用代码、成功业务响应或原 R1 报告。R2 全十组重新实际执行通过。

## 覆盖与限制

实际验证包括当前日程的独立编辑／删除、8000 字备注与分页，v2 当地时间及未知住宿时刻，地点／照片 24 条分页，伙伴私密与共享、坐标投影，签名家庭隔离及电视拒绝，撤共享／删除照片、迟到响应、真实离线、15 秒重新授权和清旧图、失败重读与返回原旅行最新详情。浏览器成功 DTO 与 JPEG 均来自真实本地 API；仅媒体提供方任务结果与图片内容为合成 fixture。

视觉结论仅覆盖已滚动后的截图视口。R2 四宽均包含图片区域，但手机说明和下方按钮可能未覆盖；深色照片是近黑色合成 JPEG，不代表真实照片质量。44px 检查采样回顾主操作区，键盘关闭与后续焦点实际通过，不泛称全站控件验收。

visibility 与 window blur/focus 使用明确的事件模拟；不承诺浏览器事件循环冻结时即时擦除已交付像素。原生 App、本人真实资料／照片、真实云以及实体电视均未验。真实配对电视 cookie 的拒绝测试不等于实体电视验收。

行程、地点和照片分别 GET，不是跨模块同一瞬间快照。回顾不推断真实出行、实际路线、照片拍摄地点或到访；到访只按原记录的明确确认显示。不新增依赖、接口、数据库表或写入动作。本轮 Linux 发布验证、包绑定与部署结果仍待后续实际记录。
