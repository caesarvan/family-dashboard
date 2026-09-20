# 重复照片提示浏览器验收工具

本工具尚未执行正式浏览器。它只检查本人已保存静态照片的跨来源展示副本是否一致，不核验原图、视觉近似或视频，不自动删除、合并或分享。

## 固定输入与执行

集成人先将已审 API、UI 与本工具合入干净组合，再对该**完全相同的 HEAD/tree** fresh 构建 Expo。工具要求 `build-evidence.json` 的成功阶段、未注入 Expo 公开环境变量、禁用 dotenv、完整 frontend 输入（仅排除 README/LICENSE/.gitignore）、九个既有补充输入及全部导出 SHA 与当前文件一致。没有旧构建复用或任意源码差异白名单。

```powershell
& '<Python>' -B -X utf8 scripts/check_expo_photo_duplicates_browser.py `
  --source-root '<冻结组合工作树>' --expected-head '<完整40位HEAD>' `
  --bundle '\\?\C:\<正式fresh构建>\web' `
  --expected-build-evidence '<64位SHA256>' --temp-root 'C:\tmp'
```

必须使用 Python `-B`，禁止 `-O`。可重复指定 `--case`，严格去重且至少一个；默认三条。短临时目录必须预先存在且不是链接。输出是独占 `test-results/expo-photo-duplicates-<UTC>/`，保存实际 wrapper/harness、全仓与导出前后哈希、逐项 HTTP/数据库摘要、截图与失败记录；不会覆盖既有失败。

## 三条实际流程

| case | 预期截图 | 验收范围 |
| --- | --- | --- |
| `cross_source_pages` | 3 | 390px，本人 21 张 Google 来源照片及一张设备来源照片来自同一真实合成 JPEG。明确查找才发 GET；20 条分页、打开原 ID、返回原目标第二页且 fresh 读取；无业务写入。 |
| `coverage_and_draft` | 3 | 1280px，不同真实像素得到无匹配；1001 条历史密文照片覆盖原始 1000 条扫描上限，其中一项缺历史指纹；显示部分覆盖而非全库结论。原详情的未保存说明在取消离开后仍保留，无 PATCH。 |
| `identity_and_revocation` | 4 | 真实成员、第二家庭及配对 TV 的权限拒绝；伙伴共享详情撤回后清除；离线隐藏；Google 来源实际 SQLite 撤权后仅元数据轮询清提示，无自动重复扫描；真实已授权响应延迟到重新登录后返回，旧身份结果不能显示。 |

Google 账户、Picker 选片清单及 worker 完成回调是明确标注的合成来源设置，JPEG 净化、加密存储、设备 raw PUT、确认保存与后续权限请求均使用原服务。两种来源先实际读取展示 JPEG 并比较字节；没有伪造不同哈希充当照片相等。历史上限 fixture 用同一真实加密展示副本、逐 ID 重新加密元数据，只有明确的一项删除历史指纹，不能视作真实 Google 导入或 1001 项真实上传验收。

浏览器使用正式 Expo 导出、Edge、回环 HTTPS/临时 Flask/SQLite。显式扫描/翻页/返回在操作前安装 15 秒 response 与 requestfinished 监听，要求同一真实请求完成后才读 JSON；不用无界 `Response.finished()`，不伪造成功 DTO。身份迟到场景仅暂存真实 GET 响应，再通过真实登录切换身份。所有外部 provider/model/非回环网络调用均禁止。每条独立数据库和服务，失败仍保留截图/阶段记录，关闭监听线程及临时目录。

## 离线检查与范围

`tests/test_expo_photo_duplicates_browser.py` 检查精确构建输入拒绝、独占输出、真实 Flask/SQLite 跨来源 JPEG/密文 fixture、历史上限数据及服务线程关闭；不会启动 Edge。离线通过不代表三条用户流程已通过。实际运行后只可按 `requestedCases`、真实退出码、截图及原件报告结论，真实账号、生产及实体电视仍需单独验收。
