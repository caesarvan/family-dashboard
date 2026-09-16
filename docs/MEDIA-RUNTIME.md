# 媒体服务运行接线

本候选将已审基础组件、媒体引擎 `e3a0cc1` 和 worker `d32da09` 接入真实应用工厂。Google Photos 本人选择→24h加密暂存→明确保存→私有精选→旅行关联/家庭共享→逐台TV许可均通过同一家庭SQLite。此处只接三张媒体表，当前工厂47张家庭表；后续独立TV播放控制再加一表，由集成人另接，不能把本候选写成48表已验收。

## 工厂与权限

`app.create_app()` 在账户、成员、旅行初始化后调用 `register_media_library`。默认家庭和 `HouseholdPlatform.child()` 构造的家庭都获得 `extensions['household_media']`。现有 child 配置已经传递 Google CLIENT_ID/SECRET，数据目录和派生 SECRET_KEY 仍各户独立，因此 `household_spaces.py` 无需额外修改。配置对象传入、真实邀请/兑换创建子家庭、四成员/两家庭隔离均在本候选测试。

新 `app.extensions['current_tv_device'](con,cookie=None)` 在调用者读事务中核对实际 `household_tv` cookie secret hash、approved和expiry。请求入口和 `/api/state` 使用它；媒体引擎已有自己的等价新事务 `_tv`，preview解密后再次复核，不能用缓存g.actor代替。成员cookie不能替代媒体TV接口的设备cookie。CSRF/Origin/成员只写与家庭路由规则保留。

## 账户事务钩子

`CloudAccounts.media_account_transition(con,before,*,tokens=None,identity=None,reauth=False)` 只在调用者显式写事务中运行，既不HTTP也不commit。仅存在媒体extension时生效：

- 相同grant正常refresh的scope缺省保留原scope；有效Picker权限未变化时，不修改照片、visibility、revision或TV授权。
- 显式记录的新scope不含Picker：在保存tokens的同一事务调用scope_revoked，清来源本地密文/暂存/TV授权。
- 新授权未提供可判断scope、既有凭据不可读或needs_reauth：撤临时流程，已确认照片保本人私有副本，撤家庭共享及TV；不宣称暂时错误等于用户要求删除。
- owner/provider/client/subject发生可信写入变化时调用identity_changed清来源副本。现有OAuth回调仍禁止把已绑定身份换成他人；refresh提交还会比较当前owner/provider/client/subject/tokens/needs_reauth，拒绝用过时grant覆盖并发变更。
- 每次真实媒体权限转变同步提高settings.meta revision，供客户端更新；正常refresh不产生这项撤回变化。

接入位置包括普通同步`active_provider`的refresh提交、`photos_access_token`的refresh提交、OAuth回调账户保存、`failure(reauth=True)`和`disconnect`。解绑在删账户/同步源前于同一事务调用`on_account_removed`；引擎schema另有账户DELETE兜底trigger。用户路由先捕获成员context，等待账号锁后在删除事务里重新核对，撤销浏览器会话不会因先前g.actor还有效而继续解绑。原云日历/待办源选择和刷新行为继续回归。

`/api/accounts` 新增 `capabilities.sync` 布尔字段，与已有 `photos` 并列：明确照片only grant为false，具备既有同步所需scope为true；历史未记录scope的grant保留原发现来源能力，不宣称远端权限已实时验证。needsReauth仍独立呈现。UI应解释显式解绑会清该来源本地精选，Google原件不变。

## Docker与源码打包

Dockerfile加入 `google_photos_picker.py,media_crypto.py,media_images.py,household_media.py,media_import_worker.py`。沿用现有cryptography/Pillow依赖，没有新增包。

`compose.yaml` 新增独立 `media` 服务：与app/sync同一`family-dashboard-app`镜像及`.env`，相同`household-data:/data`卷；命令`python -B media_import_worker.py`，read_only、/tmp tmpfs、no-new-privileges、384MiB内存上限、360秒停止宽限，依赖app健康。图片解码与HTTP不占web请求worker。进程异常退出由持久租约恢复，未知Picker创建不自动重发。

`deploy/prepare_release.py` 明确白名单包含上述五文件，实际合成源码打包测试读取tar确认都在archive且不含test-results。其它历史43/44表发布控制器和schema门禁保持原边界；本候选没有运行旧迁移，没有把“Compose config可解析”称作镜像构建/运行或生产验证。

SQLite BLOB随同一数据库一致性备份；47表（最终叠TV为48）迁移/恢复及既有会话失效验证仍需独立发布步骤。删除只清当前逻辑BLOB，不保证擦除旧页/历史备份。密钥需保持稳定并与备份恢复策略配套。

## 验证边界

新增`tests/test_media_runtime.py`使用真实工厂/成员Cookie/Photos OAuth替身/Picker transport/Pillow/Fernet/SQLite，涵盖双户四成员、真实TV配对、自动注册、worker→HTTP确认→restart、scope下降/正常refresh、来源解绑原子性和回滚、成员撤销竞态、身份/refresh CAS、TV secret在请求入口后旋转、CSRF/照片only与calendar/tasks兼容，以及源码包依赖。

原`test_household_media` fixture仅在extension缺失时手工注册，兼容独立引擎分支与工厂接线；原OAuth三处完整capabilities断言只补sync期望，业务断言未移除。组合回归同时跑这两组、`test_cloud_accounts`和`test_media_import_worker`。原生产env/账户/数据卷均不读取；Compose验证用ignored目录里的固定合成env，不启动服务。真实Google OAuth、实际媒体、物理电视、Docker运行/生产部署属于后续独立验收。
