# 助理清单确认：发布适配

本轮候选尚未发布。父版为照片日期源码 `5fae5c5d7c809ddc1dd5d09f68bd56cbeb6d7fa1`，生产保持75张家庭表、9张平台表与app/sync/media/decoder/web五服务。当前状态见 [README](../README.md)，行为契约见 [助理清单](ASSISTANT-LIST-EDITING.md)。固定适配不适用于其他父版，历史计划不可重放。

本批只改 `home_assistant.py` 和 Expo 界面。草案、首次确认绑定及回执沿既有 `assistant_plans` JSON 持久化，没有DDL、回填、新依赖、云发布或模型协议变更。新增GET只供本人核对原计划；采购截止日期沿已有实体字段保存。

`build_assistant_list_release.py` 绑定已安装包、镜像和独立生产审查，只允许该业务模块变化，其余112个非Expo运行文件逐项保持。Docker、Compose、Nginx和独立解码镜像不变。前端在固定组合提交实际安装锁定依赖、类型检查和导出，再以完整输入和产物校验固定包；作者测试、浏览器、镜像测试分别记录。

`prepare_assistant_list_activation.py` 沿现有准入检查，读取父版原件作为数据，核对固定源码/包/镜像、精确测试选择、资源保留范围及非作者审查。未变化的媒体运行文件可沿用父版相应资源证据，不据此宣称新助理查询的任意并发能力或生产恢复通过。

`activate_assistant_list_release.py` 使用现有五服务控制器的 `assistant-list-source-update` 模式：持发布锁，暂停备份，停止写入服务，完整库组备份，安装固定源与镜像，仅启动app后再次停止，核对75/9全表、数据、settings与序列一致，然后恢复服务、HTTPS和计时器。本模式没有migrate操作。

失败保留已消费计划和现场，停止本次候选，不自动恢复或重启旧服务。回退须按实际回执明确恢复完整数据库组；只读 `verify_restored_group` 绑定原数据目录、原件、计划和源身份，不能只恢复单户或只回退镜像。

测试 `test_assistant_list_release.py` 覆盖新的封闭模式、五服务顺序、无迁移、失败停止与计划不可重放；使用记录式服务调用，不将其描述成生产恢复。实际部署后须另记录安装、全组保全、服务、TLS和计时器结果。真实账号、手机选择器、实体电视和完整A–D验收仍分别跟踪。
