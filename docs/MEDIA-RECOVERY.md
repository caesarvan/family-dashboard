# 媒体恢复专项

媒体展示副本在各家庭 SQLite 的加密 BLOB 中，既有 `deploy.backup.backup_all()` 会将平台注册库及每个登记家庭库纳入同一完整组清单。恢复必须保留整个 manifest 及全部引用快照、配对应用密钥；只恢复主户或复制单个清单不构成平台恢复。不同数据库的备份不是跨库原子事务，正式恢复验收先停止写入。

`tests/test_media_restore.py` 使用真实 `create_app`、邀请建立第二家庭、4名成员、真实 SQLite/Pillow/Fernet 与已有媒体 API 创建合成照片。调用原 `backup_all` 生成两户/三库完整组，从 `deploy.rehearse_restore.documented_programs` 提取 `DEPLOYMENT.md` 的原恢复程序，**仅将固定 `/data` 字符串替换为本测试临时目录**后执行平台恢复。未改恢复算法、旧 profile 或 controller，也没有 Docker/生产/真实 Google 请求。

测试逐字节/逐值核对四张媒体表，包括密文 metadata、preview BLOB、private/shared、TV grant 和暂停播放状态；重建工厂后实际解密读取、检查旅行关联、跨成员/跨户/未获许可电视隔离。每个恢复家庭执行原 `MEMBER-SESSIONS.md` SQL，使成员版本增加、会话撤销、浏览器代次推进、进行中 OAuth 清除，实际确认4个旧登录cookie失效。

初始测试 base `c24d84d` 工厂有媒体库但未正式注册播放模块，首轮明确使用播放 fixture 注册。随后以已审 `25c9f20` 工厂运行 `MEDIA_RESTORE_REQUIRE_FACTORY=1` 同一测试通过：source/restored、default/child 四个位置的 `factoryFallback` 都为空；任一位置仍需 fallback 都会失败。此为本地临时SQLite恢复，不是实际Docker恢复或实体电视验收。Linux候选复跑需使用同一实际镜像运行模块，并提供只读测试、deploy辅助模块和原文档；不要把测试源目录置于镜像运行模块之前。

备份只保存快照时刻的权限。**备份之后的删除、解绑、成员登出、照片改私密或TV撤权不会自动写回旧快照。** 原成员失效SQL不会撤销TV配对和照片TV许可；测试实际复现旧备份会带回原有grant，然后明确撤回并验证图片不可再读。恢复服务前必须重新核对或撤回快照里的旧TV许可和播放状态；不能只验证图能显示就开放电视。

实际恢复期间 app、sync、media worker及外部入口应保持停止，先保留残存卷/配置，再核完整组、恢复全部目标、逐户执行原登录失效SQL，并核对相册及旅行关联、来源授权、待处理导入和TV许可。需要app辅助核验时仅在受控成员入口中进行，电视入口及所有worker继续停止；完成授权复核后才恢复展示和worker。未核对的旧导入不得自动续跑，特别是未知Picker创建不允许盲重建。部分恢复失败保持整个平台停止，不启动部分家庭。

逻辑删除不保证擦除SQLite旧页或历史备份。真实恢复还需验证与最终镜像绑定的48表schema、稳定密钥、资源限制、完整组内容及许可复核流程；本专项不替代这些发布门槛。
