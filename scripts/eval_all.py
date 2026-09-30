# -*- coding: utf-8 -*-
r"""全类别抽测 YOLO 检测模型，输出每类正确率和总正确率

输入: ml\data\raw\plantvillage\（39 个类别文件夹，每类随机抽 N_PER_CLASS 张，随机种子固定 42）
权重: ml\exports\yolo11s-plantvillage38-v1.pt
报告: ml\exports\eval-report-yolo11s-plantvillage38-v1.txt

判定口径: 取一张图中置信度最高的检测框类别，与所在文件夹名比对。
         38 个病害/健康类计入正确率；Background_without_leaves 在模型中没有对应类别，
         其"未检出"视为正确拒识（不计入 38 类的正确率分母）。
"""
import glob
import os
import random
import sys
import time

import cv2
import numpy as np
from ultralytics import YOLO

ROOT = r"D:\Gpt\crop-doctor\ml\data\raw\plantvillage"
CKPT = r"D:\Gpt\crop-doctor\ml\exports\yolo11s-plantvillage38-v1.pt"
N_PER_CLASS = 8          # 每类抽测张数
OUT = r"D:\Gpt\crop-doctor\ml\exports\eval-report-yolo11s-plantvillage38-v1.txt"


def imread_cn(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


model = YOLO(CKPT)
names = model.names
lines = []

total = correct = no_det = 0
class_dirs = sorted(d for d in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(d))
print(f"共 {len(class_dirs)} 个类别，每类抽 {N_PER_CLASS} 张...\n")

for d in class_dirs:
    truth = os.path.basename(d)
    files = []
    for e in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"):
        files += glob.glob(os.path.join(d, e))
    random.seed(42)
    random.shuffle(files)
    files = files[:N_PER_CLASS]

    c_ok = c_no = c_total = 0
    wrong_to = {}
    for f in files:
        img = imread_cn(f)
        if img is None:
            continue
        c_total += 1
        res = model.predict(img, conf=0.25, verbose=False)[0]
        if len(res.boxes) == 0:
            c_no += 1
            continue
        top = max(res.boxes, key=lambda b: float(b.conf))
        pred = names[int(top.cls)]
        if pred == truth:
            c_ok += 1
        else:
            wrong_to[pred] = wrong_to.get(pred, 0) + 1

    total += c_total
    correct += c_ok
    no_det += c_no
    acc = c_ok / c_total if c_total else 0
    extra = ""
    if wrong_to:
        extra = "  误判为: " + ", ".join(f"{k}×{v}" for k, v in sorted(wrong_to.items(), key=lambda x: -x[1]))
    line = f"{truth:<55s} 正确 {c_ok}/{c_total} ({acc:.0%})  未检出 {c_no}{extra}"
    print(line)
    lines.append(line)

summary = f"\n总计: {correct}/{total} = {correct/total:.1%}   未检出 {no_det} 张   (背景类未检出=正确)"
print(summary)
lines.append(summary)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(f"YOLO 全类别抽测报告  每类 {N_PER_CLASS} 张  conf=0.25\n")
    f.write(f"模型: {CKPT}\n\n")
    f.write("\n".join(lines))
print(f"\n报告已保存: {OUT}")
