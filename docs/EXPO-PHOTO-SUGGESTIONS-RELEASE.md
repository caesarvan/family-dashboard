# 照片旅行建议发布适配器

此适配器尚未证明新版本已上线。它只在本地生成未绑定工具，正式发布须完成固定源码审查、实际构建与浏览器验收、冻结测试清单和数量、独立工具审查，再由集成负责人执行。

父版本是已发布 Trip Recap：应用镜像 `e7994bbca9f2b5d2116e1f8e1fb0db866c997be6477c89473983e9b125ece73b`，清单 SHA-256 `2504bf48bf4d6275958a1bd2fc0b54efde933d88b7f918c1856fe0a2b245ca77`。输入为私有 access 目录内 `expo-trip-recap-tools-20260918-r1` 的九份原始工具，逐份校验固定哈希，不复制旧操作绑定。

沿用 58 → 58 发布与全量数据保留校验，没有数据库迁移。除 `household_media.py` 外的 37 个后端文件、Dockerfile、依赖和数据库定义必须与父版本相同；该文件仅允许审过的会话校验修复，源码 SHA-256 固定为 `63f2116462f66a33f851720b76234ada4686cff90f769c66441ae6fc109463a1`。本地打包与服务器源码检查均执行此限制。

```powershell
python -B deploy/expo_photo_suggestions_release/prepare.py --source-root <absolute-private-access> --output <absolute-private-access>/expo-photo-suggestions-tools-<unique-attempt> --freeze <absolute-private-freeze.json>
python -B tests/test_expo_photo_suggestions_release.py --source-root <absolute-private-access>
```

第二条命令只在临时目录测试真实生成的冻结、源码和未绑定入口检查，并阻断进程与网络调用。测试使用的 `9991` 是故意构造的计数，不是正式验收数。正式清单包含九个指定测试模块，数量必须从最终源码实际收集；不接受凭估算填入。

继承的发布流程会停写、核对备份、验证全部表数据与结构，再更换源码并检查应用启动未改变原有数据。发布后还需检查实际 HTTPS 资源、匿名访问边界、四个服务和新备份。备份是逐数据库在线快照，不是跨数据库同一时刻的原子快照。实体电视、Google 真实选片与家庭账号操作必须分别记录验证状态，不能由临时浏览器测试替代。
