import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image
import os
import cv2
import numpy as np
from imutils import paths  # 这个导入被覆盖就报错了
import random

# ========== 字符集配置（用你的LPRNet字符集）==========
CHARS = ['京', '沪', '津', '渝', '冀', '晋', '蒙', '辽', '吉', '黑',
         '苏', '浙', '皖', '闽', '赣', '鲁', '豫', '鄂', '湘', '粤',
         '桂', '琼', '川', '贵', '云', '藏', '陕', '甘', '青', '宁',
         '新',
         '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
         'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K',
         'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V',
         'W', 'X', 'Y', 'Z', 'I', 'O', '-']

# CTC blank必须是0，所以字符从1开始编号
CHARS2LABEL = {char: i + 1 for i, char in enumerate(CHARS)}
LABEL2CHAR = {label: char for char, label in CHARS2LABEL.items()}


class LicensePlate(Dataset):
    """
    适配LPRNet数据格式：
    - 图片路径：文件夹下的 .jpg/.png 文件
    - 标签来源：文件名中 "_" 之前的部分
    - 示例：京A12345_abc123.jpg -> 标签：京A12345
    """

    def __init__(self, root_dir=None, mode=None, img_paths=None,  # 参数名改为 img_paths
                 transform=None, img_height=32, img_width=100):
        super(LicensePlate, self).__init__()

        self.img_height = img_height
        self.img_width = img_width
        self.transform = transform if transform else self.default_transform

        # 收集图片路径
        if root_dir and not img_paths:
            if isinstance(root_dir, str):
                root_dir = [root_dir]
            self.img_paths = []
            for dir_path in root_dir:
                self.img_paths += [p for p in paths.list_images(dir_path)]  # 现在 paths 是模块
            random.shuffle(self.img_paths)
        elif img_paths:
            self.img_paths = img_paths
        else:
            raise ValueError("必须提供root_dir或img_paths")

        # 过滤无效样本
        self.img_paths = self._filter_valid()
        print(f"[{mode or 'dataset'}] 有效样本数: {len(self.img_paths)}")

    def _filter_valid(self):
        """过滤掉无法解析或包含非法字符的样本"""
        valid = []
        for path in self.img_paths:
            try:
                name = os.path.basename(path)
                text = name.split('_')[0]  # 取"_"前部分
                text = os.path.splitext(text)[0]  # 去掉扩展名

                # 检查所有字符是否在字典中
                for c in text:
                    if c not in CHARS2LABEL:
                        raise ValueError(f"非法字符: {c}")
                valid.append(path)
            except Exception as e:
                print(f"跳过无效文件 {path}: {e}")
        return valid

    def default_transform(self, img):
        """
        默认预处理（兼容原CRNN的Normalize((0.5),(0.5))）
        输入: numpy array [H, W, C] (RGB)
        输出: tensor [C, H, W], 范围[-1, 1]
        """
        img = img.astype('float32') / 255.0  # [0,1]
        img = (img - 0.5) / 0.5  # [-1,1]
        img = np.transpose(img, (2, 0, 1))  # HWC -> CHW
        return torch.from_numpy(img)

    def __getitem__(self, index):
        path = self.img_paths[index]

        try:
            # 用cv2读取（支持中文路径），转RGB
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), -1)
            if img is None:
                raise IOError("读取失败")

            if len(img.shape) == 2:  # 灰度转RGB
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
            else:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            # resize到目标尺寸
            img = cv2.resize(img, (self.img_width, self.img_height))

            # 预处理
            img = self.transform(img)

            # 解析标签：文件名_哈希.jpg -> 取前面
            name = os.path.basename(path).split('_')[0]
            name = os.path.splitext(name)[0]

            target = [CHARS2LABEL[c] for c in name]
            target = torch.LongTensor(target)
            target_length = torch.LongTensor([len(target)])

            return img, target, target_length

        except Exception as e:
            print(f"读取失败 {path}: {e}")
            # 返回dummy数据避免崩溃
            dummy_img = torch.zeros(3, self.img_height, self.img_width)
            dummy_target = torch.LongTensor([1])  # 用'京'占位
            return dummy_img, dummy_target, torch.LongTensor([1])

    def __len__(self):
        return len(self.img_paths)


# ========== 数据加载函数（保持原接口不变）==========
def custom_collate_fn(batch):
    """原CRNN的collate函数，完全不变"""
    # 过滤None（理论上不会有了，但保险）
    batch = [b for b in batch if b is not None]
    if len(batch) == 0:
        return None

    images, targets, target_lengths = zip(*batch)
    images = torch.stack(images, 0)
    targets = torch.cat(targets, 0)
    target_lengths = torch.cat(target_lengths, 0)
    return images, targets, target_lengths


def get_loader():
    """
    保持原函数签名，内部改用LPRNet数据路径
    修改下面的路径即可
    """
    # ========== 修改这里：换成你的实际路径 ==========
    train_dir = r"D:\PycharmProjects2\LPRNet训练\CCPD2020\ccpd_green\111\train_30"
    val_dir = r"D:\PycharmProjects2\LPRNet训练\CCPD2020\ccpd_green\111\val"

    # 训练配置（从原config.py拿过来的）
    train_batch_size = 32
    val_batch_size = 64
    num_workers = 0  # Windows设为0

    # 创建dataset（img_height=32, img_width=100是原CRNN配置）
    trainset = LicensePlate(
        root_dir=train_dir,
        mode='train',
        img_height=32,
        img_width=100
    )

    valset = LicensePlate(
        root_dir=val_dir,
        mode='val',
        img_height=32,
        img_width=100
    )

    train_loader = DataLoader(
        dataset=trainset,
        batch_size=train_batch_size,
        shuffle=True,
        num_workers=num_workers,
        collate_fn=custom_collate_fn
    )

    val_loader = DataLoader(
        dataset=valset,
        batch_size=val_batch_size,
        shuffle=False,
        num_workers=num_workers,
        collate_fn=custom_collate_fn
    )

    return train_loader, val_loader


# ========== 测试 ==========
if __name__ == '__main__':
    train_loader, val_loader = get_loader()

    print(f"\nTrain batches: {len(train_loader)}")
    print(f"Val batches: {len(val_loader)}")

    # 测试一个batch
    for images, targets, target_lengths in train_loader:
        print(f"\nImages shape: {images.shape}")  # [B, 3, 32, 100]
        print(f"Targets: {targets.shape}")  # [sum(lengths)]
        print(f"Lengths: {target_lengths}")  # [B]

        # 解码看看
        start = 0
        for i, L in enumerate(target_lengths[:3]):
            label = targets[start:start + L]
            text = ''.join([LABEL2CHAR[l.item()] for l in label])
            print(f"Sample {i}: {text}")
            start += L
        break