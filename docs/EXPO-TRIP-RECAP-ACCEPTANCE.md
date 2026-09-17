# 旅行回顾发布与组合验收

R2 固定候选 `6453339dcc6fb8d3d60b1a21953c02b2ca205f74`、tree `a5d0ac7aa5be525a7b1059f635b759ec69d2a668` 已完成真实临时浏览器 10/10 流程和 12 张截图的可见视口审查。本地结果与下方真实服务器发布记录分别列出，不累加为一次全量验收。

已完成旅行计划的旅行，可从详情打开「旅行回顾」。[使用与隐私契约](EXPO-TRIP-RECAP.md)、[入口接线](EXPO-TRIP-RECAP-INTEGRATION.md)、[浏览器执行方式](EXPO-TRIP-RECAP-BROWSER.md)分别说明产品行为和验证方法。

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

行程、地点和照片分别 GET，不是跨模块同一瞬间快照。回顾不推断真实出行、实际路线、照片拍摄地点或到访；到访只按原记录的明确确认显示。不新增依赖、接口、数据库表或写入动作。本轮包绑定、实际 Linux／部署结果与独立审计 PASS 见本页发布节。

<a id="expo-trip-recap-release"></a>
## 2026-09-18 01:14:21 正式发布

北京时间 01:14:21 激活、01:15:15 正常 TLS post 读回完成。01:15:59 新一次只读状态检查仍匹配；独立审计已核五份服务器阶段原件及完整哈希链，结论 PASS。发布后的纯文档不改变下列实际安装身份。

| 项目 | 实际值 |
| --- | --- |
| 安装 main／正式 source | `ab94fb1e179ad7c53d0500483668a61a4da53c4a`／`bb4835794c5657d4658b3fef9e42676f61a876f9` |
| 同树 | `72ff985f9577b3fd5ea2891f616ebaf694164f47` |
| archive／manifest | `efb82e79139454a6239b947d3ede510940930cb0fdf19c339850b31878cc4b1e`／`2504bf48bf4d6275958a1bd2fc0b54efde933d88b7f918c1856fe0a2b245ca77` |
| app／sync／media 镜像 | `sha256:e7994bbca9f2b5d2116e1f8e1fb0db866c997be6477c89473983e9b125ece73b`；web 和环境保持 |
| release | `/opt/family-dashboard-releases/expo-trip-recap-58-20260917T171324858724Z` |
| 最终 freeze | `A/expo-trip-recap-freeze-20260918-r1.json` SHA `21520c8c8542034d1495a8ad7543807642965e80bf86051fd25a8451b92fec09` |
| 来源与受验字节 | 706 包文件＝683 源文件＋23 导出；189 构建输入与 R2 相同。R2 到正式源的已审工具／测试和文档差异逐项绑定，未将不同 Git 头称为同一次浏览器执行。38 根后端、Docker 和依赖不变。 |
| Linux 实际结果 | 七模块、181 个唯一测试：180 passed，唯一 `tests.test_frontend_runtime::test_windows_junction_rejected` 因 Windows junction 语义跳过；0 failure／error／deselect，运行文件测试前后保持 |
| 生产读回 | 706 源／导出文件、115 运行文件、75 HTTPS 资源匹配；24 内部生成资源与 1 退役资源拒绝，37 唯一匿名接口精确 401；四服务 running、零重启，仅 app 报 healthy，其他 health 为 null |

58→58 无 DDL，停写完整备份为 1 户／2 库。安装前与新 app 启动后完整快照 SHA 均为 `dd21e78d63c6e8db19e8d09ee0cd7933cb04c011764a5bacd3ad073d24b250af`，原行、BLOB、schema、序列与注册库保持；不重放账户 55→58 迁移。post 新备份 `manifest-20260917T171510740338Z.json` SHA `7a3ea466fbb7affe4fc2d9e205e7f428658a9ae864e8defe06b7f122d9076b06` 验证两库 58 表结构。它是逐库在线快照，`liveGroupSnapshotRechecked=false`，不是全局原子或 live 全组再快照。

`test_journey_places.py` 的旧工厂断言仍引用 55 表，因此整个模块未进入本次七模块选择；没有 deselect。该断言另分支修复的 91 项不在本包、不计入本次结果。地点阅读与权限仍由上方 R2 浏览器实际覆盖。适配器本地 21 项、模型 11 项、本地浏览器 10 组与服务器 180 项为不同集合／阶段，不相加。

私有服务器原件目录为 `A/expo-trip-recap-published-audit-20260918-r1`。`validation/results.xml` SHA `53c488c2fb9fb5b0d4f7149928eccc28f93c94a05f339a06a71f577be02b6025`，`validation/runtime.json` SHA `8484aa5b218b4b96f91b3bb4934627e2d6663258c1a7b61b02388f61db085996`，`validation/validation.log` SHA `e29c5e3e73dbd90175b035b50ee53dda41133c6ad10a017e9aeaa394a7b7ee2b`。`fresh-readback.json` SHA `2cdcbaede49c7c2fc9ae2d8342e078283ff7ade74ce195a97b2f9b01ba8b3428`：环境 mode 0600、37 匿名 401、四服务与正常 TLS 匹配，未读取数据库／环境正文或执行算子／备份。五份服务器阶段原件位于该目录的 `phase-reports/`，JSON 内容与各阶段 stdout 一致；下列散列取自原件字节：`phase-reports/activation.json` SHA `d10f9ad8ac5ed8c11440117ffa7a4fc391f8ee80477c7095857d96351d3c30ce`，`phase-reports/post-readback.json` SHA `337e3d4af126d04f70cfa4aa9287d73ce71eb0957bbefb467eef053f21e1c7bc`。

独立审计 `audit.json` SHA `8d6e94c2996233074e928b9c85298c599356fbcc1c456e9818093501ca2876cf`，结论 PASS。审计核对五阶段原件链、三份验证原件、唯一 JUnit 集合与 collection 一致，以及上述 fresh 结果；数据库 proof 未再次独立下载，其哈希及前后相等性由 activation 与已绑定 post 的重核记录支持。审计没有重放阶段、启动备份或读取数据库／环境正文，未扩大真实个人资料、云、原生设备或实体电视验收范围。
