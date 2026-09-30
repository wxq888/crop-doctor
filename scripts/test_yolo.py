# -*- coding: utf-8 -*-
r"""
YOLO11s 植物病害检测模型测试脚本（项目检测主线）

用法（任意目录的终端均可，脚本内路径均为绝对路径）:
    # 测试单张图片（路径带空格、括号要加引号）
    python test_yolo.py "D:\某张叶片照片.jpg"

    # 从某个类别文件夹随机抽 20 张测试，并统计正确率
    python test_yolo.py --folder "D:\Gpt\crop-doctor\ml\data\raw\plantvillage\Apple___Apple_scab" -n 20

    # 权重不在默认位置时用 --ckpt 指定；--conf 调置信度阈值（默认0.25）
    python test_yolo.py --ckpt "C:\Users\xxx\Downloads\best.pt" --conf 0.4 "图片.jpg"

默认权重: ml\exports\yolo11s-plantvillage38-v1.pt（38 类）
输出: 带检测框的结果图保存到 ml\runs\yolo11s-detect-v1\，文件名前缀 det_
"""
import argparse
import glob
import os
import random
import sys

import cv2
import numpy as np
from ultralytics import YOLO


def imread_cn(path):
    """读取图片，兼容中文路径"""
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def imwrite_cn(path, img):
    """保存图片，兼容中文路径"""
    ext = os.path.splitext(path)[1] or ".jpg"
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)
    return ok


def main():
    ap = argparse.ArgumentParser(description="测试 YOLO 植物病害检测模型")
    ap.add_argument("images", nargs="*", help="要测试的图片路径（可多张）")
    ap.add_argument("--folder", help="测试整个类别文件夹（随机抽取统计正确率）")
    ap.add_argument("-n", "--num", type=int, default=20, help="从文件夹抽取的图片数，默认20")
    ap.add_argument("--ckpt", default=r"D:\Gpt\crop-doctor\ml\exports\yolo11s-plantvillage38-v1.pt", help="模型文件路径")
    ap.add_argument("--conf", type=float, default=0.25, help="置信度阈值，默认0.25")
    args = ap.parse_args()

    if not os.path.exists(args.ckpt):
        sys.exit(f"找不到模型文件: {args.ckpt}\n默认指向 ml/exports 下的权重，或用 --ckpt 指定路径")
    if not args.images and not args.folder:
        sys.exit('请指定要测试的图片路径，或用 --folder 指定类别文件夹\n示例: python test_yolo.py "D:\\照片.jpg"')

    model = YOLO(args.ckpt)
    names = model.names
    print(f"模型加载成功: {len(names)} 个类别\n")

    # 收集待测图片
    if args.folder:
        files = []
        for e in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"):
            files += glob.glob(os.path.join(args.folder, e))
        if not files:
            sys.exit(f"文件夹里没找到图片: {args.folder}")
        random.seed(42)
        random.shuffle(files)
        files = files[:args.num]
        truth = os.path.basename(os.path.normpath(args.folder))  # 文件夹名 = 真实类别
    else:
        files = args.images
        truth = None
        for f in files:
            if not os.path.exists(f):
                sys.exit(f"找不到图片: {f}")

    out_dir = r"D:\Gpt\crop-doctor\ml\runs\yolo11s-detect-v1"
    os.makedirs(out_dir, exist_ok=True)

    correct = no_det = 0
    for i, path in enumerate(files, 1):
        img = imread_cn(path)
        if img is None:
            print(f"[{i}/{len(files)}] 读取失败: {path}")
            continue

        res = model.predict(img, conf=args.conf, verbose=False)[0]
        boxes = res.boxes

        name = os.path.splitext(os.path.basename(path))[0]
        save_path = os.path.join(out_dir, f"det_{name}.jpg")

        if len(boxes) == 0:
            no_det += 1
            imwrite_cn(save_path, img)
            print(f"[{i}/{len(files)}] 未检出任何叶片  -> {save_path}")
            continue

        # 按置信度从高到低列出所有检测框
        dets = sorted(
            [(names[int(b.cls)], float(b.conf)) for b in boxes],
            key=lambda x: -x[1],
        )
        top_label = dets[0][0]
        if truth is not None and top_label == truth:
            correct += 1
        ok = "-" if truth is None else ("对" if top_label == truth else "错")

        det_str = " | ".join(f"{lb} {cf:.2f}" for lb, cf in dets[:5])
        print(f"[{i}/{len(files)}] {ok}  检出 {len(boxes)} 个目标: {det_str}")
        print(f"         结果图 -> {save_path}")

        imwrite_cn(save_path, res.plot())  # 带框和标签的结果图

    if truth is not None:
        n = len(files)
        print(f"\n真实类别: {truth}")
        print(f"正确率(最高置信度框): {correct}/{n} = {correct/n:.1%}   未检出: {no_det} 张")


if __name__ == "__main__":
    main()
