# Expo 旅行分段编辑验收

本批仍为开发候选，尚未上线。当前生产版本是 [家庭例行计划](EXPO-ROUTINES-ACCEPTANCE.md#expo-routines-release)。实体电视无法由用户测试，继续明确标为未验收，不阻塞手机／电脑流程开发。

## 交付范围

从旅行详情进入「行程分段」，编辑城市、航班、住宿、活动及保留的旧日期段。地图或助理打开的旅行沿用原返回路径。既有日期结构须明确提供参考与城市时区后升级；服务端负责当地时间、夏令时及日历冲突核对，预览后再确认保存。

本批不办理外部预订或改签。人工取消标记不等于供应商已取消；分段移出后保留已有独立日程和资料。保存后的页面分别展示当前计划及实际关联日程，避免把保留的独立日程误报为已采用计划值。

## 已验证的后端候选

- 基线 `7713ad1fd091d7390612c52d434b97e54e99f54b`，作者固定提交 `6c9261e4655bb24932dc747920c1539d60e1e6f1`。Root 已独立读取完整差分、专项和会话实现，审查通过。
- 同一次组合 **152 项通过，0 失败／错误／跳过**：新编辑快照专项 52 项已包含在内，另含原 workflows、details、reschedule、transaction_session；不相加为另一总数。XML 报告测试时间 100.979 秒，命令整体约 101.58 秒。
- 原件 `worktrees/expo-journey-segments-api/test-results/journey-edit-snapshot-regression-r2.xml`，SHA256 `044dd0d255ef34db5d259969430479a36ce0dc67e6d334d238884121b9fa07e0`；日志 SHA256 `d0bdbd8a6c2c40e6e0944b970d06d84e1cbb3e664ea01e2adae8ec7f20b69b4b`。上述私有相对路径以服务器访问工作目录 `family-dashboard-access` 为根。
- 使用真实临时 Flask／SQLite 和双连接 WAL 写入。覆盖独立修改／删除、完整关联集合与工作流版本、规范化期间并发修改、同快照详情、读取后撤权／过期／认证版本变化、旧会话兼容及电视只读边界。
- 草稿版本表随预览提交，不能用发送前 GET 的新版本替换旧草稿来源；源发生变化返回 `409 stale_edit_source`。既有 apply 的事务和回执规则保留。
- 没有新增路由、表或迁移。旧客户端不提交版本表时保持兼容；新版同时要求 v2 和 `editSourceSnapshot` 能力。

接口及限制见 [快照契约](EXPO-JOURNEY-SEGMENTS-API.md)。这些测试不代表新页面已经通过浏览器、生产或本人真实账号验收。

## 交叉审查与待验事项

UI 初版 `5ecfe697773bbc9276827ef9cc44b4a7cd599c0c` 及负责人显示修正 `60f0975f4a0b166797cfa33e148b44bff435cded` 均经模型作者独立审查；公共接线 `53dbacde26ed27c901ea101160e8a4a884d59a64` 经后端作者独立审查。

模型审查发现的清单恢复、关联标识错配及日程负责人兼容问题已修复。固定模型 `7cf14b67ecdf7a364d9f276dda0b3b9eacd2c2e8` 经 UI 作者独立复审；对固定 API `6c9261e…` 的真实临时 DTO 专项 **21/21 通过**，strict TypeScript 通过，前后模型／测试及后端字节保持。原件 `worktrees/expo-journey-segments-model/test-results/segments-model-20260917T115849665330Z/result.json`，SHA256 `0d8b686b0981b8b94c84f13e5b4597c07afa55090b2d4c55f3722238395972f3`；Node stdout SHA256 `a1b84a468bb029d040d27b4f5231c568b9b980cd77d345fe51ad8d6da134e5a7`。

目前完整计划接口无法无损表达「已单独删除清单项」「清空准备截止日」或「实际关联标识已改变」的来源差异。新版分段编辑对此明确拒绝并提示核对；不会替用户重建、补回日期或恢复关联。合法的完整计划解除关联仍可编辑。后续部分更新协议应改善这一限制，本批没有修改 apply。

初次组合 `6bb3d95a…` 的全量 typecheck 失败：应用配置包含 Node 测试，却没有 Node 类型上下文。最终修订 `8dc33cdbac58c440e54fc8be90219d99fc0feac2` 经独立审查，保留应用原排除项并增加测试目录；新增独立测试配置及 `node frontend/typecheck.mjs` 入口，顺序检查应用和测试，任一步失败即退出。`package.json` 和 lock 均与父版原字节相同，没有弱化发布守卫、屏蔽诊断或安装新依赖。

组合 `d415e8f8e373c9f4c5ba2b0ca47ae4903d9d0e8b` 实际执行完整入口退出 0；日志 `expo-segments-types-r3/typecheck.log` SHA256 `5de7fdf3acb96f57de6e3319f22ee4da8982640c7695db6ae2c47a6080a68043`。此前 R2 的相同两套配置也通过，R1 原失败输出保留在任务执行记录；不重复计算通过数。

新构建器经独立审查并已实际执行成功：固定 Git commit 批量读取 180 个输入，保留 HEAD、工作树、依赖目录、逐文件 SHA 和导出守卫。R1 构建源为上述 `d415e8f8…`，树 `123af12d9be8d430a0543163154345211397e68b`，Node v24.19.0／npm 11.17.0，23 个导出文件；`expo-segments-build-20260917-r1/build-evidence.json` SHA256 `c7248a60b646b2cd168956c0102982d7a35dfc80780f2b26e420c5c4acaf320a`。浏览器入口为 `entry-213b6fc45acd2bc370adcfe3e28f9158.js`。

同一固定源码实际收集到发布所需 11 个 Python 模块、259 个唯一用例；`expo-segments-validation-20260917-r1/collection.json` SHA256 `a4112edd11be6ddade6fed46f1293290b133e5691fcaa7520d15a4d3a9079e7d`。日志与源码前后散列核对通过。**收集不执行用例，不代表 Linux 已通过 259 项。**

固定浏览器脚本 `42a9c190f86c48d1a24c0b21271c6adcf299622a` 经 Root 独立审查，对上述冻结导出实际运行 **15/15 通过**，产出 19 张截图。覆盖正常编辑保存与重启、跨时区／夏令时、并发核对、原操作未知结果恢复、成功后详情读取失败、身份／离线边界及地图／助理返回。真实临时 Flask／SQLite、成员登录及实际 API 响应故障注入；未伪造成功业务 DTO。源码 623 文件与导出 23 文件前后保持，工作树干净，15 套临时数据均清理，页面错误及外部请求均为零。

原报告 `worktrees/expo-journey-segments-browser/test-results/expo-segments-20260917T121539413077Z/result.json` SHA256 `d97ceaaa1cc2314cf59a32bce3aeb8dfb5fe0535786c18e8139f55eb047fbcb4`；完整 stdout SHA256 `de211adecf2f669e5d83bc91cbbc9cd72178c5fd1309b111b0ddaec2e1939ea0`。报告绑定构建 `c7248a60…` 及源码 `d415e8f8…`，不是生产或真实云测试。

19 张原图均由浏览器审查者逐张实际查看；320 像素首图的航班号标签重叠另做单一真实 fixture 探针，不重跑 15 组、不改源码或原报告。几何采样显示标签约 136 毫秒后自然上浮并连续六次稳定，稳定截图无重叠，确认为 Paper 动画过渡帧。`expo-segments-320-probe-20260917T122743422848Z/result.json` SHA256 `e227951ee54fde868c536468198d4287ff32f21b0a656f2edecbaa70c4a97fb8`，新图 SHA256 `c25ea97806cd1a4fb6bc80abfd6493a603f9e5cc6a629aad1b1d3c244d75753a`。同一源码／导出前后不变且临时数据清理；当前截图可见区域没有剩余视觉阻断，不扩大为完整表单、实体手机／电视或全面无障碍验收。

生产发布还须绑定当时实际父版本、经过审查的部署工具和实际 Linux 结果，验证 55→55 原数据保全以及 HTTPS 读回。不得重放上一批固定发布工具，也不得以本页的开发结果宣称已部署。

## 发布来源选择修正

R1 的实际 freeze 已建立，但生成器在创建输出目录前拒绝：`Required new trip modules missing`。父选择器漏选了构建的三个来源文件，不能满足完整 180 项输入校验；当时没有生成生产工具、绑定或远程操作。原 freeze 与任务失败记录保留。

适配器修订 `3b1e328e… → 6f038bb8710e38d974dbb158f61f605e32a9e6a6` 经非作者审查，只为生成的来源选择器明确增加已跟踪的 `frontend/tests/journeySegments.test.ts`、`frontend/tsconfig.tests.json`、`frontend/typecheck.mjs`。它们归档供复现构建使用，不在 Python 镜像执行 Node 测试；完整输入校验、全局白名单、Docker 及原数据保全守卫保持。新增保护测试后，实际 26 项通过，报告和真实父选择器检查见 [发布适配器](EXPO-JOURNEY-SEGMENTS-RELEASE.md)。

修订后源码 `e7243789f6ad79702318f58bbbb0b0a491d018cf` 重新实际收集到 **261 个唯一用例、11 个模块**；`expo-segments-validation-20260917-r2/collection.json` SHA256 `06cd88754afd8f02255235a10a3f23ce887ca1726d2438d859d93e0c663a3346`，退出 0，源码前后不变。此项仍仅收集，不表示 Linux 已通过；R1 的 259 项留作历史，不相加。

本次不重跑已通过的浏览器或 Expo 构建：应用、实际夹具及导出输入均未改变。经独立审查的私有 freeze r2 对唯一的离线部署适配器绑定旧 SHA256 `fa4f42b89147e1e316cb1f167e1bca1529c6b3bcde150adc83d258f613f8552d` 与新 SHA256 `afe37c0e671ea20d0da6626c99eea758df1448ccfb21d2f6ea1db79aaf4acb84`；其余可执行来源、实际夹具和导出仍逐字节保持，新 Python 输入则绑定 R2 收集证据。三个增加的归档来源已在原浏览器完整跟踪散列和原 180 个构建输入中核验。
