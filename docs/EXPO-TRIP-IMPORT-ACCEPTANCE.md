# 旅行 JSON 导入：验收与发布记录

## 当前状态与入口

**已于 2026-09-18 04:42:28（北京时间）激活，04:43:27 正常 TLS 读回、04:45:06 独立只读检查通过，04:52:12 完成独立语义审计。** 下表记录实际安装身份；后续纯文档提交不改变该运行包。

入口为「旅行 → 导入旅行」。选择 JSON 文件或粘贴内容，核对服务端预览后明确创建；保存成功后读取当前旅行详情。支持两版示例、准备事项、采购、目的地和行程分段，金额未知与零分别保留。操作与恢复见[使用说明](EXPO-TRIP-IMPORT.md)，事务内会话检查见[后端契约](JOURNEY-IMPORT-SESSIONS.md)。不自动创建云日历事件。

<a id="expo-trip-import-release"></a>
## 发布身份

| 项目 | 本轮固定记录 |
|---|---|
| main | `eda8632719a6f1a3202e6d5c2a9a986329c9c287` |
| source／integration | `cbd0c6756da83699307683cb0541b26adf3d77d8` |
| tree | `f402fd307d392732cbc3b6d592b7d8abaf47113e` |
| 本地 R2 组合 | `fce37351dc18ac8b73f095682f3a42d6c1e3bad0`，与上述 tree 相同 |
| app／sync／media 镜像 | `sha256:578142cb4d209d573ee0c54408d9494833ec49a74df1c5647a403e47ec5a72c1` |
| archive SHA256 | `0206b70e83f111fc99431c6021096e90d29cad15787c15788ba8022540c677e4` |
| manifest SHA256 | `79679fa35c8a1ca234c38f26d277150797c1e6ad445d5843d19cde7bfc6fc5a3` |
| 包文件 | 733 项：710 个选中源文件与 23 个 Expo 导出文件 |
| Linux 执行 | 12 模块、288 项＝287 通过＋1 精确 Windows junction 跳过；0 failure／error／deselected，370.428 秒；115 个运行文件、38 个已加载模块前后一致 |
| 数据库 | 58→58，无 DDL；实际 1 户、2 库停写备份，原 58 表行／schema／序列与平台注册库在新 app 启动核对时保持 |
| 读回 | 733 个包文件、115 个运行文件、75 个 HTTPS 静态文件核对；24 个生成文件与 1 个退役资源禁止公开访问 |
| 权限与运行 | 37 个唯一匿名 URL 均 401；四服务 running、0 次重启；仅 app 有健康探针且 healthy，其他 health 为 null；环境保持且权限 0600 |

发布目录 `/opt/family-dashboard-releases/expo-trip-import-58-20260917T204131765553Z`。停写备份前与新 app 启动后的完整快照 SHA 相同：`aacb38bbbc9bf4d924fa6a55e4438e27e111754c4450502396328a72d2b629ef`。后置新备份服务为 `success`、timer 为 `active`；该次是逐库在线备份，不是跨库原子快照，也没有再次核对 live 全组快照。运行恢复后的在线备份与停写时的完整组保全分别记录。

独立审查者 `expo_finance_acceptance` 核对八份下载原件的远端两次及本地 SHA、五阶段报告与捕获 stdout JSON 一致，并确认 JUnit 的 288 个唯一节点与收集集合完全相同。保全依据已审算子的完整比较报告及 before／after-app／post 散列链，未额外下载数据库或原 proof 正文，没有重放发布、测试或备份。

生成、打包、绑定和部署是独立步骤。九份实际生成工具经非作者审查后绑定；阶段输出保留原件，失败时不得重放旧命令或覆盖已有证据。发布工具见[适配器说明](EXPO-TRIP-IMPORT-RELEASE.md)。

## 已完成的本地验证

