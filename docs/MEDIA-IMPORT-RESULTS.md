# 相册导入结果与历史未知边界

本次修订只补全诊断，不增加格式、大小、像素、存储配额或解码容错，不自动重新下载或重发 Picker 创建请求。实际用户曾选择 10 张普通照片，只确认保存 3 张；当时已完成确认和远端清理，原 manifest 已清除，最近完整备份也在确认之后。**无法从现有记录还原另外 7 项的原因，不推断 HEIC、动图或用户未勾选。** 新代码不会重写这些历史记录。

## import DTO

原 `counts.selected/ready/skipped/failed` 保留，新增 `pending/saved/unselected`；另加 `resultsState` 和 `results`：

```json
{
  "resultsState": "known",
  "counts": {"selected": 10, "ready": 3, "skipped": 0, "failed": 7, "pending": 0, "saved": 3, "unselected": 0},
  "results": [
    {"position": 1, "status": "successful"},
    {"position": 4, "status": "failed", "error": {"code": "invalid_image", "message": "图片不完整或无法安全解码。"}}
  ]
}
```

上例为截取结果列表的合成格式示例，不是上述真实 7 项的诊断。实际 `results` 最多 20 项，按完整选择清单顺序给出连续 1-based `position`；它是列表序号，不是地理位置，不含文件名、provider ID、拍摄信息、图片或原响应。

- status 仅 `pending/successful/duplicate/skipped/failed`。`ready` 是 successful 与 duplicate 总数，表示本次可保存项；确认后仍保留原处理状态及计数。
- `saved` 是明确确认时实际勾选数，包含已有本地照片的复用；不是新下载数，也不是当前仍存在的照片总数。`unselected=ready-saved`，仅确认后已知，确认前为 null。
- `pending` 是尚未完成处理的项数；终止导入保留该值时不表示 worker 会继续执行。`resultsState=known` 表示已知清单和逐项处理状态，不表示全部处理成功。
- `resultsState=unknown` 时 results=[]，selected/ready/skipped/failed/pending/unselected 均为 null。旧 confirmed 回执仍有 itemIds 时仅 saved 为其准确长度；回执也已清除时 saved=null。不能把 null 显示为 0 或声称完整成功。

## 固定错误与保存

Pillow 的 `MediaImageError.code` 只接受固定白名单：invalid_input、input_too_large、unsupported_format、invalid_image、multiple_frames、too_many_pixels、output_too_large、unsafe_decoder_configuration。非照片选择用 unsupported_type；原协议拒绝保留 unsupported_media／too_large；未知解码 code 回退 unsupported_image，旧逐项无错误码用 result_unknown。提示从后端固定文本表生成，不存储或转发解码器异常文本、远端 message／URL 或元数据。invalid_image 等通用码不表示已确定具体损坏原因。

处理期的加密 manifest slot 增加固定错误码。确认时把统计和白名单结果写入现有 `context_cipher` 加密回执，保留原本用于幂等的本地 itemIds，清除 manifest；不增加表或字段。相同确认请求重放返回相同处理统计；后续照片删除不会反写历史保存数。取消、过期和处理失败尽可能留下不含授权 context 的最小统计，远端清理成功／失败均可保留；异常诊断密文不会阻止隐私清理。真正账户删除／scope 撤销仍按原逻辑清除 context、manifest、session 和相应本地副本，不为诊断而保留来源信息。

## 定向验证

`tests/test_media_import_results.py` 使用真实 SQLite、媒体引擎、成员 API 与合成图片／Picker transport，覆盖十张照片的部分成功和勾选子集、确认／清理／重放／重启、重复照片与非照片区分、旧无摘要回执、终止摘要及 scope 擦除、损坏诊断不阻碍清理、每个解码白名单码与未知码回退。两个旧专项仅适配新增计数字段和保留的 invalid_image 错误码。

```powershell
python -B -X utf8 -m pytest -q tests/test_media_import_results.py tests/test_household_media.py tests/test_media_import_worker.py
```

全部使用合成输入，不访问真实 Google 或生产；前端展示由独立候选验收。下一次真实选片才会产生新摘要，不能补造过去缺失的原因。
