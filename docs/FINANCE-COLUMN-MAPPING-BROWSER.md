# 通用账单字段映射：本地浏览器验收

`tests/browser_finance_column_mapping_check.py` 在独立临时 Flask／SQLite／HTTPS／Edge 中操作 Expo 文件选择器。合成 CSV／XLSX 只含虚构记录，成功业务响应来自真实应用；故障只丢弃或延迟真实响应。

R1 实际执行六场景，0/6 通过：连续选择列时，上一弹窗关闭动画未结束，测试定位到两个同名选项。修正为每次选择后等待选项完全消失，不使用 first/nth 绕过重复。原失败保留在 `test-results/finance-column-mapping-20260917T222739281084Z/`；修正版 R2 已实际完整 6/6 通过，原始选择器与业务断言保持，详见下方结果。

1. 日期、金额、标题、币种四列映射；CSV 引号内换行的原文件位置、精确分与多币种、首次来源、重启保留；同文件再次预览和换金额列不得重复入账。
2. XLSX 先选工作表再映射；来源为工作表实际行；换工作表不得沿用旧 token。
3. 改列和换文件清除旧预览；金额错误或短行缺少币种时，连同文件中的有效行也不部分保存，旧映射 token 拒绝。
4. 实际确认已提交但回复丢失，只用原编号读取持久化回执，确认请求只有一次。
5. 另一成员不能读取本人流水或回执；本人退出后，迟到的真实预览不能重新显示或触发保存。
6. 320／390／1280／1920 四宽、浅深两色的列选择控件，触控尺寸及键盘预览；预期八张可见视口截图，须由非作者实际看图。

每个场景用新的临时数据库，服务端与浏览器禁止外网，运行前后核对完整 tracked 源码、构建输入及全部导出，并核对受验提交和清理结果。接口权限与并发撤销在后端专项另验，不与浏览器数量相加；真实平台文件、本人公网流程、云和实体电视不在本脚本范围内。

运行参数必须绑定已审查、干净的组合提交和对应 Expo build evidence，不应直接运行本功能分支。允许复用祖先提交的构建，但仅允许本验收脚本与本文两个路径变化，并必须验证原构建提交与 tree、全部构建输入和导出逐字节一致；报告分别记录当前源码与原构建提交，不将测试或文档更新冒充重新构建。命令形状：

```text
python -B -X utf8 tests/browser_finance_column_mapping_check.py \
  --source-root <reviewed-clean-combination> --expected-head <full-commit> \
  --bundle <exact-export-directory> --expected-build-evidence <sha256>
```

原件写入执行脚本所在 worktree 的 `test-results/finance-column-mapping-<UTC>/`；失败报告和截图保留，每个失败场景不计成功。截图只能支持被实际查看的视口，不能替代内部完整滚动区域或真实设备验证。

## R2 实际结果

R2 原件为 `test-results/finance-column-mapping-20260917T223602014837Z/result.json`，SHA `97620fca69ae828f7247a4d3aa64640c36193577b1e64fa8de775b31f53462f4`。六场景均通过，八张 PNG 由 Root 逐张查看，结论仅 `PASS_VISIBLE_VIEWPORT`；视觉报告 SHA `817f074a5833291a768357936baa183f9b18ec05c986425a0f5229484b41a91b`。

受验源码为 `2331b608056dec2175e6cca9d0e4beb9f9d2dc20`，原实际构建为 `c958c1b2da6f4a79cbc828653d6d86afdfab76da`，build evidence SHA `3cafbe331fae7eca902af4b12496bdf13cd599c752177b4ec6d250aea4e9ca34`。196 构建输入与 23 导出逐字节一致，复用导出而非重新构建；739 源文件、4 fixture 前后保持，6 个临时环境全部清理，页面错误与外网请求均为 0。R1 0/6 原件不覆盖，也不与 R2 相加。最终发布及更多证据见[集中验收记录](FINANCE-COLUMN-MAPPING-ACCEPTANCE.md)。
