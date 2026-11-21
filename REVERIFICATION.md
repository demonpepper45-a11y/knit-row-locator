# 第二轮复验记录：末行修复、CLI 基线与实拍准备

- 日期：2026-11-21（Asia/Shanghai）
- 仓库：`demonpepper45-a11y/knit-row-locator`
- 基线提交：`4c574ac4036f296f3d229ee5b6ac4850281aa291`
- 工作分支：`feat/knitalign-research-baseline`
- 本轮实现提交：`59f94a32016c5c8f82949ac946973d968571e2c7`

## 1. 复现第一版

实际命令（项目根目录）：

```powershell
git clone https://github.com/demonpepper45-a11y/knit-row-locator.git
git -C knit-row-locator log -1 --format=%H
git -C knit-row-locator switch -c feat/knitalign-research-baseline
python -m pytest -q
```

结果：

- 克隆成功，`main` 当前提交为 `4c574ac4036f296f3d229ee5b6ac4850281aa291`，
  与任务给出的已核验提交一致。
- 分支 `feat/knitalign-research-baseline` 创建成功。
- 第一版测试：**70 passed in 3.88s**（Python 3.12，numpy 2.5.5，
  opencv-python-headless 5.1.0.95，streamlit 1.67.0，pytest 9.2.0）。
- 本轮在仓库内新建 `.venv` 并按 `requirements.txt` 安装成功（同一组版本）；
  安装后全套测试为 **81 passed in 9.95s**，是下文最终测试结果的来源。
- 访问私有仓库使用本机已登录的 GitHub 账号 `demonpepper45-a11y`（owner），
  未发生权限阻塞。HTTPS 克隆需显式提供令牌/OpenSSL 后端；命令中未写入任何令牌。

第一版说明阅读范围：`README.md`、`ACCEPTANCE.md`、`tests/`、
`examples/README.md`、`core/config.py`。仓库内未附《KnitAlign 研究项目执行书》；
本轮按工作区 `outputs/KnitAlign-研究项目执行书.md` 的步骤 01–05 范围执行
（基线、数据协议、评测口径），未开展形变/时序研究。

## 2. 验收问题的修复

### 2.1 多候选末行显示

问题：演示二切到第 28–32 行时，界面用全局 `match_result.chart_complete`
（排名第一的候选）判断，显示不存在的“下一行 33”。

修复：

- 新增 `core/progress.py::candidate_progress`，按**当前选中候选**判断末行。
- `app.py` 的“下一行”指标、完成提示、图解说明全部改用候选级结果：
  - 多候选且当前候选到末行：`若此候选正确，图解已完成`；
  - 唯一候选到末行：`图解已完成` / `next_row = None`；
  - 其他候选：正常显示下一行。
- `MatchResult.chart_complete` 与 `MatchResult.next_row` 保留但文档明确：
  仅描述排名第一的候选，多候选必须用候选级判断。

复验结果（Streamlit AppTest，真实控件树）：

| 操作 | 修复前 | 修复后 |
|---|---|---|
| 演示二选第 28–32 行 | 最近完成 32，下一行 33 | 最近完成 32，下一行“若此候选正确，图解已完成”，无 33 |
| 切回第 20–24 行 | 下一行 25 | 下一行 25 |
| 唯一候选覆盖第 28–32 行 | 未单独验证 | “图解已完成”，`next_row = null` |

证据测试：`tests/test_progress.py`（3 项）、`tests/test_app.py` 中的末行切换与
临时末行唯一案例。临时案例由 `chart1` 最后 5 行生成照片，仅用于测试，不进入交付样例。

### 2.2 未经实拍验证的吻合度表述

已删除“正常实拍吻合度常在 85%–97%”一类表述，统一为：

- 干净合成样例接近 1.0；
- **实拍吻合度尚无配对实测数据**；
- `0.82` 是待实拍校准的保守初始值，随机双色期望约 0.5。

修改位置：`app.py` 的分数说明、`README.md` 阈值表、`core/config.py` 的模块说明。
`grep -R "85%\|97%\|正常实拍"` 无残留。

## 3. 可复现研究基线（CLI）

新增 `cli.py`，复用 `core/pipeline.py` 与同一套阈值，不复制匹配逻辑。

```powershell
python cli.py --all --scenarios
python cli.py --all --scenarios --json --out docs/baseline_results.json
python cli.py --case case2_repeat --row-range 20-26 --json
python cli.py --manifest data/real_round1/manifest.json --json
```

运行产物：

- `docs/baseline_results.json`：完整结构化结果（配置、来源、预期、候选、得分、
  覆盖率、差异格、耗时、环境）。
- `docs/baseline_results.txt`：同一次运行的文本摘要。

实际输出（2026-11-21，合成素材）：

