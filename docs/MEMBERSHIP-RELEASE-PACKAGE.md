# 成员关系候选打包契约

`deploy/membership_release_package.py` 是新的本地源包构造／核验入口，不继承多代字符串替换操作器。它不导入应用、不初始化数据库、不安装依赖、不执行 Docker、SSH、备份或部署。上层操作器另行负责容器构建、验证、迁移和激活；打包成功不是这些阶段通过。

当前已安装父身份固定为 manifest `db3a984f570d38b88c62cb040181f3b4f9d812ace04193ac21c509f899c4c246`、镜像 `sha256:09f583b81f5782ceebc008995665fe095ac6ef0822302bc9b5d84ab3aa3f42f2`。这些是本包预期父身份，上层必须重新核实际生产匹配，脚本不联网证明它们。

## 输入与结果

Python 接口 `inspect_inputs(repo, commit, export_dir, build_evidence, evidence_sha256)` 只读；`prepare(..., output_dir)` 排他创建新目录。`repo` 必须 HEAD 等于明确 40 位 commit 且完全干净，源码、证据、导出和输出均禁止链接／junction。候选文件从固定 Git blob 批量读取，逐项与工作文件比较；`prepare_release.py` 的已审 FILES/FOLDERS 白名单以 AST 读取，不运行它。保留私人凭据、数据库、环境文件、test-results、bytecode 排除，并禁止生成导出被 tracked。

`required_build_inputs(tracked_paths)` 返回所有 tracked `frontend/**`，仅排除精确 `frontend/README.md`、`frontend/LICENSE`、`frontend/.gitignore`。包括 src/public、package 与 lock、app.json、两份 tsconfig、typecheck.mjs 和 frontend/tests。构建证据必要字段为：

```json
{
  "schemaVersion": 1,
  "kind": "membership-expo-build",
  "head": "完整构建提交",
  "tree": "完整构建树",
  "buildExit": 0,
  "bundleMarkers": true,
  "inputFiles": {"frontend/相对输入": "sha256"},
  "files": {"相对导出路径": "sha256"}
}
```

可附构建时间与日志 SHA。inputFiles 必须与构建 Git、候选 Git 的精确集合及字节一致；两个提交可以不同，但不能仅以祖先关系代替输入验证。导出固定完整 23 文件，必须有 index.html、metadata.json 及唯一 entry JS；Windows 使用扩展路径完整枚举，不用可能截断的普通 rglob。依赖、Dockerfile、Compose、nginx、白名单和 Git reader 固定为本次基线 `7b5b2c3b14b5727484fa6558e4e3a21074c4435a` 的已核字节，变化需独立修订审查。

输出只有 `release.tar.gz`、`release-manifest.json`、原样 `build-evidence.json`、`package.json` 四件。归档根 `RELEASE-MANIFEST.json` 与外部 release-manifest.json 同字节，保留 `files:{relative:sha256}` 兼容现有生产读回。package.json 含 archiveSha256/manifestSha256、sourceHead/tree、sourceFiles/exportFiles/runtimeFiles、固定配置、完整构建输入和脚本身份。runtimeFiles 是包中根级 Python、requirements 与 static 全集；是否真正加载到镜像须上层独立核验。

`verify_package(output_dir, package_sha256)` 不写文件、不提取归档；校验外部授权 metadata SHA、全压缩包／manifest／证据、所有 tar 成员，拒绝重复／大小写碰撞、链接、穿越、异常权限、超限和非白名单项，返回 `{metadata, manifest, blobs}`。上层安全提取应仅使用返回的已核 blobs，并继续确保自己的新目标目录和文件写入安全，不能直接信任未经核验的 tar。

```powershell
python -B deploy/membership_release_package.py prepare --repo <clean-root> --commit <40hex> --export-dir <dist> --build-evidence <json> --evidence-sha256 <64hex> --output-dir <new-directory>
python -B deploy/membership_release_package.py verify --output-dir <directory> --package-sha256 <64hex>
```

写包前及写完后均重新读取输入，最后读回所有归档成员及结束标志后的尾部；竞态失败保留未封口原件，不覆盖或盲目重放。没有 package.json 的目录不构成完成候选。专项测试使用真实临时 Git／文件／tar，合成源码与导出；不是实际 Expo 构建或生产容器验证。

作者实测首轮 22／22 通过（66.44 秒），XML SHA `dc802152fbc99632fa86da8b3de8f36aacbb6990ccbcb23b5c5d1399c4487546`。随后新增归档尾部拒绝守卫及对应测试，只运行受影响的完整读回、恶意归档、长路径共 8 项，8 通过／15 未选择（36.54 秒），XML SHA `c27f939d372a8c1fe7799024cfc13124838c46d0c555ed7793adb2977d2f5519`。两轮均无失败／错误／skip，源码前后相同；不是最终 23 项同轮全跑。原件各在作者树 `test-results/membership-package-r1/`、`membership-package-r2/`。没有实际业务包／容器／远端执行。
