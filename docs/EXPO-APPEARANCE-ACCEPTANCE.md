# Expo 成员外观验收与发布

<a id="expo-appearance-release"></a>

**已于 2026-09-17 16:17:28（北京时间）激活，16:17:57 正常 TLS 读回通过。** 独立审计核对 13 份服务器原件及其哈希链，16:24:38 的安全读回仍与发布身份一致。使用步骤见 [成员外观](EXPO-APPEARANCE.md)，接口见 [成员偏好 API](MEMBER-PREFERENCES-API.md)，发布工具与历史输入见 [发布说明](EXPO-APPEARANCE-RELEASE.md)。

## 实际运行身份

| 项目 | 本次实际值 |
| --- | --- |
| main | `e5b12c33b325359dc7629e19bf8a4d0b95f9b2ca` |
| 正式 integration／source | `c75676222406a6845e0c8527f43ef99d0143454d` |
| 同树 | `81e170870848042bee9f6a5ad7e984d7b70fbe1c` |
| archive SHA256 | `4244790d034ae3602a6d734982165cdd7c6eb83962cdffc24a09a032ae0d2e65` |
| manifest SHA256 | `14374023ae120c9c3d6ddbe009c0f1b97a4ab845d104ce5bc7fd05b8de2cff11` |
| binding SHA256 | `cfdad76fd648e3b5859df6cb217f0fdef982e55964b747c4aceaef8643a77a7e` |
| app／sync／media 镜像 | `sha256:6c1650d84ecfdff6f46fc9358ddd332a11b1f812a95279d5621fb63735fc447e` |
| release | `/opt/family-dashboard-releases/expo-appearance-55-20260917T081628619801Z` |
| 文件核对 | manifest 595 项＝572 个源码文件＋23 个 Expo 导出；运行文件 114 项 |

此前 14:56 首页布局版本是本次升级基线；原证据仍保留。浏览器受验源码为 `61e82b48b6cd0f23d40366d9cb848ef2760d1a5b`、tree `ed30a40d893111d95cc1fa682c3dbd4876498d9a`。正式冻结核对全部可执行源码与该受验输入一致，仅文档可后续变化，没有发布工具豁免。本文等发布后文档另行提交，不改写上述运行身份或重打包。

## 验证范围

| 检查 | 实际结果与限制 |
| --- | --- |
| 偏好后端专项 | Windows 三模块 64 项通过；真实临时 SQLite 的会话撤销、事务锁、家庭隔离和 CAS，详见 API 文档。 |
| 前端模型／语法 | 最终 Node 40 项通过，已包含此前 29 项和 classic 11 项；完整 TypeScript 检查通过，tsc 仅保留当时终端记录。 |
| R1 浏览器 | 真实临时 Flask／SQLite／Edge 11／11 流程通过；572 源码和 23 导出前后相同，零页面错误和外网请求，夹具已清理。 |
| 视觉 | 17 张当前视口截图由验收作者逐张查看；协调者另看 3 张，所见范围无阻断。320／390／1280／1920 宽度；内部滚动区域没有完整覆盖。 |
| Linux 发布验证 | 九模块 227 项＝226 通过＋唯一精确 Windows junction 跳过，零失败／错误／取消选择；37 个加载模块、114 个运行文件在测试前后验证通过。 |

唯一跳过为 `tests.test_frontend_runtime.test_windows_junction_rejected`，原因 `Windows junction semantics`。此前 227 项 collection 只证明收集；实际执行以本次服务器 JUnit 为准。专项、模型、发布工具和 Linux 之间有重叠，不能累加为独立全套数量。

浏览器覆盖明确保存／跨端读取、伴侣／家庭／TV 隔离、409 保留差异后明确保存、真实提交丢回复后只读核对、导航锁、离线与后台草稿恢复、迟到响应和写后身份变化、classic CAS 与丢回复；也检查了深色账户／资金／持仓可读性。新面板按钮至少 44px，首页待办实际 44×44px，空格只产生一次 PATCH。既有日程范围按钮仍为 34px；日程／清单内部密度尚未全面接入。

