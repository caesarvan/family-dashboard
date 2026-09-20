# 本地日程隐私：使用与发布验收

<a id="calendar-privacy-release"></a>

## 当前状态

2026-09-20 10:11:17（北京时间）激活成功，10:18:48 独立生产只读审计通过。源码经 [PR #17](https://github.com/caesarvan/family-dashboard/pull/17) 合入 main `a6c0c39a75efcb456aa39e19a941e7cc182ab048`，与实际安装 source 同树。后续纯文档提交不改变运行包。

本批为新建本地日程增加默认私密和明确共享；生产家庭库保持 71 表、平台注册库保持 9 表，没有 DDL、历史日程回填或云端写入。部署计划已消费，不得重放。

## 怎样使用

1. 从首页或日程页添加安排，填写标题、时间和地点；可见范围默认「仅自己」。负责人表示参与者，改为伴侣也不会把私人日程交给伴侣。
2. 需要共同查看时，明确选择「家庭共享」并保存。家庭成员和已配对电视才能看到这类新日程；其他成员可以协作编辑普通字段或删除，不能改变可见范围。
3. 创建者可编辑原日程，将范围改回「仅自己」。服务器在后续读取、写入、助理搜索和导出时核对当前权限；界面收到撤回结果后隐藏旧详情。

旧记录缺少全部隐私字段时继续原家庭共享行为，不推断历史创建者。已明确选择的云日历来源、旅行派生日程保持原授权和编辑方式。本批没有新增“云来源只同步给自己”模式，也不会修改原日历应用里的共享设置。ICS 新导入默认私人，重复导入不占有其他人的私人安排或改变原范围。

身份无法确认、离线或切到后台时，首页和日程中的标题、数量、工作量及编辑器暂时隐藏；同一身份核对成功后恢复草稿。身份改变则丢弃旧身份草稿。业务 404 后的旧编辑快照不会因同 ID 再次出现而恢复；写入结果不明时先核对，不自动再写一次。

## 实际验证与边界

| 范围 | 已取得的证据 |
| --- | --- |
| 后端 | 43 个唯一用例分轮通过：25 个隐私专项及 18 个日程、助理、导出邻域用例；真实临时 Flask／SQLite、合成成员及配对电视会话，网络阻断 |
| 正式前端构建 | 独立 fresh 安装、两组 TypeScript、55 项 Node 通过；141 个前端输入、9 个辅助输入与 23 个导出文件固定 |
| 真实临时浏览器 | R1 的撤共享／切身份与身份失败／草稿恢复两项通过；R4 仅补验私人创建→明确共享→收回，1/1 通过，3 张截图；三条流程分段覆盖，不能记成一次 3/3 |
| 浏览器修正记录 | R1 首项在末尾 audit 键断言失败；R2 首项功能通过但浮动标签重叠；工具修正冻结时钟后 R3 因等待表达式触发 CSP 而失败，未保存业务变更；R4 使用函数形式等待，不放宽 CSP，标签位置及实际 CRUD 均通过。全部原件保留 |
| 发布适配 | 27 个唯一用例分两轮通过：首轮 26 通过、1 项夹具数量假设失败；只修正夹具预期后窄重验通过。含真实临时两户三库备份、非空数据与 app 重启保全 |
| 实际 Linux 镜像 | 固定选择的 43/43 通过、零失败／错误／跳过；实际镜像运行文件和测试原件经非作者独立审查 |
| 生产只读审计 | 1059 个安装文件、三个应用服务各 130 个运行文件匹配；四服务运行、零重启、app healthy；75 个正常 TLS 静态资源、三个入口及 29＋3 项匿名 GET 拒绝分别核对 |

R4 实际创建及两次修改始终使用同一 ID，revision 为 1→2→3；数据库为一次创建、两次更新。配对电视会话的权限检查不能代替实体电视显示。Linux、浏览器、发布工具及生产检查各自保留范围，不相加为一轮全量测试。

**A–D 本人完整验收仍为 0/4。** 真实云写入、本人完整使用链和实体电视尚未完成；视频仍在独立候选中，不包含在本批安装包。

## 固定发布身份

| 项目 | 值 |
| --- | --- |
| source | `8d3e6376a606155ff66a0388e43d04cb7562fe9f` |
| tree | `2a94ee86f2c5fbc3bbbe0d62bea4ffa5c0b04601` |
| package | `c8c627cacbf16f6616c7f99c7d2de9bbc528775e67f9c59321649c19df2912dd` |
| manifest | `83ff8610c85eccf9dfc5e9dac788d2704543e8dc68d937e1463fbf7819add5c1` |
| archive | `c5d7cbaf30ad39a0b614bfad57689a2d36c37691ba036e906156231ad482cc0a` |
| image | `sha256:a783c58c882748d273c5956e2d94a43c99261c61c6b41f0489118d9fd96f6654` |
| plan（已消费） | `30723643983b2803c20459e89e9ffc5f7dd6ccd5308c475304f621b8512fc683` |
| stage | `4c13324f4b596b60e6e45a11281d4e0d1c9b02407998211b86a5036f8a16679f` |
| activation | `907149ff3773daac7e643f40ace186edb57c4f6c1f9ab8cad3d3c04c13653333` |
| 实际 Linux build | `cf81b0fccfd19e840708e4feb192707cc19818f56a42233af6736685e41a0d02` |
| 实际 Linux validation | `72f683910e7c5a87fe0ce3af0dd7aea1cb99b5d66b13962ffc43519d2eb0aa30` |
| 独立生产只读审计 | `5f8d8f22e4924c0905c7313d8ace6cef5ad9f66ec594cd21dc3715df1c57ff12` |

父版为[日程时间重叠](CALENDAR-CONFLICTS-ACCEPTANCE.md#calendar-conflicts-release)。本批共 107 个非 Expo 运行文件：更新 `app.py`、`home_assistant.py`、`data_portability.py`，新增 `calendar_privacy.py`，其余 103 个逐字节保持。Docker COPY 增加隐私模块；依赖、Compose、Nginx、环境及成员标记保持，38 个发布 operator 由正式包绑定。

实际一户两库在停写／app-only 窗口内完整保持 71→71／9→9，全部表、settings、序列、提醒状态及回执均比较。窗口前后逻辑摘要同为 `e8d0fc050c826f9af3106c14b6a5c436ddfd69e769526d7f5b269fde9ae553dd`。这不限制恢复服务后的正常同步和用户写入。两份停机备份字节已核对，备份定时器 active；未在生产执行恢复。匿名 GET 返回 401 只证明该读取被拒绝，不代替 POST 授权或本人业务流程。

## 交接与原件

后端合同见[本地日程权限](CALENDAR-PRIVACY.md)，前端及恢复见[可见范围](EXPO-CALENDAR-PRIVACY.md)，工具见[浏览器验证](EXPO-CALENDAR-PRIVACY-BROWSER.md)和[发布适配](CALENDAR-PRIVACY-RELEASE.md)。后续开发继续独立分支／worktree、非作者审查、integration 组合核对及 PR 合入。Git 推送不自动部署。

操作机证据根目录为 `C:/Users/caesarf/Documents/Codex/family-dashboard-access/`：

- 固定包、绑定及唯一 assemble／stage／activate 原件：`calendar-privacy-release-20260920-r1/`。
- 正式构建：`worktrees/calendar-privacy-build-r1/test-results/expo-calendar-privacy-build-r1/`。
- 浏览器 R1–R4、Linux 固定输入及实际原件：`worktrees/calendar-privacy-browser-r1/test-results/`。
- 组合源码／绑定／具体计划／Linux 独审，以及本次生产只读审计：`worktrees/calendar-conflicts-release/test-results/`；生产结果位于其中的 `calendar-privacy-production-audit-bound-r1/calendar-privacy-production-readonly-r1.result.json`。

原件留在操作机，截图、日志、环境与数据库不进入 Git。服务器已消费候选为 `/opt/family-dashboard-candidates/calendar-privacy-71-20260920-r1`，保留的发布目录为 `/opt/family-dashboard-releases/calendar-privacy-71-20260920T020935661346Z`；后续发布必须重新核对实际安装身份并生成新计划。
