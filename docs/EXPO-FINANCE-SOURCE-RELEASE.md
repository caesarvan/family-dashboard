# Expo 来源导入界面：55→55 发布适配器

本适配器准备来源导入 UI 候选，尚未生成正式工具、打包、绑定或发布。父 baseline 已于 2026-09-17 21:58:49（北京时间）激活，21:59:22 TLS 读回及 22:01:55 独立读回通过；下列值是已核的当前父身份，见 [父发布验收](EXPO-BASELINE-ACCEPTANCE.md#expo-baseline-release)。本批后端不变，候选本地证据见 [组合验收](EXPO-FINANCE-SOURCE-ACCEPTANCE.md)。

## 固定父原件与范围

输入是私有 `expo-baseline-tools-20260917-r1/` 的七算子、`prepare-package.py` 和 `bind-release.py`。九份实际 SHA 固定在 [适配器](../deploy/expo_finance_source_release/prepare.py)，生成前后再次核对，不运行原算子。

| 字段 | 已核父发布值 |
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

输入与输出必须是受限绝对路径，拒绝 symlink／junction；输出只能位于 access 根下的全新目录。未给最终 `--freeze` 时不绑定测试数量；给出 freeze 后仍仅生成审查稿。父版本已上线并完成独立核验；本轮浏览器功能、12 图独立视查与 collection 已完成，仍须完成最终组合审查、正式源码合入和新 freeze，再独立审查实际九文件、核包并绑定。旧工具和失败原件不覆盖、不重放。

`stage.py`、`validate.py`、`expo_contract.py` 保持父原字节；验证资源仍为内存 896 MiB、tmpfs 640 MiB。Docker、依赖、环境和 55 张户内表及注册库保持；没有 DDL。停写完整备份、原 rows／schema／sequences／registry 与新 app 启动后的比较、阶段身份和排他输出守卫保持。后续逐库在线备份不等于全局原子快照。

post 仅改变本批发布目录前缀，全部 34 个唯一匿名 API 检查原样保留，仍只接受 401；没有重复增加五个来源路径。正常 TLS 静态资源、Expo 入口、`/tv → /app/tv`、经典回退、生成私有资源和退役脚本拒绝检查保持。

## 实际本地检查与未验范围

- `tests/test_expo_finance_source_release.py` 普通专项 **20 passed**；XML `test-results/finance-source-release-r1.xml` SHA `04650ea3708ee861655114e2cf754375feb3cdc00b3b5f1c083facb58d6d7030`。
- 同文件显式 CLI 用真实父九原件和父归档，在临时目录生成代码。生成代码的网络／进程调用被拒绝；7 个未绑定入口、33 个坏 freeze、37 个实际后端字节变更拒绝通过，Docker 与暂存／验证字节保持，匿名 401／200／403 分支符合原契约。
- CLI 对固定候选 `4b6d6c5aeba98386e0aafe712313a3fce2524359` 核对全部 37 个后端与父包相同。真实父／新选择器集合相同、三个本地输入缺失拒绝、敏感与生成路径拒绝。报告 `test-results/finance-source-release-pinned-r1.json` SHA `c928586b9bee469b9db4fc66c490701bc7c4103b9b06d6838e491b32c494437e`。
- 上述 CLI 受验时的 `4b6d6c5` 尚缺本适配器、专项与 `browser_expo_finance_source_check.py`，原报告保留三项待集成及 `actualBuildInputCount=null`、`actualFreezeAccepted=false`。三项现已合入 `c1486996`，新真实构建与浏览器另有原件，不能倒改原 CLI 记录为已验最终 freeze。

最终 Python 选择为八模块：baseline 读取会话、导入会话、原 baseline、frontend runtime、家庭隔离、平台备份、持仓迁移和本适配器。固定 `c1486996` 已实际收集 **184 个唯一 nodeId／8 模块**，前后 649 个 tracked 源相同，`collectedOnly=true`、`executed=false`；未执行本批 Linux 验证，不复用父 348。构建也恰有 184 个输入，但它与测试集合是两种不同计数。完整 source bridge／消费观察旧套件不重复纳入，依靠本轮后端字节守卫与既有受验父版本，不能据此扩称真实来源内容正确或新设备／云端验收。协议与父发布准备见 [baseline 发布](EXPO-BASELINE-RELEASE.md)。
