# 家庭成员关系浏览器验收

本脚本为独立验收工具，尚未执行，不代表功能已验收或发布。使用真实 Expo 导出、Edge、临时 HTTPS Flask 和 SQLite；所有账号、邀请和私人财务资料均为合成。界面的注册、绑定、邀请、加入、切换、移除、退出和个人登出必须实际点击，API 仅用于建立旧身份／第二家庭／私人资料及核对持久结果。

| 独立组 | 实际用户路径与关键断言 |
|---|---|
| 旧身份绑定 | 验证当前家庭密码→创建个人账户→明确绑定；注册不自动绑定，原 `member1` 私人 owner、用户字段与资料保持，伙伴不可读取 |
| 第三人成员生命周期 | 管理员创建一次邀请码→第三人注册→重新核对→明确加入→切换；移除拒绝旧派生会话，重新邀请保留同一 owner 与资料且为普通成员，自助退出后仅个人回执可查 |
| 同人双户 | 两户各自 `member1` 明确绑定同一个人账户；切换时资料不串户，旧代次派生 cookie 拒绝，个人登出撤销当前派生成员访问 |
| 未知结果与布局 | 丢弃真实已提交邀请码回复，原 requestId 保留且无自动重发／核对；明确 GET 后读当前，历史／重放不泄漏 token；隐藏清秘密，键盘操作，320／390／1280 两主题共六张可见视口图 |

每组独占临时数据库、服务和浏览器 context。组内失败停止下游阶段，保存异常堆栈及可得的失败截图；其他独立组继续，整轮失败不会计作通过。成功业务 DTO 由真实服务器返回，唯一故障注入只读取真实响应后断开传输。浏览器和 Python socket 都禁止外网。

脚本自身来自单独干净提交，记录其 HEAD、实际源码 SHA；应用必须精确匹配传入的 HEAD／tree 和本轮 `membership-build-r1.json`（`head/tree/files/buildExit/bundleMarkers`）原件 SHA，导出全集相同，不允许仅祖先关系复用。执行前后核全部 tracked source、导出、三个复用 fixture 的实际模块路径与 SHA，以及应用／脚本 HEAD、干净状态和临时目录清理。源码不同的后续组合需要新的明确构建记录。

```powershell
& <root-python> -B -X utf8 tests/browser_expo_memberships_check.py `
  --source-root <reviewed-source-root> --expected-head <40-hex-head> `
  --bundle <actual-export> --build-evidence <membership-build-report> `
  --expected-build-evidence <64-hex-sha256>
```

输出排他写入作者树 `test-results/expo-memberships-UTC/`，命令 stdout／stderr 由调用方另存。复用 `browser_expo_finance_check.py`、`test_financial_files.py`、`test_app.py` 的真实临时环境；不加载旧验收场景运行。入口先绑定实际端口再创建应用，使个人账户的 Origin 校验沿真实本地地址执行。

六张图仅能支持实际可见区域的后续人工审查，不等同所有内滚动、实体手机／电视、真实家庭、云服务或生产迁移验收。此四组也不替代领域／个人账户／工作队列的并发专项与发布保全检查。

R1 运行停在四组的静态文件复制阶段，尚未进入 UI：Windows 长路径导致 `copytree` 失败，0 检查／0 图，四个临时目录均已清理。原始记录与失败完整保留。修订仅将测试临时目录改为短前缀、源导出用 Windows 扩展路径读取，并以完整 `os.walk` 清单核原导出和每组复制品；Root 的独立完整构建记录实际列出 23 文件，原 11 项散列均保持。后续轮次不得把这次初始化失败记作业务通过。
