# -*- coding: utf-8 -*-
r"""把被解压成文件夹的 PyTorch 权重重新打包回 .pt 文件

一次性迁移工具：当年 yolo_best.pt 被误当成压缩包解压成了文件夹，用此脚本还原回单个 .pt。
下方 src / dst 是当时一次性使用的硬编码路径，再次使用时请先改成当前的实际路径。
"""
import os
import zipfile

src = r"d:\download\数据集\model\best"
dst = r"d:\download\数据集\yolo_best.pt"

files = []
for root, dirs, names in os.walk(src):
    for n in names:
        full = os.path.join(root, n)
        rel = os.path.relpath(full, src).replace("\\", "/")
        files.append(rel)

# data.pkl 必须是第一个写入的记录，其余按原结构写入
files.sort(key=lambda x: (x != "data.pkl", x))

with zipfile.ZipFile(dst, "w", zipfile.ZIP_STORED, strict_timestamps=False) as zf:
    for rel in files:
        # torch 打包时内部路径带一层与文件名同名的前缀（这里是 "best/"）
        zf.write(os.path.join(src, rel), arcname="best/" + rel)

print(f"打包完成: {dst}  共 {len(files)} 个内部文件")
