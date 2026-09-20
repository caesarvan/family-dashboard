# 本人确认照片日期：真实浏览器验收工具

本工具已完成两条流程的分轮验证。R1 在组合 `75a79cd729ae339eabccd9f10cd5e8991142562f` 和对应正式 Expo 导出运行：手机通过，桌面因工具把同家庭伙伴无权修改的正确 `403 forbidden` 误期望为 `404` 而失败，整轮仍保留失败。仅修工具后，R2 在 `90d97ba4037b45281cda10395b41aeceec0b4c52` 使用同一正式导出，单独补跑桌面通过。具体原件、错误调用与上线边界见[集中验收](MEDIA-CONFIRMED-DATE-ACCEPTANCE.md#media-date-release)；不把两轮相加为一次全量。契约见 [MEDIA-CONFIRMED-DATE.md](MEDIA-CONFIRMED-DATE.md)。工具原基线为 `c8d8ed0800a81f9b200599d8e7a9155c2902aa00`。

入口：[tests/browser_media_confirmed_date_check.py](../tests/browser_media_confirmed_date_check.py)。仅新增此入口与本文；复用原设备照片 Run、真实 Flask／SQLite／HTTPS 登录与文件选择、限时请求完成等待、照片建议创建／配对、截图几何检查、HTTP 5xx 守卫和临时目录收尾。没有修改公共夹具或业务代码，不构造成功业务 DTO。

## 两个独立流程

| `--case` | 实际验收目标 | 宽度／截图 |
|---|---|---|
| `upload_date_journey_memories` | 真实设备文件选择 → raw 上传／净化加密 → 明确私密确认 → 原 ID 单独保存日期 → 重载 → 按本人日期获取旅行建议并明确确认原旅行 → 那年今日打开原 ID；上海午夜后移出当前回忆 | 390／3 |
| `lost_conflict_identity_clear` | 真实日期 PATCH 已提交后丢弃响应 → GET 核对不重写；真实竞争日期保存导致旧 revision 409，保留草稿，核对后明确恢复当前值；迟到原本人 GET 在真实成员切换后不能安装；清除日期退出建议／回忆而保留已经关联的旅行 | 1280／3 |

第二条用真实 API 建立另一家庭和合成电视配对／授权，核非本人不返回日期字段、同家庭伙伴日期写返回 403、另一家庭读写返回 404、电视写返回 403。照片共享和非空电视授权在日期保存／清除前后保持；这不代表实体电视验收。晚响应先从真实服务端取得本人结果，再真实登录另一成员，最后交付原响应；等待页面自己的 `/me` 与新账户菜单，并以 MutationObserver 检查旧日期编辑器没有重新安装。不得用“面板本来为空”代替完成信号。

日期取实际 v2 `referenceDate` 派生。仅向 `MediaLibrary.clock` 注入合成 `2024-02-29`，分别选择合法往年闰日 `2020-02-29`／`2016-02-29`；不用减一年产生非法 2 月 29 日。第一条将服务器时刻从上海 2 月 29 日 23:59:59 推至 3 月 1 日 00:00:00，触发既有隐藏／恢复读取并核原照片移出回忆。使用过去的合成时钟避免把真实刚配对的临时设备凭证人为推进到过期；浏览器 Date／动画和身份会话时钟不冻结。没有把日期转为 UTC 拍摄时刻，也不修改未知来源日期。

## 保全与失败证据

每次日期提交都核原照片 revision 恰加一、仅日期元数据变更；原行其他列（含净化密文）、去除日期后的全部元数据、旅行记录、导入记录、共享范围及电视授权摘要相同。只单独核 `settings.meta.revision` 与一条 `media_item_update` audit 恰加一，其他 settings 全部保持。恢复 GET 核原行／audit 不变、无新增 PATCH；同日期状态不是原请求回执。

真实响应及等待阶段使用独占 JSON，先写盘再丢弃响应或断言。实际服务端方法／路径／query／状态另写 `server-http.jsonl`；浏览器 context 监听所有页面响应，**任何 HTTP 5xx 均失败**，不启用旧坏预览夹具的例外。原文件和净化展示副本只记录散列，不输出密钥或原图；全部内容与家庭均为虚构夹具。

每条流程拥有新临时目录／数据库；继承已审 lifecycle，等待请求线程结束并关闭监听、SQLite 连接使用显式 closing。仅向父 runner 临时注入本工具两个 case 的截图计数，不改其文件或既有 case。失败记录 traceback、已有 HTTP／数据库摘要和可取得的截图，不能把已打印业务 PASS 当清理成功。每次运行新建结果目录；原失败不覆盖，必要修正经审查后仅明确选中受影响 case。

## 固定输入与运行

集成人使用实际完整提交、正式构建 SHA 与绝对目录替换参数；以下仅为待执行形式：

```text
python -B -X utf8 tests/browser_media_confirmed_date_check.py --source-root <固定源码目录> --expected-head <完整提交> --bundle <正式导出的web目录> --expected-build-evidence <build-evidence.json的SHA256> --temp-root <独占临时父目录>
```

支持重复 `--case`，默认两条；选择列表去重。默认要求构建提交等于运行提交。仅工具修正时可明确加 `--build-source-head <原构建完整提交>`：原构建必须是运行提交的祖先，两者以禁用 rename 检测的 Git diff 核对，差异路径只能是本工具与本文档；任何业务、前端或其他夹具变化均拒绝。构建证据的 sourceHead／sourceTree 必须匹配原构建 commit 自身，源码干净、完整 frontend／supplemental／additional inputs 与 23 个实际导出仍逐字节匹配，不能改写构建证据冒充新构建。报告分别保留 sourceHead、buildSourceHead、buildSourceTree 与 buildReusePaths。前后保存全部跟踪文件／导出／实际加载夹具散列；禁止使用浮动源码或替换 bundle。`-B` 必需，`-O` 明确拒绝。

R2 补验仅选择 `--case lost_conflict_identity_clear`，明确 `--build-source-head 75a79cd729ae339eabccd9f10cd5e8991142562f`，运行 head 为上述 `90d97ba`，继续使用 R1 的正式 bundle 和构建证据 SHA。手机 R1 通过与桌面补验分别记载，不相加为同一轮两条通过。

结果为源码目录 `test-results/media-confirmed-date-<UTC>/result.json`，另含执行脚本快照、各 case 独占原件与预期总共 6 张截图。所有等待使用原有 15 秒有界请求完成／响应或 UI／身份完成条件，不调用无期限 `Response.finished()`，不插入固定 sleep。禁止云、模型及非本地网络；本机允许临时自签 HTTPS，不能把它写成生产 TLS 验证。组合尚未完成时只做 AST、差异和本地链接检查，不启动预期失败的业务测试。
