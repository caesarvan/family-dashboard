# 相册真实本地集成检查

`tests/browser_media_integration_check.py` 在临时数据目录启动真实 Flask 应用和 SQLite，以真实 Edge 加载完整 `index.html`、账户界面、product shell 与相册 UI。媒体业务路由、成员 Cookie／CSRF、家庭路由、数据库、worker、Google Picker 协议校验、Pillow 净化与 Fernet 加密均使用候选源码，不用同名合成业务 API 替代。

唯一外部服务替身是 Google：OAuth 授权页面回跳、token／identity 返回、Picker 会话／选片页面／清单／图片网络响应。照片与账户均为虚构。浏览器 Google 页面由路由拦截器直接返回，服务端 token 与图片由注入的 transport 返回；其余外站浏览器请求与 Python 非 loopback socket 被拒绝。未使用真实 Google 账户或凭据，也不证明 Google 实际同意界面和线上 OAuth 配置可用。

测试先绑定临时 loopback TLS 端口，再把其准确地址设置为 `PUBLIC_ORIGIN`，因此实际 Photos 授权主机检查始终执行。Edge 只在此隔离上下文接受临时自签证书；这不是公共 TLS 或生产验收。

## 执行

在包含已审 UI、API、worker 的固定候选根目录运行，使用已有项目虚拟环境和 Windows Edge：

```powershell
python -B -X utf8 tests/browser_media_integration_check.py
```

应用工厂尚未接线时，测试可在首请求之前调用候选的 `register_media_library`。这种结果会在 `registration` 中明确写为 `explicit fixture registration before first request`，不当作实际工厂接线已通过。它不替换业务处理器或状态机。

实际 app／子家庭接线合入后必须使用：

```powershell
python -B -X utf8 tests/browser_media_integration_check.py --require-factory
```

此模式要求首个家庭、重启工厂及新建子家庭都已自动安装 `household_media`；任一缺失即失败，不允许注册 fallback。每轮生成全新的 ignored `test-results/media-integration-<UTC>/` 目录，保留失败报告，不覆盖原件。

## 实际流程与断言

- 浏览器真实登录后，从相册连接 Photos；实际应用 OAuth 回调进入相册，不跳到日历／清单选择。只由 Google 边界替身接收和返回合成授权。
- 临时处理同意后创建真实 import；worker 逐个执行 create、poll、list、download、cleanup。完整 Picker 清单重核、Pillow 净化和 SQLite 加密落库均真实执行。临时照片未确认前不出现在相册列表。
- 本人再次同意持久保存；照片默认私密，伴侣和两台真实配对 Cookie 的电视客户端均无访问权。关联真实旅行并共享后，伴侣可查看，但电视仍未获准。
- 在实际相册 UI 单独授权其中一台屏幕，验证第一台获得最小媒体投影与预览，第二台仍为空；TV 不能访问成员相册 API。这里验证电视凭据和接口许可，不模拟实体电视播放。
- 真实看板刷新保持同一草稿 DOM、焦点与文本选区；撤回私密后伴侣和已授权电视的下一次真实 API 请求立即拒绝。
- 页面重载和应用工厂重新创建后，从同一 SQLite 读回完全相同的净化 JPEG、旅行关系和权限；数据库外键检查通过。实际 logout／另一成员登录清理旧私密草稿；真实邀请码创建第二家庭后，相同成员名仍无法读取前一家庭的媒体。

每次记录 Git HEAD、源码 SHA 前后、通过步骤、JS 错误、被阻止的外站访问、实际注册方式和合成截图。异常强制 `passed=false` 并退出非零；浏览器先关闭，服务与请求关闭后才清理临时数据库目录。原 Google 图片字节不写入相册文件目录；保存的是实际引擎产生的 SQLite 密文 BLOB。

本检查不启动 Docker、worker 守护服务或生产发布，也不替代 schema 迁移／恢复、真实 Google 媒体和实体电视验收。现有单模块边界测试、此处真实本地组合、最后生产验收应分别记录。
