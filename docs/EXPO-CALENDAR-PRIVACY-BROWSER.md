# 本地日程隐私：真实浏览器组合验证

这是验证工具，不是产品通过或发布回执。只有独立审查后的前后端组合、新 Expo 导出和本工具都固定后才可运行；作者分支基于 `ffb0b3cf46b6a4cf35b005d84879763b825cd822`，本身不含下一批隐私实现。工具仅新增三个文件，不修改原夹具、业务响应或产品源码。

## 三条流程

| case | 实际接缝与验收 | 截图 |
| --- | --- | --- |
| `private_share_revoke` | 手机真实表单新建默认 private、负责人为本人；两个真实成员会话及真实配对 TV 的 state 读权限；创建者明确共享、伙伴可读但 scope PATCH 被拒绝、创建者收回；同一个 ID、revision 1→2→3，DB 一次创建、两次编辑，无副本。 | 390 两张、1280 一张 |
| `withdrawal_identity` | 伙伴正在编辑时创建者收回，真实 state→尾部 me 完成后隐藏旧详情；伙伴 PATCH、助理搜索/brief、带共同记录 ZIP 导出都不含私有内容；故意延迟旧 state，切换成员后旧标题和草稿不能显示或产生写入。 | 1280 一张、390 一张 |
| `identity_failure_draft` | 仅将真实 me 的 200 传输响应替换为 404，实际 provider 未发业务 PATCH，草稿暂藏；本人明确核对后草稿和共享选择恢复；真实 offline 生命周期同样暂藏、恢复，无 DB 修改；最后实际删除原日程再发旧 PATCH 得到业务 404，旧详情关闭且不能复活，不重发。 | 390 三张 |

共 3 条／8 图。默认全跑；只补验失败流程时使用单独新输出和 `--case`，记录真实所选数量，不把一条补验称为全量通过。第三条 offline 检查是离线事件后阻止操作与恢复，未宣称业务 POST 已发送或远端结果未知。传输 404 不伪造业务成功；真实 CRUD、配对、数据库、搜索与导出从不替换。

复用既有 `browser_expo_finance_check.Run` 的临时 HTTPS Flask／SQLite、真实 Edge、登录与现场失败保全，复用 calendar conflicts 的安全 DOM 测量及 dependencies 的 HTTP／DB 证据。390/1280 检查实际 body/root 水平宽度与控件裁切，已有水平滚动祖先的严格边界保持。所有数据均为新临时合成家庭；TV 是真实配对会话的接口权限验证，不代替实体电视显示验收。

本工具在既有页面打开后，用带时区的 `NOW` datetime 调用 `page.clock.set_system_time`：保持合成日期并恢复时钟走时。继承的固定 `Date.now()` 会阻止 React Native Web 浮动标签动画完成；此处仅修正隐私工具的时钟，不修改共享夹具或产品样式。 每次打开实际断言 Date.now 跨帧推进且仍为合成日期；首条截图前等待地点标签几何位置移到输入文字区域上方，保存时钟和标签几何原件。

## 运行合同

由集成人提供完整冻结 source head、新 bundle 和 `build-evidence.json` SHA。Windows 为 bundle 使用 `\\?\` 绝对长路径，`--temp-root` 是现有短临时目录。使用 `python -B -X utf8`，禁止 `-O`。

```powershell
python -B -X utf8 scripts/check_expo_calendar_privacy_browser.py `
  --source-root '<本次冻结独立checkout>' --expected-head '<40位source>' `
  --bundle '\\?\C:\<本次导出>\web' --expected-build-evidence '<64位SHA>' `
  --temp-root 'C:/tmp'
```

只有 source 在 build source 之后且差异严格仅限本工具／测试／本文三个路径时，可指定 `--build-source-head` 复用同字节前端；整棵 frontend、输入 hash、23 导出等实际 build evidence 原件均核对。业务或其他工具变化不能通过这个例外。输出 `test-results/expo-calendar-privacy-<UTC>/` 必须独占，保留 result、实际执行工具副本、HTTP 请求／响应体、DB/audit、截图、ZIP hash、失败和前后源码／导出 hashes；每条独立临时库，执行后关闭监听和清理临时数据。原失败不可覆盖或自动重跑。

仅回环网络；云／模型入口明确阻断，浏览器外部请求亦阻断并作为失败。没有真实账户、生产、云、模型、SSH、安装或构建操作。工具测试只验证新 case 选择、独占输出及三文件复用边界；正式浏览器另待授权及新构建，不能用 helper 测试替代。
