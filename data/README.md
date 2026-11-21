# 实拍数据目录（本地）

真实织片照片默认**不提交**到仓库，避免在授权范围未确认时公开原始素材。
本目录只保留说明；采集时在本地创建：

```text
data/real_round1/
├─ manifest.json          # 可直接传给 cli.py --manifest
├─ charts/                # 原始双色图解
├─ photos/                # 原始完整宽度正面照
├─ labels.csv             # 独立真值与拍摄记录
├─ predictions/           # CLI 输出的结构化结果
└─ splits/                # 按图解分组的 train/val/test 清单
```

分组与划分要求：

- 以**原始图解**为分组单位；同一图解的所有照片、裁剪、旋转/亮度派生样本必须留在同一划分。
- 同一织片的连续拍摄序列不得跨划分。
- 同一织片的多张照片只算一个独立设计，不能把几十张照片当成几十个独立实验。
- 至少抽取 10% 的帧做盲重复标注，保留分歧与裁决记录。
- 原始照片、派生图和系统输出分别登记；推理前移除会直接泄露停织行号的标记。

可直接填写的模板见：

- [采集与验收模板](../docs/real_photo_capture_template.md)
- [CSV 记录表](../docs/real_photo_capture_template.csv)
- [manifest 模板](../docs/real_photo_manifest_template.json)

本轮（2026-11-21）仓库内没有配对实拍素材，因此**实拍定位能力仍待验证**；当前结果只来自合成样例。
