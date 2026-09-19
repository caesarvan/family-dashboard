# 助理资料与照片搜索的浏览器验收

此工具基于 UI 候选 `839d038eec04dc11229e41a1c0bc9e06d44b0199`，依赖另行审查、由集成人合入的资料搜索 API。作者分支没有复制 API。准备脚本和通过工具自检不表示组合产品、浏览器或生产已验收。

实际执行还需合入 UI 审查修正 `acd5c99e60a0c7d9be2fb1a49f13a6e7ef7c77eb`（原旅行 404 时搜索入口不能自动转入本人库）；本浏览器分支保留原 base，不复制这处产品修复。

`tests/browser_expo_assistant_document_search_check.py` 只运行四条端到端流程，各自使用新的临时 Flask、SQLite、HTTPS 服务和 Edge 上下文：

1. 真实上传 21 份虚构 PDF、保存一张合成照片；搜索第二页，依次打开原资料和照片编号并返回原搜索词与页码。搜索／详情均为真实接口，检查没有业务写入或自动资料下载。
2. 搜索后实际删除原旅行；旧搜索入口明确拒绝打开移出原范围的资料，不能自动转入本人库。返回重新搜索后，以未关联私密资料的新范围显式打开本人库中同一记录。
3. 伙伴先能读取共享资料；拥有者真实撤销共享、删除照片后，已有搜索卡片不能打开旧详情，返回重新搜索后移除结果。
4. 暂停真实成功的资料列表或照片详情响应，实际更换成员登录 cookie，再交付原响应；必须丢弃旧成员内容，新成员重新搜索为零。

前两条生成 390／1280 宽的八张截图，同时测量实际 body 和 documentElement 横向尺寸、视口内控件边界；结果包含 HTTP、数据库摘要、完整来源／导出／fixture 哈希及清理结果。不会访问真实 Google、微软、模型或生产；照片导入 worker 仅使用合成任务输入，随后所有浏览器业务请求走真实后端。采购错误文字的垂直测量继续使用原采购 harness 的 `offline_draft`，不在这里重复。

在非作者审查、组合 API/UI、新前端导出完成后，使用组合 checkout 中的脚本，填入真实冻结值运行。Windows `--bundle` 必须使用 `\\?\` 绝对路径，防止深层静态资源被短路径限制遗漏：

```powershell
& '<项目 Python>' -B -X utf8 '<组合 checkout>/tests/browser_expo_assistant_document_search_check.py' `
  --source-root '<组合 checkout>' --expected-head '<完整组合 HEAD>' `
  --bundle '\\?\C:\<新构建目录>\web' --expected-build-evidence '<build-evidence.json SHA-256>'
```

默认必须使用同一提交构建。只有明确传 `--build-source-head` 时，才允许后续仅修改本脚本、对应 wrapper 或本说明的已审后代提交复用原导出；任何业务源码或 fixture 依赖差异都会拒绝。每次创建新 `test-results/expo-assistant-document-search-<UTC>/`，保留失败原件，不覆盖以前结果。

照片首次打开提示的小修采用 `cc688863f090bb300c7e6fe3412ef011b7498958` 新 R2 导出。增量验证在审查通过的工具后代提交运行，额外传 `--build-source-head cc688863f090bb300c7e6fe3412ef011b7498958 --scenario content_pagination`：只运行原分页往返这一完整流程，生成六图，明确检查首次照片详情不存在两句草稿恢复提示；原 HTTP／DB、身份、无写入、原编号、往返分页及布局断言保持。省略 `--scenario` 仍运行原四条／八图；不会将该单项结果记为四条再次通过，旧 R1 原件保留。

工具自检（仅临时 Git 输入身份校验，不启动产品或浏览器）：

```powershell
& '<项目 Python>' -B -X utf8 -m pytest tests/test_assistant_document_search_browser.py -q
```

真实来源、实体电视、原生设备、完整家庭验收和生产发布均不在此工具的通过范围内。
