import torch
import cv2
import numpy as np
import os
from nets.crnn import CRNN
from dataset import CHARS, CHARS2LABEL, LABEL2CHAR, custom_collate_fn
from torch.utils.data import DataLoader
from dataset import LicensePlate  # 用你的数据集类

# ========== 配置 ==========
CHECKPOINT = r'D:\PycharmProjects2\crnn\改版\checkpoint\crnn_3000_loss1.494233.pth'  # 改成你的模型路径
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
IMG_HEIGHT = 32
IMG_WIDTH = 100

# ========== 加载模型 ==========
model = CRNN(input_c=3, input_h=IMG_HEIGHT, num_classes=len(CHARS) + 1).to(DEVICE)
model.load_state_dict(torch.load(CHECKPOINT, map_location=DEVICE))
model.eval()
print(f"Loaded model from {CHECKPOINT}")


# ========== 单张图片推理 ==========
def predict_single(image_path):
    """
    预测单张图片
    :param image_path: 图片路径
    :return: 识别的车牌字符串
    """
    # 读取并预处理（同dataset.py的逻辑）
    img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), -1)
    if img is None:
        return "读取失败"

    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    img = cv2.resize(img, (IMG_WIDTH, IMG_HEIGHT))

    # 归一化
    img = img.astype('float32') / 255.0
    img = (img - 0.5) / 0.5
    img = np.transpose(img, (2, 0, 1))  # HWC -> CHW
    img = torch.from_numpy(img).unsqueeze(0).to(DEVICE)  # [1,3,32,100]

    # 推理
    with torch.no_grad():
        output = model(img)  # [W,1,C]

    # CTC解码（贪婪解码）
    pred = output.argmax(dim=2).squeeze(1).cpu().numpy()  # [W]

    # 去重去blank
    result = []
    prev = -1
    for p in pred:
        if p != prev and p != 0:  # 0是blank
            result.append(p)
        prev = p

    # 转字符
    plate = ''.join([LABEL2CHAR.get(c, '?') for c in result])
    return plate


# ========== 批量验证测试集 ==========
def evaluate_testset(test_dir, batch_size=64):
    """
    验证整个测试集，输出准确率
    :param test_dir: 测试集文件夹路径
    """
    # 创建dataset（复用你的LicensePlate类）
    testset = LicensePlate(
        root_dir=test_dir,
        mode='test',
        img_height=IMG_HEIGHT,
        img_width=IMG_WIDTH
    )

    test_loader = DataLoader(
        testset,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=custom_collate_fn
    )

    correct = 0
    total = 0
    wrong_cases = []  # 记录错误样例

    print(f"\n开始验证，共{len(testset)}张图片...")

    with torch.no_grad():
        for images, targets, target_lengths in test_loader:
            if images is None:
                continue

            images = images.to(DEVICE)
            outputs = model(images)  # [W,B,C]

            # 批量解码
            preds = decode_batch(outputs)

            # 解析真实标签
            start = 0
            for i, length in enumerate(target_lengths):
                true_label = targets[start:start + length].tolist()
                pred_label = preds[i]

                true_text = ''.join([LABEL2CHAR.get(c, '?') for c in true_label])
                pred_text = ''.join([LABEL2CHAR.get(c, '?') for c in pred_label])

                if pred_label == true_label:
                    correct += 1
                else:
                    wrong_cases.append((true_text, pred_text))
                total += 1

                start += length

    acc = correct / total if total > 0 else 0
    print(f"\n========== 验证结果 ==========")
    print(f"总样本数: {total}")
    print(f"正确数: {correct}")
    print(f"准确率: {acc:.4f} ({acc * 100:.2f}%)")
    print(f"错误数: {total - correct}")

    # 显示前10个错误样例
    if wrong_cases:
        print(f"\n========== 错误样例（前10个）==========")
        for i, (true, pred) in enumerate(wrong_cases[:10]):
            print(f"{i + 1}. 真实: {true} | 预测: {pred}")

    return acc


def decode_batch(outputs, blank=0):
    """
    批量CTC解码
    :param outputs: [W,B,C] 模型输出
    :return: list of list，每个元素是一个样本的标签序列
    """
    preds = outputs.argmax(dim=2).cpu().numpy()  # [W,B]
    batch_size = preds.shape[1]

    results = []
    for b in range(batch_size):
        seq = []
        prev = -1
        for t in range(preds.shape[0]):
            p = preds[t, b]
            if p != prev and p != blank:
                seq.append(p)
            prev = p
        results.append(seq)

    return results


# ========== 主函数 ==========
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['single', 'batch'], default='batch',
                        help='single:单张图片, batch:整个测试集')
    parser.add_argument('--image', type=str, help='单张图片路径（mode=single时必需）')
    parser.add_argument('--test_dir', type=str,
                        default=r"D:\PycharmProjects2\LPRNet训练\CCPD2020\ccpd_green\111\test",
                        help='测试集目录（mode=batch时使用）')
    args = parser.parse_args()

    if args.mode == 'single':
        if not args.image:
            print("请提供--image参数指定图片路径")
        else:
            result = predict_single(args.image)
            print(f"预测结果: {result}")
    else:
        # 批量验证
        acc = evaluate_testset(args.test_dir)