本地原件相对私有 access 根目录：

- `worktrees/expo-appearance-integration/test-results/appearance-combined-node-r1.tap`，SHA256 `a47e2cc15fe2812d9373036006ffc3f94beeaa761b0474e1e943f041492842ad`。
- `expo-appearance-build-20260917-r1/build-evidence.json`，SHA256 `629010b284a31610589a98d18d663ee4e448e49876635cd9f6d28ad6b5d724a7`。
- `worktrees/expo-appearance-browser/test-results/expo-appearance-20260917T074803636982Z/result.json`，SHA256 `b81ecbdd6780d8016ee579446210a745be41bb09cf2873e9889f67945699ea9d`；同目录 `visual-review.json`，SHA256 `60e7ea4c3c7c46bbc175f752b0480684ff9a2d7e7afb8ae0f7f0af30cd0719c8`。

## 发布、保全及独立读回

打包、绑定、上传完成后，build、validate、stage、activate、post_readback 五阶段均一次退出 0。55→55 不执行迁移或 DDL；停写后完整备份实际 1 户、2 库。安装前与新 app 启动后的快照字节相同，原 55 张家庭表、两张平台注册表以及 rows／schema／sqlite_sequence 全部保持。生产持仓操作回执行数实际为 0，不把合成非空覆盖描述为生产非空回执验证。READY 中的 `productionWrites: 0` 仅指准备阶段，不能据此宣称整次激活没有生产操作。

正常 TLS 实际核对 75 个静态资源，拒绝 24 个生成内部资源和 1 个退役资源，25 个匿名 API 均返回 401。四服务均 running、重启数 0；app 的 health 为 healthy，其余服务未配置该健康值。环境保持，web 沿用原镜像。

post 触发新一次备份服务且成功、timer active；新 manifest `manifest-20260917T081752863401Z.json` 核对完整 1 户 2 库与 55 表结构，SHA256 `227edd1b273e83fd57b7ffd6b74c4995e2c133fe10a571352a4c2934801c596a`。它是每库独立 online backup，`liveGroupSnapshotRechecked=false`，不是跨库全局原子事务，也不是再次检查 live 全组快照。

13 份原件保存在私有 `expo-appearance-published-audit-20260917T081852106490Z/`：根目录五份阶段 JSON，`validation/` 三份原件，`proof/` 五份备份／保全报告。审查者只读取报告与安全状态，不下载数据库备份、不执行发布算子。以下均为取回原件的 SHA256，**不是 `*-command.stdout` 的哈希**：

| 原件 | SHA256 |
| --- | --- |
| `build.json` | `cb1c6f821a0caa8417d360f5a7c50bc7e8168eb499d8b1a5239074068467499f` |
| `validation.json` | `855ea98c956605cdb7fc08b1eea2084b19ce1222e0f0d54e3b78e16027d85b95` |
| `ready.json` | `7302155dcc92029abff1e3162546dabef47c497b41b20e500f29900091bfc63a` |
| `activation.json` | `53b032f449dc76cab23023c9eb0799167f45db150ec6cbc905de38e65a4ce10f` |
| `post-readback.json` | `73b01538d26bf8e48067cfd6b93799f65e5198239ad6c0141bf5da1cff0da8ea` |
| `validation/results.xml` | `e37a30b6ff5083f7c3560086f904a36df8339d030266912b7b99ed2a68bf499d` |
| `audit.json`（独立审计摘要） | `003e9c2ff644201019b8c5555ab36aafc0557d6e22e95c8d7b630043c036ff7a` |
| `readback.json`（独立读取） | `64b26ffa64d55098a1dda7c9594ff908ba8f5cc53a89fd19776f36d513adc25a` |

## 尚未验收

本轮没有真实云或模型调用，不把合成账户和本地浏览器算作本人公网新设置流程、原生安装或实体电视验收。用户暂不能测试实体电视；保留限制，不重复索要该操作。当前改进不等于全部 UI 或完整产品目标完成，后续优先补齐 34px 日程范围按钮与日程／清单内部间距。
