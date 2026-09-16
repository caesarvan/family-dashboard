# 相册选片处理结果

本候选只修改相册界面，不改变图片支持范围、保存授权或后台重试。用户过去选择十张而只保存三张，不能据此推断另外七张的格式或失败原因。旧记录若未保存明细，界面明确显示“已保存 3 张；本次其他处理结果未记录”。没有保存数量时也显示“未记录”，不补零。

## 接口与展示

继续读取 `GET /api/media/imports/<id>` 的 `{import, items}`，不增加请求或向电视开放接口。后端结果候选 `0b66f2ee18f512d13f0efb57623d770c9d6382ce` 提供：

- `import.resultsState` 为 `known` 或 `unknown`；未知不展示伪造的统计和进度。
- `import.counts` 包含 `selected`、`ready`、`skipped`、`failed`、`pending`、`saved`、`unselected`。未知为 `null`；缺字段也按未知。`ready` 含成功生成和已有照片复用；`saved` 是本次明确勾选确认数量，含复用。`unselected` 仅确认后表示成功但未勾选数量。
- `import.results` 是最多二十项的 `{position, status, error?}`。序号为本次清单的一开始计数，不能定位原图库中的文件。状态为 `pending`、`successful`、`duplicate`、`skipped`、`failed`；确认后保留处理状态，不把全部改成保存成功。
- `items` 保留可勾选的本地预览，不把失败项伪造为图片。确认后即使此数组为空，仍使用持久统计和结果明细。

界面同时显示处理成功、失败、跳过、待处理／处理中；确认后增加已保存和成功但未勾选。进度表示已经处理的数量，失败也属于处理完成，不能把满进度条解释为全部成功。失败和跳过明细常显，不藏进折叠面板。每项原因通过本地固定代码白名单映射，不展示服务商原文、异常、文件名、代码或任意 `error.message`；未知代码显示原因未记录。多帧代码仅说明当前不支持动图或多帧图片，不能据此认定普通照片是动图或 HEIC。

勾选时实时显示“仅将当前勾选的 N 张保存”，并显示其余可保存但未勾选的数量。没有自动全选或自动保存。结果未知后的重试继续使用同一确认请求和原勾选范围；发生明确冲突时仍要求重新读取、核对和同意。手动重新选片保留已有临时处理同意流程，不自动重复授权。

## 验证与限制

独立专项以真实本地 Edge 配合明确的合成 HTTP DTO，验证十选三留七失败、确认结果丢失后的同请求重试、历史重新打开、逐项安全提示、未知统计、复用与未勾选、键盘、浅深主题和手机尺寸、身份变化后的迟到响应以及电视零读取。它不证明真实 Google、后台存储、实体电视或生产已通过。旧相册浏览器专项同时回归，后端持久结果由另一个候选测试，组合后仍需独立验收。

```powershell
uv run --offline --no-project --link-mode copy --with-requirements requirements.txt --with playwright python -B -X utf8 tests/browser_media_results_check.py
uv run --offline --no-project --link-mode copy --with-requirements requirements.txt --with playwright python -B -X utf8 tests/browser_household_media_check.py
```

新专项将时间戳报告与截图写入忽略的 `test-results/media-results/`，包含受测文件 SHA-256、实际通过项、页面错误和外部请求。所有照片、账户和错误内容均为合成数据。界面源码冻结后由非作者审查，尚未部署。
