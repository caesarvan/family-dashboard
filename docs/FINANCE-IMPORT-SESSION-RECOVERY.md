# 财务来源导入：会话与未知结果恢复

本候选只调整 `finance_source_bridge.py`、`spending_observations.py` 的现有 status／preview／confirm；无新表、路由、依赖或金额算法。尚未部署。完整资产基线与独立消费观察仍使用各自的回执、版本和来源摘要；消费观察继续核对两条版本线，不写资产、共享汇总、实付账本或荷包。

## 接口增量

- 两种 preview 原响应增加 `operationId`：签名载荷的稳定 SHA256，等于成功时的 `receiptId`。重试保存原文件、原 token 和原操作 ID，不自动重新预览生成另一操作。
- 原无参数 status 的响应保持。GET `/api/finance-baseline/imports/status?mode=baseline&operationId=<64位小写hex>` 精确查询本人历史；消费观察使用 `mode=spending_observation`。省略 mode 等同 baseline。mode／operationId 不接受重复参数，操作 ID 不接受大小写或长度宽松匹配。
- 精确查询返回 `{mode, operationId, found, receipt}`。found=true 时 receipt 是原确认回执，`replayed=true`；false 时 receipt=null。**false 只表示此刻未查到，不证明请求未在途或可以发起新写入。** 此响应不夹带当前基线；普通 status 另读当前版本。本人新登录可读本人历史，不能据此执行旧会话尚未提交的操作。
- confirm 原请求格式不变。校验签名和原候选、取得当前家庭数据库中的写锁并核验当前真实会话后，按原操作 ID／本人精确查回执；已有回执优先返回，不受原 token 年龄、旧会话或后续基线删除／版本变化影响，也不重建数据。回放释放事务后再次核验当前会话。
- 只有尚无回执时才校验签发年龄 `0..1200` 秒、原会话绑定和原有 CAS。过期返回 HTTP410、`code=preview_expired`；尚未过期的旧 baseline token 缺会话绑定且未提交返回 HTTP409、`code=preview_repreview_required`。其他既有格式／身份／版本错误保持对应 400／401／403／409；所有错误保留 error 字符串。旧消费观察 token 保留原 context 绑定兼容。

历史操作读取不等于当前资产已核实，也不表示来源摘要可以证明银行原文件真实性。签名无效、其他成员、其他家庭和 TV 不获得回执。

## 会话和事务

每次请求捕获实际 member session ID、owner、auth version、credential hash 与家庭身份，缺会话引擎明确503，不退化为仅信任 g.actor。

status／preview 在同一只读快照中读取完整响应，释放快照后重新查实际会话；legacy 凭据可能产生的隐式事务也释放。写入在 BEGIN IMMEDIATE 取得锁后、审计后提交前复核；失败同时回滚基线／观察、回执、审计和共享 revision。预览和回执查询不写业务数据。会话认证自身的既有访问记录不属于业务零写承诺。

客户端遇到网络中断、取消或身份失败时不能从 HTTP 错误猜测未提交；保存原 operationId，恢复本人身份后只读核对。未提交且已过期时重新核对最新来源再明确预览／确认，不能把不存在的历史回执伪装为成功。

## 验证范围

新增 `tests/test_finance_import_sessions.py` 使用真实临时 Flask、HttpOnly cookie、SQLite 双连接和现有配对／家庭路由；只注入时间或真实数据库时序，不替换成功业务响应。覆盖读取途中撤权、锁等待、提交前过期、真实换登录、legacy／空状态、精确历史回执、旧 token、跨成员家庭／TV 和缺会话引擎。

旧来源桥接测试的合成 g.actor 夹具迁移为真实应用／登录，保留金额、来源、CAS、回放及不变性断言；消费观察的临时连接显式关闭。

本分支实际三模块 **216 通过、0 失败／错误／跳过，110.37秒**：新会话专项56、来源桥接106、消费观察54。5份 Python 输入前后 SHA256 相同。原件 `test-results/finance-import-r2.xml` SHA256 `97295e8c1c8ec09cbcc346d4e715fd1658afa17d7226425a97416c309e7a020e`，证据索引 `finance-import-r2-evidence.json` SHA256 `e0fbc873b305df3a11e12ee32663527e378049f1dc9f344895f71afe3fb76ce3`；原件不进入 Git。

首轮专项53通过／1测试失败原件保留：畸形载荷用例误把消费观察初始 revision=0 时合法的 source=null 当成错误，已改为与该版本不匹配的摘要，未放宽产品断言。更早私人研究的清理失败也保留，不作为本候选通过证据。真实来源文件、真实银行／云、前端恢复交互与生产部署均不在本后端专项内。
