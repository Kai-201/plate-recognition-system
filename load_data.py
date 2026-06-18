from torch.utils.data import *  # 导入 PyTorch 数据加载相关模块
from imutils import paths  # 导入 imutils 库中的路径工具，用于处理文件路径
import numpy as np  # 导入 NumPy，用于数值计算
import random  # 导入 random 模块，用于随机操作
import cv2  # 导入 OpenCV 库，用于图像处理
import os  # 导入 os 模块，用于文件和目录操作

# 定义一个包含所有可能字符的列表，包括中文省份简称、数字和字母
CHARS = ['京', '沪', '津', '渝', '冀', '晋', '蒙', '辽', '吉', '黑',
         '苏', '浙', '皖', '闽', '赣', '鲁', '豫', '鄂', '湘', '粤',
         '桂', '琼', '川', '贵', '云', '藏', '陕', '甘', '青', '宁',
         '新',
         '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
         'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K',
         'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V',
         'W', 'X', 'Y', 'Z', 'I', 'O', '-'  # 包括特殊字符 '-'
         ]

# 创建一个字符到索引的映射字典，方便后续字符编码
CHARS_DICT = {char: i for i, char in enumerate(CHARS)}

# 定义一个自定义数据加载类，继承自 PyTorch 的 Dataset 基类
class LPRDataLoader(Dataset):
    def __init__(self, img_dir, imgSize, lpr_max_len, PreprocFun=None):
        """
        初始化数据加载器
        :param img_dir: 图像目录列表，每个目录包含待加载的图像
        :param imgSize: 图像目标尺寸 (宽, 高)
        :param lpr_max_len: 车牌号的最大长度
        :param PreprocFun: 图像预处理函数，默认为 None
        """
        self.img_dir = img_dir  # 保存图像目录列表
        self.img_paths = []  # 初始化图像路径列表
        for i in range(len(img_dir)):  # 遍历每个目录
            # 使用 imutils.paths.list_images 获取目录下所有图像路径
            self.img_paths += [el for el in paths.list_images(img_dir[i])]
        random.shuffle(self.img_paths)  # 随机打乱图像路径列表
        self.img_size = imgSize  # 保存目标图像尺寸
        self.lpr_max_len = lpr_max_len  # 保存车牌号最大长度
        # 如果提供了预处理函数，则使用提供的函数；否则使用默认的 transform 函数
        if PreprocFun is not None:
            self.PreprocFun = PreprocFun
        else:
            self.PreprocFun = self.transform

    def __len__(self):
        """
        返回数据集的大小（图像数量）
        :return: 图像路径列表的长度
        """
        return len(self.img_paths)

    def __getitem__(self, index):
        """
        根据索引获取数据项
        :param index: 数据索引
        :return: 预处理后的图像
        """
        filename = self.img_paths[index]  # 获取索引对应的图像路径
        Image = cv2.imread(filename)  # 使用 OpenCV 读取图像
        height, width, _ = Image.shape  # 获取图像的高度和宽度
        # 如果图像尺寸与目标尺寸不符，则调整为目标尺寸
        if height != self.img_size[1] or width != self.img_size[0]:
            Image = cv2.resize(Image, self.img_size)
        # 对图像进行预处理（如归一化、数据增强等）
        Image = self.PreprocFun(Image)
        return Image  # 返回预处理后的图像