# 通用账单字段映射：本地浏览器验收

`tests/browser_finance_column_mapping_check.py` 在独立临时 Flask／SQLite／HTTPS／Edge 中操作 Expo 文件选择器。合成 CSV／XLSX 只含虚构记录，成功业务响应来自真实应用；故障只丢弃或延迟真实响应。

本脚本尚未实际执行；提交和静态审查不代表以下场景已通过。

1. 日期、金额、标题、币种四列映射；CSV 引号内换行的原文件位置、精确分与多币种、首次来源、重启保留；同文件再次预览和换金额列不得重复入账。
2. XLSX 先选工作表再映射；来源为工作表实际行；换工作表不得沿用旧 token。
3. 改列和换文件清除旧预览；错误金额零写入，旧映射 token 拒绝。
4. 实际确认已提交但回复丢失，只用原编号读取持久化回执，确认请求只有一次。
5. 另一成员不能读取本人流水或回执；本人退出后，迟到的真实预览不能重新显示或触发保存。
6. 320／390／1280／1920 四宽、浅深两色的列选择控件，触控尺寸及键盘预览；预期八张可见视口截图，须由非作者实际看图。

每个场景用新的临时数据库，服务端与浏览器禁止外网，运行前后核对完整 tracked 源码、构建输入及全部导出，并核对受验提交和清理结果。接口权限与并发撤销在后端专项另验，不与浏览器数量相加；真实平台文件、本人公网流程、云和实体电视不在本脚本范围内。

运行参数必须绑定已审查、干净的组合提交和对应 Expo build evidence，不应直接运行本功能分支或使用旧导出。命令形状：

```text
python -B -X utf8 tests/browser_finance_column_mapping_check.py \
  --source-root <reviewed-clean-combination> --expected-head <full-commit> \
  --bundle <exact-export-directory> --expected-build-evidence <sha256>
```

原件写入执行脚本所在 worktree 的 `test-results/finance-column-mapping-<UTC>/`；失败报告和截图保留，每个失败场景不计成功。截图只能支持被实际查看的视口，不能替代内部完整滚动区域或真实设备验证。