| 范围 | 实际结果 |
|---|---|
| 完整类型检查 | `frontend/typecheck.mjs` 检查应用与测试两个配置，退出 0 |
| Web 构建 | R2 实际导出；193 个构建输入、23 个导出文件 |
| 浏览器 | R2 12／12 通过，12 张截图；711 个 tracked 源文件、导出及六项真实 fixture 前后保持 |
| 浏览器清理 | 12 份临时 fixture 均清理；0 页面错误、0 外网请求、0 生产写入 |
| 视觉 | Root 逐张查看 12 张图；320／390／1280／1920 宽度、浅深色、长标题与键盘场景，可见视口通过 |
| Node 模型 | 13 项通过；执行在 R1 组合，R2 只修改入口按钮标签和高度，模型与后端字节保持 |
| 发布适配器 | 8 项 pytest 通过；122 次输入篡改、5 个未绑定阶段入口均被拒绝 |
| Linux 收集 | 12 模块、288 个唯一测试；这是收集数，执行结果单独记录 |

浏览器包括文件／粘贴、默认字段与显式空集合、真实 DST 错误、重复请求、结果未知、过期后回执恢复、父页面详情读取失败、身份变化与迟到响应、离线、导航和权限场景。合成数据通过真实临时 Flask／SQLite 保存；成功业务响应没有替换成固定 DTO。

R1 浏览器在共同入口的精确可访问名称匹配处失败：7 组遇到同一失败，第 8 组中断，另 4 组未开始，没有通过组；不是完整运行的 12 个失败。修正按钮可访问名称与至少 44px 高度后，R2 独立完成全部 12 组。R1 中断没有执行最终清理，临时目录清理状态未确认，原件保留。

后端作者验证分轮进行：首轮 192 项中 190 通过、2 项测试时钟构造错误；只修正新增测试的时钟后，两项补验通过。不能将分轮结果写成一次 192 项全过；本轮 Linux 执行另有独立证据。

## 证据索引与边界

私有根 `A` 为项目交接目录 `family-dashboard-access`；`W` 为其 `worktrees` 子目录。原件不提交 Git，不含真实业务输入。

- 最终冻结：`A/expo-trip-import-freeze-20260918-r1.json`，SHA `83780362ff72dad0a3ef5b174d594bacfbd889dfc9ad64ce5f37709f9b99a978`。
- 组合独立审查：`A/expo-trip-import-combination-review-20260918-r2.json`，SHA `e107543f7cbb03e7f4e4f719c394ab848c175d8fe452e3dd240a0817983c3ec3`。
- 构建：`A/expo-trip-import-build-20260918-r2/build-evidence.json`，SHA `df7ba17e84442bc5c2dafdf364ea23542631cdf588a3cff61d2c8af403e1d47a`。
- 浏览器：`W/expo-trip-import-browser/test-results/expo-trip-import-20260917T193539706020Z/result.json`，SHA `8aa2e4296fa6c66b7885367e026c12a99dc290d82ea0be5f2329c43aaab811a0`；同目录 `visual-review.json` SHA `c133c8091d2f5d2b5fcf5cf67226404234e6f7ab022f0840c5ebc02702114a28`。
- 实际工具审查：`A/expo-trip-import-tools-20260918-r1/operator-review-record.json`，SHA `917e2c74d8f2d5a8611d24d5d6b316f631dd1fa62d9caecfd933de70d4cf591b`；绑定 SHA `39cc43c88ddbe954f102d88af345e0befe5b044e0a20564c41ebe0e0bb1a2d7d`。
- 发布后独立审计：`A/expo-trip-import-published-audit-20260918-r1/audit.json`，SHA `14c9cb4ddf2634d285218667efd445ae31d7c2130646b7850cccea41105a596c`；同目录 `fresh-readback.stdout` SHA `0abcff792a28069d37675ef38e9b6ef1d216b854160bf98567ff1b8a110222e4`。八份服务器原件在其 `remote-evidence/`。

原生操作系统文件选择框、本人真实文件、在线 AI、真实云写入及实体电视未在本轮验收。图片审查仅覆盖实际可见区域，不代表全量展开内容或完整无障碍认证。另一个同一旅行连续流程验收候选不在本轮发布包内，也不计入这 12 组或场景 A 整体通过。
