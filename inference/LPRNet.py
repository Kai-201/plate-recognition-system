import torch.nn as nn  # 导入 PyTorch 的神经网络模块
import torch  # 导入 PyTorch 库

# 定义一个小型基础块（small_basic_block），用于构建网络的基本单元
class small_basic_block(nn.Module):
    def __init__(self, ch_in, ch_out):
        """
        初始化小型基础块
        :param ch_in: 输入通道数
        :param ch_out: 输出通道数
        """
        super(small_basic_block, self).__init__()
        # 定义一个顺序容器（Sequential），包含多个卷积层和激活函数
        self.block = nn.Sequential(
            nn.Conv2d(ch_in, ch_out // 4, kernel_size=1),  # 1x1卷积，用于减少通道数
            nn.ReLU(),  # 激活函数
            nn.Conv2d(ch_out // 4, ch_out // 4, kernel_size=(3, 1), padding=(1, 0)),  # 3x1卷积
            nn.ReLU(),  # 激活函数
            nn.Conv2d(ch_out // 4, ch_out // 4, kernel_size=(1, 3), padding=(0, 1)),  # 1x3卷积
            nn.ReLU(),  # 激活函数
            nn.Conv2d(ch_out // 4, ch_out, kernel_size=1),  # 1x1卷积，用于恢复通道数
        )

    def forward(self, x):
        """
        前向传播函数
        :param x: 输入张量
        :return: 经过小型基础块处理后的张量
        """
        return self.block(x)  # 将输入张量通过定义的顺序容器

# 定义车牌识别网络（LPRNet）
class LPRNet(nn.Module):
    def __init__(self, lpr_max_len, phase, class_num, dropout_rate, use_attention=True):
        """
        初始化 LPRNet
        :param lpr_max_len: 车牌号的最大长度
        :param phase: 网络的阶段（训练或测试）
        :param class_num: 分类类别数（字符总数）
        :param dropout_rate: Dropout 的概率
        :param use_attention: 是否使用注意力机制
        """
        super(LPRNet, self).__init__()
        self.use_attention = use_attention
        self.phase = phase  # 保存网络阶段
        self.lpr_max_len = lpr_max_len  # 保存车牌号最大长度
        self.class_num = class_num  # 保存分类类别数

        # 定义网络的主干部分（backbone）
        self.backbone = nn.Sequential(
            nn.Conv2d(in_channels=3, out_channels=64, kernel_size=3, stride=1),  # 卷积层，输入通道3（RGB图像），输出通道64
            nn.BatchNorm2d(num_features=64),  # 批归一化层
            nn.ReLU(),  # 激活函数
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 1, 1)),  # 3D最大池化层，减少特征图尺寸
            small_basic_block(ch_in=64, ch_out=128),  # 小型基础块，输入通道64，输出通道128
            nn.BatchNorm2d(num_features=128),  # 批归一化层
            nn.ReLU(),  # 激活函数
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(2, 1, 2)),  # 3D最大池化层，进一步减少特征图尺寸
            small_basic_block(ch_in=64, ch_out=256),  # 小型基础块，输入通道64，输出通道256
            nn.BatchNorm2d(num_features=256),  # 批归一化层
            nn.ReLU(),  # 激活函数
            small_basic_block(ch_in=256, ch_out=256),  # 小型基础块，输入通道256，输出通道256
            nn.BatchNorm2d(num_features=256),  # 批归一化层
            nn.ReLU(),  # 激活函数
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(4, 1, 2)),  # 3D最大池化层，进一步减少特征图尺寸
            nn.Dropout(dropout_rate),  # Dropout层，用于防止过拟合
            nn.Conv2d(in_channels=64, out_channels=256, kernel_size=(1, 4), stride=1),  # 卷积层，调整特征图尺寸
            nn.BatchNorm2d(num_features=256),  # 批归一化层
            nn.ReLU(),  # 激活函数
            nn.Dropout(dropout_rate),  # Dropout层
            nn.Conv2d(in_channels=256, out_channels=class_num, kernel_size=(13, 1), stride=1),  # 卷积层，输出类别数
            nn.BatchNorm2d(num_features=class_num),  # 批归一化层
            nn.ReLU(),  # 激活函数
        )

        # 定义容器部分，用于进一步处理特征
        self.container = nn.Sequential(
            nn.Conv2d(in_channels=448 + self.class_num, out_channels=self.class_num, kernel_size=(1, 1), stride=(1, 1)),
            # 其他层被注释掉
        )

    def forward(self, x):
        """
        前向传播函数
        :param x: 输入张量
        :return: 网络输出
        """
        keep_features = list()  # 用于保存特定层的特征
        for i, layer in enumerate(self.backbone.children()):  # 遍历主干网络的每一层
            x = layer(x)  # 通过当前层
            if i in [2, 6, 13, 22]:  # 保存特定层的输出
                keep_features.append(x)

        global_context = list()  # 用于保存全局上下文特征
        for i, f in enumerate(keep_features):  # 遍历保存的特征
            if i in [0, 1]:  # 对前两个特征进行平均池化
                f = nn.AvgPool2d(kernel_size=5, stride=5)(f)
            if i in [2]:  # 对第三个特征进行不同的平均池化
                f = nn.AvgPool2d(kernel_size=(4, 10), stride=(4, 2))(f)
            f_pow = torch.pow(f, 2)  # 对特征进行平方
            f_mean = torch.mean(f_pow)  # 计算平方的均值
            f = torch.div(f, f_mean)  # 对特征进行归一化
            global_context.append(f)  # 保存归一化后的特征

        x = torch.cat(global_context, 1)  # 将全局上下文特征在通道维度上拼接
        x = self.container(x)  # 通过容器部分
        logits = torch.mean(x, dim=2)  # 对特征在宽度维度上求均值

        return logits  # 返回最终的输出

# 构建 LPRNet 的函数
def build_lprnet(lpr_max_len=8, phase=False, class_num=66, dropout_rate=0.5):
    """
    构建 LPRNet
    :param lpr_max_len: 车牌号的最大长度
    :param phase: 网络的阶段（训练或测试）
    :param class_num: 分类类别数
    :param dropout_rate: Dropout 的概率
    :return: 构建好的 LPRNet
    """
    Net = LPRNet(lpr_max_len, phase, class_num, dropout_rate)  # 初始化网络

    if phase == "train100":  # 如果是训练阶段
        return Net.train()  # 返回训练模式的网络
    else:  # 如果是测试阶段
        return Net.eval()  # 返回评估模式的网络
