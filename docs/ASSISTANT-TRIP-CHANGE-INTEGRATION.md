# 已有旅行改期建议：应用接线

本接线已随 AI 已有旅行改期发布；运行身份、分轮证据与生产审计见[集中验收](ASSISTANT-TRIP-CHANGE-ACCEPTANCE.md#assistant-trip-change-release)。下方命令与限制保留本接线作者阶段的历史范围。

本增量基于 `04e22a7e8902450fe1c38b12a4edc02a2dc091fb`，将已审查的建议 API 接入实际 Flask 应用和 Docker 源文件清单。接口行为见 [API 合同](ASSISTANT-TRIP-CHANGE-API.md)，界面流程见 [Expo 接线](EXPO-ASSISTANT-TRIP-CHANGE.md)。

`create_app()` 在成员会话、旅行和原助理注册之后调用 `register_assistant_trip_change(app, db, Problem, body, require_member, limited)`。使用同一个请求解析、成员校验与限流实现，保留全局同源 JSON、CSRF、电视只读和家庭隔离保护。新家庭仍通过既有 `create_app()` 初始化，因此也正常注册此路由。注册本身没有 SQL、DDL 或数据迁移。

Dockerfile 增加 `assistant_trip_intent.py` 和 `assistant_trip_change_api.py` 的 COPY；没有新增依赖、配置或执行引擎。建议接口只读旅行并产生待核对日期，实际保存仍经过原快照、预览、明确提交和原操作回执恢复。

`tests/test_assistant_trip_change_api.py` 删除早期作者基线的临时注册包装。fixture 现在断言应用实际注册一次 `/api/assistant/trip-change`，仅提供 POST/OPTIONS，并由真实 API 模块处理。其余业务测试与禁止外网的 provider 合成边界保持不变。API 合同文档中关于“测试注册包装”的历史说明由本接线替代。

## 验证与交付边界

聚焦命令（使用现有开发 Python 环境）：

```text
python -B -X utf8 -m pytest -q tests/test_assistant_trip_change_api.py tests/test_app.py::test_auth_csrf_origin tests/test_app.py::test_tv_pair_readonly_revocation --junitxml=test-results/assistant-trip-change-wiring-pytest.xml
git diff --check
```

本次命令结果为 42 项通过（78.69 秒，退出码 0），`git diff --check` 通过。测试使用临时 SQLite、真实应用注册、登录、CSRF、家庭选择和原改期接口。模型输出仅为合成输入，socket 出网被禁止；不等同于真实供应商响应或完整浏览器验收。JUnit 日志保存在忽略目录 `test-results/assistant-trip-change-wiring-pytest.xml`，固定提交与证据散列随本次交付记录。

本增量没有执行 Docker 镜像构建、浏览器验收或部署。历史发布 profile 与打包算子未修改；新源码发布 profile、镜像验证和生产发布由集成人另外安排。单独合入本接线不表示已上线。
