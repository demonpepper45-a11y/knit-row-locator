# KnitAlign 第一轮实拍采集与验收模板

> 状态（2026-11-21）：仓库内**没有配对实拍素材**，本模板用于下一轮采集。
> 在拿到“同一织片的原图解 + 完整宽度正面照 + 独立记录的停织行号”之前，
> 实拍定位能力保持**待验证**，不得用合成结果代替实拍指标。

## 1. 本轮目标

- 最小可用：1 个图解 + 1 块织片 + 1 个已知停织行号，走通采集、标注、CLI 运行和失败记录。
- 建议目标（研究执行书 02）：3 块织片，每块至少 4 个已知停织位置；优先包含
  一组重复图案和一组非重复图案。
- 每个样本至少包含：原始双色图解、同一织片完整宽度正面照、独立真值、四角选区、
  可见行数/针数、拍摄条件、系统输出、是否需要重选角点。

## 2. 标识与分组

| 层级 | 示例 | 说明 |
|---|---|---|
| 图解 | `chart_A` | 同一原始图解的所有样本同组 |
| 织片 | `piece_A1` | 同一图解可织多块；不同织片不要混为同一独立样本 |
| 拍摄会话 | `session_20261121_01` | 同一停织位置可拍多张 |
| 帧 | `frame_0003` | 单张照片；一张照片一个样本 |
| 样本号 | `R001` | 写入 CSV 与 manifest 的主键 |

文件命名建议：`data/real_round1/photos/<piece_id>/<session_id>/<frame_id>.jpg`，
图解放 `data/real_round1/charts/<chart_id>/original.png`。原始文件只读，派生图另建目录。

## 3. 真值采集（避免泄露）

停织行号必须**独立于系统输出**记录，不能根据程序结果反填。推荐任一方式并写清来源：

1. 编织者在停织时当场记录“最后完整行”的行号，并签名/日期。
2. 在织片上放置可移除的行标（如别针+编号纸），先拍一张“标定照”记录真值；
   正式推理照移除行标后再拍，确保输入不含答案。
3. 使用编织机/计数器的行数记录，截图或拍照留存。
4. 两人独立读数，分歧处由第三人裁决，记录分歧。

同一停织位置建议拍 2–3 张（正面、轻微角度、不同光照），但**真值只记一次**。
不要把带行标、带手写答案或文件名含行号的照片作为推理输入。

## 4. 拍摄条件

- 正面朝相机，针杆在上；完整宽度（左右最外针都在画面内）；上下可超出。
- 平铺在纯色、无纹理背景上；避免手指、阴影、强反光和褶皱压住针目。
- 对焦清楚；尽量让每格在照片中至少 8×8 像素（低于 3×3 会被程序拒绝）。
- 记录设备、分辨率、光源（自然光/室内灯）、是否使用闪光灯、拍摄距离、角度。
- 记录织片状态：平整 / 局部拉伸 / 弯曲 / 遮挡；是否刚拆过线。
- 记录线材颜色（最好给 RGB 或色号）与花纹周期（如果已知）。

## 5. 四角与行列数

1. 在界面上按 **左上 → 右上 → 右下 → 左下** 标四角。
2. 上边贴着**最新完成整行**的上边缘；下边落在**更早一整行**的下边缘。
3. 可见完整行数 = 两条边之间的行数；针数 = 照片中织片完整宽度针数。
4. 先看界面里的“白点”采样位置；若偏到网格线/相邻针，重选角点或调整选区。
5. 记录首次角点、是否重选、重选原因（模糊/倾斜/遮挡/选错行）。

## 6. 逐样本记录字段

CSV 模板见 [`real_photo_capture_template.csv`](real_photo_capture_template.csv)。核心字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `sample_id` | 是 | 主键，如 `R001` |
| `group_id` | 是 | 图解分组，如 `chart_A` |
| `chart_file` / `chart_sha256` | 是 | 原始图解路径与哈希 |
| `chart_rows` / `chart_stitches` | 是 | 图解行列数 |
| `photo_file` / `photo_sha256` | 是 | 推理用原图路径与哈希 |
| `actual_last_completed_row` | 是 | 独立记录的真值行号（一基） |
| `truth_source` | 是 | `weaver_note` / `removable_marker` / `counter` / `two_person` |
| `visible_rows` / `photo_stitches` | 是 | 四角之间的完整行数、完整宽度针数 |
| `corners_tl_x/y` 等 8 个 | 是 | 四角像素坐标 |
| `capture_date` / `device` / `lighting` | 是 | 拍摄条件 |
| `deformation` / `occlusion` | 是 | 平整/拉伸/弯曲；遮挡描述 |
| `row_range` | 否 | 若使用“最近完成行范围”，填 `20-26` |
| `system_status` | 运行后 | `unique` / `multiple` / `insufficient` / `input_error` |
| `candidate_last_completed_rows` | 运行后 | 全部候选的最近完成行，如 `8;16;24;32` |
| `next_rows` | 运行后 | 每个候选的下一行；末行候选记 `completed` |
| `best_score` / `coverage` / `diff_cells` | 运行后 | 实际输出 |
| `reselected_corners` | 运行后 | 是否重选角点及原因 |
| `outcome` | 运行后 | `unique_correct` / `multiple_covers` / `unique_wrong` / `refused` / `input_error` |
| `notes` | 否 | 失败现象、遮挡、异常 |

## 7. 用 CLI 运行

把样本写入 manifest（模板见 [`real_photo_manifest_template.json`](real_photo_manifest_template.json)）：

```powershell
python cli.py --manifest data/real_round1/manifest.json --json `
  --out reports/real_round1/predictions.json
```

输出中每个样本包含 `result.candidates`、`ground_truth_check.outcome`、得分、
覆盖率、差异格数和耗时。`ground_truth_check` 的口径：

- `unique_correct`：唯一回答且等于真值；
- `multiple_covers`：候选集包含真值（允许保留歧义）；
- `unique_wrong`：错误地给出了唯一行号（必须保留失败样本）；
- `refused`：系统拒绝给出行号（不计为错误唯一回答，但未自动回答）；
- `input_error`：尺寸/输入错误，未产生行号。

重复花纹以**候选集覆盖真值**验收，不要求任一并列候选被标为唯一真值。

## 8. 验收与划分

- 同一 `group_id`（同一图解）的所有照片、裁剪、亮度/旋转派生样本必须放在同一
  train/val/test 划分；序列不拆散。
- 报告每个划分的独立图解数、织片数、帧数；不要把同一织片的几十张照片算成几十个独立样本。
- 首次实拍只报告描述性结果，不在样本不足时声称统计显著性。
- 失败样本（`unique_wrong`、`multiple_misses`、`refused`）逐例保留图、选区、角点、输出与原因。
- 至少 10% 帧做盲重复标注，记录分歧与裁决。

## 9. 本轮交付状态

- 采集模板：本文件 + CSV + manifest 模板。
- 实拍素材：**不可得**（仓库与工作区均无配对材料）。
- 实拍实验：未运行，无实拍性能数字。
- 合成实验：见 [`REVERIFICATION.md`](../REVERIFICATION.md) 与
  [`baseline_results.json`](baseline_results.json)。
