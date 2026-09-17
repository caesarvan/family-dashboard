# Expo 照片旅行建议：浏览器验收设计

本脚本为待独立审查的验收候选，尚未运行或部署。只能在集成人提供已审组合 HEAD、实际 Expo
导出和构建证据后执行；不能以编译脚本通过代替浏览器或视觉验收。

```powershell
python -B -X utf8 tests/browser_expo_photo_suggestions_check.py `
  --source-root '<冻结组合目录>' `
  --expected-head '<40位提交>' `
  --bundle '<实际构建dist目录>' `
  --expected-build-evidence '<build-evidence.json的SHA256>'
```

复用 `browser_expo_trip_recap_check.Run` 和其底层 finance Run 的真实临时 Flask HTTPS、SQLite、
成员 cookie、Edge、失败截图与清理；照片通过真实媒体创建／确认接口及引擎保存，只有云端 job 完成值
和净化前的 Pillow 图片为虚构夹具。不调用 Google、不读取本人照片，不替换业务成功 DTO。

十二组计划，每组单独临时数据库、服务器、浏览器 context 和清理栈：

1. 本人详情显式读取建议，键盘选中后仅一次四字段 PATCH；真实关联读回，说明、共享、电视许可、地点和旅行保持。
2. 来源时间未知与无日期匹配：明确空态，不生成假建议，仍可使用普通手动关联。
3. v1 上海默认参考时区、v2 夏威夷时区、纳秒来源原文和独立修改后的当前 trip 日期／标题；不推断拍摄地点。
4. 21 条实际匹配旅行只返回有序 20 条，显示更多提示，不冒充全部或自动关联。
5. 在实际 PATCH 到服务端前分别改变照片／workflow／trip revision，真实 409 不写；GET 核对、重新选择、明确确认后才能保存。
6. PATCH 请求未到服务端即中断：保留未知状态，仅 GET 核对，未关联不证明此前请求一定未执行，不自动重发。
7. PATCH 实际提交后丢响应，首次核对 GET 也丢响应：一直保持核对状态，随后手动 GET 恢复，不重复 PATCH。
8. PATCH 200 已交付而后续详情 GET 失败：旧选择不能继续提交，只能明确重新核对。
9. caption、visibility、手动 journey、电视勾选、用途同意五类未保存输入均阻止建议；仅取消本地草稿后再确认，不夹带其他字段。
10. 伴侣共享详情无建议入口；真实成员、签名第二家庭、配对电视按既有权限拒绝，照片关联不变。
11. 换照片、实际离线、模拟 hidden／blur 与迟到 GET；真实换成员／家庭 cookie 后旧内容不能复活。
12. 320／390／1280／1920，浅色长标题、内部滚动确认区、深色键盘焦点各四张，共计划十二图；新建议操作触控至少 44px、无可见横溢、键盘 Space 选择不隐式写。

失败组保留截图、ARIA 和异常堆栈并继续其他独立组；任一失败、page error、外部请求或清理失败令整轮失败。
未知结果检查等待核对按钮 enabled，保证真实写请求及后验已经结束，不提前撤销故障路由。

报告保存于自身 ignored `test-results/expo-photo-suggestions-<UTC>/`。绑定实际执行脚本副本、全部 tracked
源码、构建输入、导出、HEAD／tree 和 fixture 散列，运行前后必须不变。fixture 集合含自身、recap／finance
浏览器夹具、`test_household_media.py`、`media_images.py`、`test_financial_files.py`、`test_app.py`、
`test_journey_documents.py`。所有 SQLite 临时连接使用关闭上下文，失败不手动删除旧原件。

截图只代表明确滚动后的可见视口，须另由审查者实际查看；不代表完整内部表单、原生手机、真实云或实体电视。
visibility／window focus 为浏览器事件模拟；不承诺被冻结进程即时清屏，也不能撤回已经交付给用户的字节。
后端语义见 [照片旅行建议](MEDIA-JOURNEY-SUGGESTIONS.md)，会话专项由独立后端候选提供。