| 案例 | 状态 | 候选窗口（一基） | 最近完成行 | 下一行 | 得分 | 覆盖率 |
|---|---|---|---|---|---|---|
| case1_unique | unique | 19–23 | 23 | 24 | 1.000 | 100% |
| case1_unique + 范围 20–26 | unique | 19–23 | 23 | 24 | 1.000 | 100% |
| case2_repeat | multiple | 4–8、12–16、20–24、28–32 | 8、16、24、32 | 9、17、25、若此候选正确已完成 | 1.000 | 100% |
| case2_repeat + 范围 20–26 | unique | 20–24 | 24 | 25 | 1.000 | 100% |

验收口径：

- `case1_unique`：最近完成 23、下一行 24；
- `case2_repeat`：候选集保留最近完成 8、16、24、32；
- 限定 20–26 后只保留最近完成 24；
- 重复案例的 `expected_check.comparison = candidate_set`，按候选集比较，
  不把任一并列候选当成唯一真值。

CLI 与界面一致性：`tests/test_cli.py::test_cli_and_pipeline_produce_same_candidates`
对同一案例/范围比较 CLI 与 `core.pipeline.run_case` 的候选窗口和分数；界面演示也调用
`run_case`，因此两者使用同一配置与算法。

单次运行耗时（同一台机器，包含图像读取；不是基准测试）：
case1 82.6 ms、case1 范围 41.3 ms、case2 41.0 ms、case2 范围 40.9 ms。
**这些是合成输入的观测值，不能当作实拍或生产性能结论。**

## 4. 第一轮实拍验证准备

当前仓库与工作区**没有配对实拍素材**，因此：

- 未运行任何实拍样本；
- 没有实拍定位准确率、错报率、覆盖率或耗时数字；
- 实拍定位能力保持**待验证**。

已交付可直接填写的材料：

| 文件 | 用途 |
|---|---|
| `docs/real_photo_capture_template.md` | 采集流程、真值防泄露、四角协议、验收分类、数据划分规则 |
| `docs/real_photo_capture_template.csv` | 逐样本记录表（UTF-8 BOM，可直接用 Excel 打开） |
| `docs/real_photo_manifest_template.json` | 可直接传给 `cli.py --manifest` 的样本清单模板 |
| `data/README.md` | 本地实拍目录、授权与“同一图解同组划分”约定 |

CLI 的 manifest 模式已用合成样例走通（`tests/test_cli.py` 中的 `S1/S2/S3`）：
- 唯一正确 → `unique_correct`；
- 多个候选覆盖真值 → `multiple_covers`；
- 范围限定后唯一正确 → `unique_correct`。

实拍验收分类沿用采集模板：`unique_correct` / `multiple_covers` /
`unique_wrong` / `refused` / `input_error`。失败样本（尤其 `unique_wrong`）
必须保留原图、选区、角点和输出。

补测材料清单：同一织片的原始双色图解、完整宽度正面照、拍摄时独立记录的
停织行号（编织者笔记/可移除行标/计数器/双人读数）、拍摄条件、四角坐标。
建议 3 块织片 × 每块至少 4 个停织位置，优先包含重复图案与非重复图案。

## 5. 测试与证据汇总

最终测试：**81 passed in 9.95s**（新建 `.venv` 安装依赖后运行；完整输出 `docs/pytest_output.txt`）。

| 测试文件 | 数量 | 本轮新增内容 |
|---|---:|---|
| `tests/test_types.py` | 5 | — |
| `tests/test_chart.py` | 8 | — |
| `tests/test_photo.py` | 10 | — |
| `tests/test_match.py` | 22 | — |
| `tests/test_samples.py` | 11 | — |
| `tests/test_app.py` | 6 | 末行候选切换、唯一候选到末行的临时案例 |
| `tests/test_robustness.py` | 9 | — |
| `tests/test_progress.py` | 3 | 候选级末行与下一行 |
| `tests/test_cli.py` | 7 | JSON、范围、场景、CLI/管线一致、文本、manifest、错误 |
| **合计** | **81** | |

证据边界：

- 合成实验：上述两个案例、变体素材与单元测试；
- 实拍实验：**无**；
- 仍待验证：真实织片的定位效果、阈值在实拍上的校准、局部照片/形变/多帧研究问题；
- 界面验证：Streamlit AppTest 控件级测试，未进行人工浏览器体验评估；
- 性能：仅报告单机单次 CLI 耗时与测试耗时，未做 P95 或对照基准。

## 6. 交付与复现

```powershell
cd knit-row-locator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python cli.py --all --scenarios --json --out docs/baseline_results.json
python -m streamlit run app.py
```

- 分支：`feat/knitalign-research-baseline`
- 基线提交：`4c574ac4036f296f3d229ee5b6ac4850281aa291`
- 本轮实现提交：`59f94a32016c5c8f82949ac946973d968571e2c7`
- 本记录提交：分支 HEAD（见最终回复）
- PR：https://github.com/demonpepper45-a11y/knit-row-locator/pull/1（待项目负责人审核）
