# Expo 来源导入界面：55→55 发布适配器

本适配器仅准备下一批未绑定工具。父 baseline 包已经打包并实际构建成功；本文撰写时其 Linux 验证仍在进行，尚未激活，不能把下面的预期父身份称为当前生产身份。新来源导入界面也没有执行打包、绑定或发布。

## 固定父原件与范围

输入是私有 `expo-baseline-tools-20260917-r1/` 的七算子、`prepare-package.py` 和 `bind-release.py`。九份实际 SHA 固定在 [适配器](../deploy/expo_finance_source_release/prepare.py)，生成前后再次核对，不运行原算子。

| 字段 | 已确认的父候选值 |
| --- | --- |
| archive | `bee0c0e751f5aca0599920560bb20fadaeeb1de7779a81f9949fe4e39fe5bef8` |
| manifest | `265830d1037696d39f1712a7f19cec25780de788071406cc0442956b06eb3252` |
| 实际 build image | `sha256:4e3de8d45b39e251a7c0d3a068847c758617957028652b2f7dcc1f80e01cc5f2` |

本批必需变更仅为 `types.ts`、`FinanceScreen.tsx`、`HouseholdApp.tsx`；新增来源导入 model／Panel、Node 模型测试、真实浏览器脚本及本适配器和专项。全部 37 个现有根级 Python 后端都列入 `UNCHANGED`，覆盖资产金额、来源转换、消费观察、认证、家庭和其他既有 API。发布前任何这些后端字节变化都拒绝；不是只固定三个来源入口。

沿用父完整来源白名单和三个本地构建输入：`frontend/tests/journeySegments.test.ts`、`frontend/tsconfig.tests.json`、`frontend/typecheck.mjs`；不扩大公共白名单，不把 Node 测试放进 Python 镜像。最终所有构建输入、Git blob、manifest 与实际导出仍须完整对应。

## 生成与执行边界

```powershell
python -B deploy/expo_finance_source_release/prepare.py --source-root <private-access-root> --output <private-access-root>/expo-finance-source-tools-<new-id>
```

输入与输出必须是受限绝对路径，拒绝 symlink／junction；输出只能位于 access 根下的全新目录。未给最终 `--freeze` 时不绑定测试数量；给出 freeze 后仍仅生成审查稿。父版本须真正上线并完成核验，新组合与浏览器通过、真实 collection 完成后，才能独立审查实际九文件、核包并绑定。旧工具和失败原件不覆盖、不重放。

`stage.py`、`validate.py`、`expo_contract.py` 保持父原字节；验证资源仍为内存 896 MiB、tmpfs 640 MiB。Docker、依赖、环境和 55 张户内表及注册库保持；没有 DDL。停写完整备份、原 rows／schema／sequences／registry 与新 app 启动后的比较、阶段身份和排他输出守卫保持。后续逐库在线备份不等于全局原子快照。

post 仅改变本批发布目录前缀，全部 34 个唯一匿名 API 检查原样保留，仍只接受 401；没有重复增加五个来源路径。正常 TLS 静态资源、Expo 入口、`/tv → /app/tv`、经典回退、生成私有资源和退役脚本拒绝检查保持。

## 实际本地检查与未验范围

- `tests/test_expo_finance_source_release.py` 普通专项 **20 passed**；XML `test-results/finance-source-release-r1.xml` SHA `04650ea3708ee861655114e2cf754375feb3cdc00b3b5f1c083facb58d6d7030`。
- 同文件显式 CLI 用真实父九原件和父归档，在临时目录生成代码。生成代码的网络／进程调用被拒绝；7 个未绑定入口、33 个坏 freeze、37 个实际后端字节变更拒绝通过，Docker 与暂存／验证字节保持，匿名 401／200／403 分支符合原契约。
- CLI 对固定候选 `4b6d6c5aeba98386e0aafe712313a3fce2524359` 核对全部 37 个后端与父包相同。真实父／新选择器集合相同、三个本地输入缺失拒绝、敏感与生成路径拒绝。报告 `test-results/finance-source-release-pinned-r1.json` SHA `c928586b9bee469b9db4fc66c490701bc7c4103b9b06d6838e491b32c494437e`。
- 此候选尚缺本适配器、专项与 `browser_expo_finance_source_check.py`，报告明确列出三项待集成。没有提供本批构建或最终 freeze，`actualBuildInputCount=null`、`actualFreezeAccepted=false`，不宣称最终组合已齐。

最终 Python 选择为八模块：baseline 读取会话、导入会话、原 baseline、frontend runtime、家庭隔离、平台备份、持仓迁移和本适配器。准确数量由最终源码实际收集，不复用父 348；collection 不等于执行通过。完整 source bridge／消费观察旧套件不重复纳入，依靠本轮后端字节守卫与既有受验父版本，不能据此扩称真实来源内容正确或新设备／云端验收。协议与父发布准备见 [baseline 发布](EXPO-BASELINE-RELEASE.md)。
