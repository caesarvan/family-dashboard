# 旅行简报事项的浏览器验收脚本

本页说明候选 [browser_expo_assistant_trip_items_check.py](../tests/browser_expo_assistant_trip_items_check.py) 的执行范围。脚本提交时尚未运行组合浏览器，不能作为功能通过或上线证明。运行须使用已独立审查的 API/UI 组合源码和对应完整 Expo 导出。

## 四条独立流程

1. 合成模型返回精确旅行、本人／另一成员准备和采购、单项人民币预算及未知金额；真实简报校验后在页面读回，继续至原旅行编辑，重新预览并明确保存。核对任务负责人和日期、采购整数分／`null`、独立旅行总预算、一次 workflow/action、无日历或任务发布队列变化；实际重启临时 app 后读回并截图。
2. 通过真实临时 `/api/profile` 设置两个同名成员，模型原文同时包含未知分工和同名分工。未解决时不得进入预览；明确选择「一起」或「另一位成员」后核对实际成员 ID，仍不保存。
3. 编辑总日期、随出发调整的天数，删除和添加准备／采购。一次明确标记的未发送预览请求模拟网络失败，检查编辑仍在；再走真实预览。保存请求真实提交后丢弃响应，经原「核对原保存」重用同一预览令牌和操作编号，检查没有重复实体或操作。
4. 延迟已经真实返回的模型简报；先在等待中编辑字段，确认迟到结果不覆盖编辑，再用真实登录切换成员后放行另一条迟到响应，检查旧原文、事项和金额不进入当前页面、URL 或浏览器存储，不写业务记录，不自动重复请求模型。

只有 `home_assistant._model_json` 返回的原始模型 JSON 为合成内容。实际 `model_journey_brief`、字段规范化、原文依据、当前成员解析、会话、CSRF、preview/apply 和 SQLite 均执行生产代码。模型 input 必须严格只有本次 `request`；不发送成员列表或家庭数据。此脚本不能证明真实模型抽取质量或真实云发布成功。

## 执行与原件

```powershell
& '<项目虚拟环境>/Scripts/python.exe' -B -X utf8 `
  '<已审组合>/tests/browser_expo_assistant_trip_items_check.py' `
  --source-root '<已审组合>' --expected-head '<完整组合 SHA>' `
  --bundle '<完整 Expo export 目录>' --expected-build-evidence '<build-evidence.json SHA256>'
```

当唯一变化为构建后的已审源码／测试时，可显式传 `--build-source-head '<构建 SHA>'`；脚本要求该提交为组合的祖先、整个 frontend Git 树一致、构建 inputFiles 逐字节一致。默认要求构建与组合为同一 head。Windows 长路径导出使用完整枚举，任何缺文件或哈希不同均失败。

原件写入组合源码下新建的 `test-results/expo-assistant-trip-items-<UTC>/`，保留执行脚本、真实 HTTP 请求／响应、合成数据库快照、原始模型 advisory、每场景失败和 `result.json`。源文件、实际导入 fixture 和全部 bundle 字节在前后核对。四张截图分别覆盖事项整理／保存读回的 390 和 1280 宽可见视口，不代表所有内层滚动位置均已视觉验收；截图仍需非作者查看。

每场景独立临时目录／数据库／回环 HTTPS 服务，浏览器只允许同一回环站点，Python socket 禁止非回环连接；本地证书忽略仅适用于临时自签名服务。关闭浏览器上下文和所有请求线程后才清理该场景新建临时目录。失败原件留在 `test-results`，不自动重试。没有生产数据库、真实账户、实际 provider、远端或实体电视操作。
