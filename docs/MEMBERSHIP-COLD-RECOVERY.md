# 默认家庭库缺失时的冷启动恢复

本修订针对真实合成复现：平台 registry 已存在，默认 `household.sqlite3` 被移走后，旧 `create_app` 仍初始化新库，从配置重新建立 `member1/member2`，导致个人账户看见的旧 membership 无法对应原数据。移走的库并未被覆盖，但新空库会掩盖存储故障。热实例的缺库测试没有覆盖此冷启动路径。

实现限于 [app.py](../app.py)、[household_spaces.py](../household_spaces.py) 和 [membership_http.py](../membership_http.py)；回归见 [test_membership_cold_recovery.py](../tests/test_membership_cold_recovery.py)。不新增表、迁移、API 或个人账户授权方式。

`create_app` 在已有平台库而默认库缺失时，于任何默认库连接、initialize、模块注册之前返回恢复模式。该 app 只注册原公开前端入口及独立个人账户平台；静态文件规则与安全响应头从原函数抽出共用，路径白名单不扩大。真实 `/app` 及其允许的导出仍可加载；默认家庭 API 与 health 为 503。个人账户登录及所属家庭目录继续使用平台认证、CSRF、代次和真实户内成员校验，可明确切换到存在的子家庭。

`HouseholdPlatform.child(default)` 同时检查默认库存在与恢复模式标记。同步 worker 和媒体 worker 沿现有加载失败分支跳过默认家庭，不获得业务模块或触发初始化；有效子家庭仍正常加载。携带旧默认成员 cookie 的 `/space/...` 无法安全撤销原会话时返回 503，既不尝试不存在的 session 扩展而造成 500，也不把原 cookie 交给目标家庭。独立个人账户切换继续使用现有的失效代次及新派生凭据。

恢复模式不会在默认库文件重新出现后自动接管。控制器须核验恢复完整性并重新启动应用，才能按正常初始化/兼容升级路径使用原库。首次安装（尚无平台库）仍初始化两位原成员；已有默认库的常规启动、用户/password/角色/私有 owner 和原 schema 升级路径保持。

独立审查进一步实际发现：原库放回但未重启时，`child(default)` 正确拒绝恢复实例，但个人目录/切换及带旧电视 cookie 的账户读取未将该拒绝归一，产生 500。复现原件 `membership-cold-recovery-restored-probe-r1.json` SHA `a839f5fe8b1eae1c08110b1c2fa7c25af1d2f62c6db72f10c8b039642df4da93` 保留。后续 HTTP 适配层同时检查文件与恢复标记，将默认户列为 `unavailable`、直接切换默认户返回受控 503；旧 TV 探测不阻断个人登录，切有效子户不打开尚未重新加载的原默认库。显式 `X-Display-Mode: tv` 仍拒绝，恢复标记不随文件出现自动解除。

实际证据在作者树独立 `test-results/`：基线 `membership-cold-baseline-r1` 的真实 Flask/SQLite 单项确认默认库被重建，1 FAIL，JUnit SHA `de5d09b06c022439231369a28d24bd1d2790abb839f6a4e84b63515f392f64af`。失败原件保留，修复后专项与必要兼容回归另留记录；不把失败轮改写为通过。

修复后 `membership-cold-fixed-r1` 一次实际 **89 PASS，62.63 秒，零失败/错误/跳过**：新冷启动 12 项、原成员集成 17、家庭空间 9、前端运行 42、基础 app 8、同步调度 1。JUnit SHA `f146d285c4b1106b831f9cbdc0b84e6047af398b7ce317a0b70e009221288b3c`，执行记录 SHA `37fc29da7088765470370a93fd32560ed1e0cad0b0d36cd97f1b4168513c49b5`；351 个 Python 输入前后散列一致，stderr 为空。另以 AST 精确核验原 `initialize`、`index`、`asset` 及抽出共用的响应 header 函数逻辑保持。

审查增量后 `membership-cold-restored-fixed-r2` 单独 **6 PASS，14.02 秒，零失败/错误/跳过**：新四个无 cookie／旧成员／旧 TV／两者组合，以及原缺库恢复、普通双户切换两项兼容。JUnit SHA `0b0524099c32bda154768ab8581644d9026aa1425c69cd869d259b3001f3f3b9`，record SHA `007cb64c17719b4ae96125fbad64914337c35f5b3eb5ec18f2452203e2e4eb57`；351 个 Python 输入前后相同，stderr 空。未重新执行整轮 89 项，也未将两轮计数相加冒称一次最终全量通过。

专项以合成两户、真实旧成员证明/个人注册/邀请加入/登录/切换及实际 cookie 构造，覆盖原库散列保持、公开 shell、静态拒绝、默认 API 503、旧 cookie 路由、worker 跳过、有效子户、恢复后重启和首次安装。所有 socket 连接均禁止；没有成功业务响应 mock、真实私人数据、生产库或浏览器执行。本修订的真实界面补验须在固定源码独立审查后，使用已有恢复脚本仅补先前失败的冷启动组。
