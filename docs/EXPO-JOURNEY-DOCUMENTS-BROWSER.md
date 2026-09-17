# Expo 旅行资料浏览器验收

**新脚本候选，尚未执行浏览器；不能据脚本存在宣称通过。** 入口为 [browser_expo_journey_documents_check.py](../tests/browser_expo_journey_documents_check.py)。须先非作者审查，再用包含该脚本及实际组件的冻结源码与对应 Expo 导出运行。

## 复用与范围

复用已有 `browser_expo_finance_check.Run` 的本地真实 Flask／SQLite／TLS、成员登录、CSRF、请求计数、重启及错误截图夹具，覆盖财务 reset 为无操作，不运行旧财务流程。应用来自指定 source-root 的 `create_app`，DATA_DIR 为独立临时目录，静态文件与 Expo 导出复制进该夹具；不启动 Metro，不连接线上服务。

计划九组有界场景：

1. 真文件选择器上传合成 PDF、含合成元数据的 PNG；确认前无业务写，默认私有与分段正确，鉴权下载核对 PDF 字节／净化 JPEG，临时 app 重启后仍存在。
2. UI 明确共享后伙伴仅下载；本人库、真实第二家庭、实际配对 TV 保持隔离。
3. API 制造真实 CAS 冲突，UI 保留草稿，读取后只合并本人改动，明确再次保存。
4. 上传实际提交丢回复与请求未送达两种情况；GET 不归因、不重发，明确重试沿用完整 payload／requestId，SQLite 只保留一条记录。
5. PATCH／DELETE 实际提交丢回复，只 GET 核对并明确采用，不自动重试；旧上传键不能恢复已删除文件。
6. 删除旅行后文件私有保留，UI 从本人库重新关联；13 份 API 准备资料验证搜索与分页。
7. 离线／模拟后台隐藏并保留同身份草稿，迟到 GET 不能重新显示；明确放弃无业务写。
8. 下载和上传真实响应返回前切换有效成员 Cookie，旧私密内容不回显、旧下载不发出，新成员不能取得文件。
9. 主旅行入口、地图内嵌旅行、无模型的助理创建旅行以及更多资料库的导航保护；明确放弃后可返回首页。

计划生成 12 张实际滚动的当前视口截图：320／390／1280／1920 的编辑上部、确认按钮下部及资料库；资料库包含浅色与深色。检查页面没有横向溢出，新保存／返回按钮至少 44×44px；这不是所有控件、全部滚动内容、真实手机或实体电视的完整视觉验收。

## 运行

使用主项目已有 Python 虚拟环境，要求 Playwright、Edge、Flask、Werkzeug、cryptography、Pillow 及应用依赖可用。冻结包由集成人另行构建，不在本脚本中安装依赖或构建前端。

```powershell
& '<项目>/.venv/Scripts/python.exe' -B -X utf8 '<本分支>/tests/browser_expo_journey_documents_check.py' --source-root '<已审冻结组合目录>' --expected-head '<完整源码提交>' --bundle '<对应构建>/dist' --expected-build-evidence '<build-evidence.json SHA256>'
```

源码 HEAD／tree／tracked clean、build evidence、全部构建输入与导出 SHA 必须一致；实际执行的 harness、复用夹具也必须与冻结源码同字节。结果保存到脚本所属工作树的 `test-results/expo-journey-documents-<UTC>/`，含执行脚本、JSON、截图及失败时的 ARIA。结束再次核对全部 tracked 源与导出不变、临时夹具清除；失败原件保留，不覆盖或改成通过。

浏览器请求限制精确本地 origin，Python socket 限 loopback。网络故障只截留或丢弃真实 HTTP 回复，`route.fetch` 禁止跟随重定向；不伪造业务成功响应，不预注入 UI。文件、旅行、家庭和账户全为合成夹具；文件准备和并发修改可使用真实 API，核心上传必须经过实际界面。文档内容不送模型、云提供者或生产；背景状态通过事件模拟，真实凭证可读性、公网／原生／实体设备仍不属于该套结论。
