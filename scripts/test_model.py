# -*- coding: utf-8 -*-
r"""
植物病害模型测试脚本（ResNet50 分类 + Grad-CAM 病灶定位）

注意: 这是早期探索的旁支方案，项目检测主线为 YOLO11s（见 test_yolo.py / eval_all.py）。
      保留此脚本用于方案对比与消融说明。

用法（任意目录的终端均可，脚本内路径均为绝对路径）:
    # 测试单张图片（路径带空格、括号要加引号）
    python test_model.py "D:\某张叶片照片.jpg"

    # 从某个类别文件夹随机抽 20 张测试，并统计正确率
    python test_model.py --folder "D:\Gpt\crop-doctor\ml\data\raw\plantvillage\Apple___Apple_scab" -n 20

    # 权重不在默认位置时，用 --ckpt 指定路径
    python test_model.py --ckpt "C:\Users\xxx\Downloads\best.pt" "图片.jpg"

默认权重: ml\exports\resnet50-plantvillage39-v1.pt（39 类）
输出: 结果图（热力图 + 绿框 + 类别）保存到 ml\runs\resnet50-gradcam-v1\，文件名前缀 result_
"""
import argparse
import glob
import os
import random
import sys

import cv2
import numpy as np
import torch
from torchvision import models, transforms

# grad-cam 是可选依赖，没装也能跑（只输出分类，不画定位框）
try:
    from pytorch_grad_cam import GradCAM
    from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget
    from pytorch_grad_cam.utils.image import show_cam_on_image
    HAS_CAM = True
except ImportError:
    HAS_CAM = False
    print("提示: 未安装 grad-cam 包，只输出分类结果，不画定位框")
    print("      安装命令: pip install grad-cam\n")

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# 与训练时一致的预处理
tf = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def imread_cn(path):
    """读取图片，兼容中文路径（cv2.imread 在 Windows 下读不了中文路径）"""
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_cn(path, img):
    """保存图片，兼容中文路径"""
    ext = os.path.splitext(path)[1] or ".jpg"
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)


def load_model(ckpt_path):
    try:
        ckpt = torch.load(ckpt_path, map_location=DEVICE, weights_only=False)
    except TypeError:  # 旧版 torch 没有 weights_only 参数
        ckpt = torch.load(ckpt_path, map_location=DEVICE)
    classes = ckpt["classes"]
    model = models.resnet50()
    model.fc = torch.nn.Linear(model.fc.in_features, len(classes))
    model.load_state_dict(ckpt["state_dict"])
    model.eval().to(DEVICE)
    return model, classes


def predict(model, classes, cam_obj, img_bgr):
    """对一张 BGR 图片做分类 + 定位，返回(结果图, 标签, 置信度, top3列表)"""
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    x = tf(rgb).unsqueeze(0).to(DEVICE)

    with torch.no_grad():
        prob = torch.softmax(model(x), 1)[0]
    top3 = torch.topk(prob, 3)
    cid = int(top3.indices[0])
    label, conf = classes[cid], float(top3.values[0])

    out = img_bgr.copy()
    if cam_obj is not None:
        # 生成热力图（模型关注的病斑区域）
        heatmap = cam_obj(input_tensor=x, targets=[ClassifierOutputTarget(cid)])[0]
        heat = cv2.resize(heatmap, (rgb.shape[1], rgb.shape[0]))
        heat = (heat - heat.min()) / (heat.max() - heat.min() + 1e-8)

        # 热力图最亮的前 20% 区域 -> 最大连通域 -> 边界框
        mask = (heat > np.percentile(heat, 80)).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        overlay = show_cam_on_image(rgb.astype(np.float32) / 255.0, heat, use_rgb=True)
        out = cv2.cvtColor((overlay * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
        if contours:
            bx, by, bw, bh = cv2.boundingRect(max(contours, key=cv2.contourArea))
            cv2.rectangle(out, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)
            text = f"{label} {conf:.2f}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            # 标签放框上方，若超出图像边界则收进框内/左移，避免截断
            tx = min(max(bx, 2), out.shape[1] - tw - 2)
            ty = by - 8 if by - 8 - th >= 0 else by + th + 4
            cv2.putText(out, text, (tx, max(ty, th + 2)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    top3_list = [(classes[int(i)], float(v)) for v, i in zip(top3.values, top3.indices)]
    return out, label, conf, top3_list


def main():
    ap = argparse.ArgumentParser(description="测试植物病害分类+定位模型")
    ap.add_argument("images", nargs="*", help="要测试的图片路径（可多张）")
    ap.add_argument("--folder", help="测试整个类别文件夹（随机抽取统计正确率）")
    ap.add_argument("-n", "--num", type=int, default=20, help="从文件夹抽取的图片数，默认20")
    ap.add_argument("--ckpt", default=r"D:\Gpt\crop-doctor\ml\exports\resnet50-plantvillage39-v1.pt", help="模型文件路径")
    args = ap.parse_args()

    if not os.path.exists(args.ckpt):
        sys.exit(f"找不到模型文件: {args.ckpt}\n默认指向 ml/exports 下的权重，或用 --ckpt 指定路径")
    if not args.images and not args.folder:
        sys.exit("请指定要测试的图片路径，或用 --folder 指定类别文件夹\n示例: python test_model.py \"D:\\照片.jpg\"")

    model, classes = load_model(args.ckpt)
    cam_obj = GradCAM(model=model, target_layers=[model.layer4]) if HAS_CAM else None
    print(f"模型加载成功: {len(classes)} 个类别 | 设备: {DEVICE}（CPU 单张约 1~3 秒）\n")

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

    out_dir = r"D:\Gpt\crop-doctor\ml\runs\resnet50-gradcam-v1"
    os.makedirs(out_dir, exist_ok=True)

    correct = 0
    for i, path in enumerate(files, 1):
        img = imread_cn(path)
        if img is None:
            print(f"[{i}/{len(files)}] 读取失败: {path}")
            continue
        out, label, conf, top3 = predict(model, classes, cam_obj, img)

        name = os.path.splitext(os.path.basename(path))[0]
        save_path = os.path.join(out_dir, f"result_{name}.jpg")
        imwrite_cn(save_path, out)

        ok = "-" if truth is None else ("对" if label == truth else "错")
        if truth is not None and label == truth:
            correct += 1
        top3_str = " | ".join(f"{c} {p:.2f}" for c, p in top3)
        print(f"[{i}/{len(files)}] {ok}  {label}  置信度={conf:.1%}")
        print(f"         Top3: {top3_str}")
        print(f"         结果图 -> {save_path}")

    if truth is not None:
        print(f"\n真实类别: {truth}")
        print(f"正确率: {correct}/{len(files)} = {correct/len(files):.1%}")


if __name__ == "__main__":
    main()
