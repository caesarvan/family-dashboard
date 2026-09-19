# 日程重叠：本地真实浏览器工具

本工具只准备本地验证，不代表流程已经通过、真实云授权或生产部署。使用冻结源码、新 Expo 导出、独立短临时目录和 Edge；源码、bundle、导入夹具的实际路径与前后哈希均绑定。核心 GET／PATCH／偏好写入通过真实 Flask／SQLite，不伪造成功 DTO。同步只读记录是新临时库的初始合成投影，不证明任何 provider 的导入行为。

## 三条独立流程

| case | 范围 | 截图 |
| --- | --- | --- |
| home_edit_resolve | 390：首页本周重叠入口，点选一天不缩小范围；展开全文、修改原本地安排、真实 PATCH 与原 revision +1、刷新后消解，无新增副本 | 2 |
| ranges_focus_readonly | 1280：本周／前后 3 天与成员侧重；跨日一组的两个实际时段，紧凑偏好和每次三组分页；同步只读及完整长标题，事件数据不变 | 3 |
| draft_identity | 390：真实竞争更新触发 409，保留输入和原范围；真实离线保存保留锁定草稿且数据库不变；延迟返回原 state 时切换成员，隐藏旧草稿并使用新关注范围 | 3 |

浏览器显示时钟固定到北京时间 2027-10-13 中午；定时器继续正常运行。每条场景使用自己的临时 HTTPS 应用／库组，结束验证监听器与临时目录清理。输出保留 HTTP 请求及真实响应、SQLite 前后状态、失败现场、截图、实际 body 横向溢出指标及展开长文本高度。失败不会覆盖旧轮次；结果明确记录本轮所选 case，单项通过不写成全部三项通过。

## 执行

先由非作者审查工具及其小测试，再由集成人给出固定 source head、build source head 和新 build-evidence SHA；未提供这些身份前不运行产品浏览器。使用 `python -B -X utf8`，不允许优化禁用 assert。Windows bundle 传入 `\\?\` 开头的绝对路径，temp-root 用已存在的本机短目录。

```powershell
python -B -X utf8 scripts/check_expo_calendar_conflicts_browser.py `
  --source-root <本次冻结checkout> --expected-head <本次完整HEAD> `
  --build-source-head <新导出完整HEAD> `
  --bundle <新导出web的扩展绝对路径> `
  --expected-build-evidence <新导出证据SHA256> --temp-root C:/tmp
```

默认只运行上述三项。失败后可加 `--case draft_identity` 定向再验，必要时重复 `--case`，工具按实际选择计算流程和截图数量。源码 checkout 必须干净，harness 必须从该 checkout 导入；build source 必须是祖先、完整 frontend tree 和全部记录输入必须相同。只允许本工具／小测试／本文三条路径作为导出后的后代增量；不得借此复用改变产品或后端后的旧导出。

新结果位于本次 checkout 的 ignored `test-results/expo-calendar-conflicts-<UTC>/result.json`；目录独占创建，不覆盖原件。真实模型／provider 被阻断，浏览器与 Python socket 仅允许 loopback，没有生产或真实账户配置。原夹具的安全测试保持；新增工具测试仅核场景选择、独占输出和严格构建复用边界，不声称业务浏览器成功。没有 SSH、真实云或实体电视验收。
