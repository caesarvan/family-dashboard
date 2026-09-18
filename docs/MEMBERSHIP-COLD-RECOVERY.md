# 默认家庭库缺失时的冷启动恢复

本修订针对真实合成复现：平台 registry 已存在，默认 `household.sqlite3` 被移走后，旧 `create_app` 仍初始化新库，从配置重新建立 `member1/member2`，导致个人账户看见的旧 membership 无法对应原数据。移走的库并未被覆盖，但新空库会掩盖存储故障。热实例的缺库测试没有覆盖此冷启动路径。

实现限于 [app.py](../app.py) 和 [household_spaces.py](../household_spaces.py)；回归见 [test_membership_cold_recovery.py](../tests/test_membership_cold_recovery.py)。不新增表、迁移、API 或个人账户授权方式。

`create_app` 在已有平台库而默认库缺失时，于任何默认库连接、initialize、模块注册之前返回恢复模式。该 app 只注册原公开前端入口及独立个人账户平台；静态文件规则与安全响应头从原函数抽出共用，路径白名单不扩大。真实 `/app` 及其允许的导出仍可加载；默认家庭 API 与 health 为 503。个人账户登录及所属家庭目录继续使用平台认证、CSRF、代次和真实户内成员校验，可明确切换到存在的子家庭。

`HouseholdPlatform.child(default)` 同时检查默认库存在与恢复模式标记。同步 worker 和媒体 worker 沿现有加载失败分支跳过默认家庭，不获得业务模块或触发初始化；有效子家庭仍正常加载。携带旧默认成员 cookie 的 `/space/...` 无法安全撤销原会话时返回 503，既不尝试不存在的 session 扩展而造成 500，也不把原 cookie 交给目标家庭。独立个人账户切换继续使用现有的失效代次及新派生凭据。

恢复模式不会在默认库文件重新出现后自动接管。控制器须核验恢复完整性并重新启动应用，才能按正常初始化/兼容升级路径使用原库。首次安装（尚无平台库）仍初始化两位原成员；已有默认库的常规启动、用户/password/角色/私有 owner 和原 schema 升级路径保持。

实际证据在作者树独立 `test-results/`：基线 `membership-cold-baseline-r1` 的真实 Flask/SQLite 单项确认默认库被重建，1 FAIL，JUnit SHA `de5d09b06c022439231369a28d24bd1d2790abb839f6a4e84b63515f392f64af`。失败原件保留，修复后专项与必要兼容回归另留记录；不把失败轮改写为通过。

修复后 `membership-cold-fixed-r1` 一次实际 **89 PASS，62.63 秒，零失败/错误/跳过**：新冷启动 12 项、原成员集成 17、家庭空间 9、前端运行 42、基础 app 8、同步调度 1。JUnit SHA `f146d285c4b1106b831f9cbdc0b84e6047af398b7ce317a0b70e009221288b3c`，执行记录 SHA `37fc29da7088765470370a93fd32560ed1e0cad0b0d36cd97f1b4168513c49b5`；351 个 Python 输入前后散列一致，stderr 为空。另以 AST 精确核验原 `initialize`、`index`、`asset` 及抽出共用的响应 header 函数逻辑保持。

专项以合成两户、真实旧成员证明/个人注册/邀请加入/登录/切换及实际 cookie 构造，覆盖原库散列保持、公开 shell、静态拒绝、默认 API 503、旧 cookie 路由、worker 跳过、有效子户、恢复后重启和首次安装。所有 socket 连接均禁止；没有成功业务响应 mock、真实私人数据、生产库或浏览器执行。本修订的真实界面补验须在固定源码独立审查后，使用已有恢复脚本仅补先前失败的冷启动组。
