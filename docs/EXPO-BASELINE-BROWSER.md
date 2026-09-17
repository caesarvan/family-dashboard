# Expo 本人资产来源浏览器验收

此页记录新增脚本和执行边界；**当前仅编写、静态检查，尚未运行浏览器，不代表功能或视觉通过**。待独立审查及完整源码、Expo 导出冻结后执行。

脚本：[browser_expo_baseline_check.py](../tests/browser_expo_baseline_check.py)。复用已存在的 `browser_expo_finance_check.Run` 启动真实临时 Flask、SQLite、HTTPS loopback 和 Edge。每组单独应用、数据库、监听端口、上下文和 `ExitStack`，结束关闭浏览器上下文、停止并 join 服务、恢复 patch、移除临时目录；失败保留并继续其余独立组，整轮仍失败。

## 九组计划

1. 真实空记录、旧来源格式及省略秒的带时区时间；财务进入后返回保留已选择账本月份。
2. 真实资产/负债/历史收入、未知金额与零、美元排除口径；后续独立消费观察及负净支出、各自覆盖窗口和来源日期。
3. 30 条记录全部分页可达；在本分类全部记录中搜索深页项、空结果和来源文件。
4. 真实本人、伴侣、签名第二家庭、实际配对 TV 与匿名访问隔离；TV 不读取私密报告，owner 查询不能切换本人。
5. 取得真实 private GET 后切换成员 cookie，后置 `/me` 阻止旧资料安装；等待旧面板因真实 actor 更换卸载，再重新打开。
6. 取得真实 private GET 后切换签名家庭并登录，同样等待身份最终状态，检查无旧户资料。
7. 浏览器离线与模拟 `visibilitychange` 清除资料和搜索；迟到真实响应不能在后台恢复，前台需要新 GET。
8. 丢弃实际 GET 响应后显式只读重试；读取中返回财务，迟到响应不能重开面板。
9. 320、390、1280、1920 四宽：浅色概览、浅色长标题资产、深色紧凑消费观察，共计划 12 张截图；新控件至少 44px，检查可见控件横向溢出。

所有成功业务 DTO 来自真实源码接口。测试使用合成来源候选经实际导入预览/确认、独立消费观察预览/确认取得记录；旧格式走真实 `import_baseline` 持久化。用户界面仍只读，不把 fixture 写入当作 UI 写功能。只延迟或丢弃真实响应，不替换成功 JSON。

每次截图先等待字体、实际滚动到目标、至少 800ms Paper 动画和两帧布局稳定。截图仅当前 viewport，包含内部滚动容器的局部内容，不声称覆盖整页；生成后还需逐张人工视查。自动尺寸检查只覆盖本批明确控件。

## 固定输入后执行

```powershell
& '<既有虚拟环境>/Scripts/python.exe' -B -X utf8 tests/browser_expo_baseline_check.py `
  --source-root '<已审组合工作树>' `
  --expected-head '<完整40位提交>' `
  --bundle '<独立冻结build目录>/dist' `
  --expected-build-evidence '<build-evidence.json的64位SHA256>'
```

需要既有 Python 应用依赖、Playwright 和可用 Edge；不安装依赖，不重建或修改受验目录。脚本核对 clean HEAD/tree、build 输入、全部导出、当前执行 harness 和引用 fixture 字节；运行前后记录全部已跟踪源文件与导出散列，结束再次检查 HEAD/clean。每组输出归入独占 `test-results/expo-baseline-<UTC>/<case>/`，整轮 `result.json` 保存来源、实际 checks、每组清理状态及失败；旧轮不覆盖。

浏览器请求限制到当前本地 origin，Python socket 限 loopback，云端/模型凭据在临时环境中为空。没有访问真实财务文件、邮箱、金融服务或生产；第二家庭和电视均为本地合成身份。前后台事件是夹具模拟，离线使用浏览器网络开关，未验收实体设备。
