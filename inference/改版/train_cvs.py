import torch
from torch.nn import CTCLoss
from config import common_config, train_config
from nets.crnn import CRNN
from torch.optim import Adam
from dataset import get_loader
from torch.nn.functional import log_softmax
import os
from evaluate import evaluate
import csv

os.makedirs(train_config['checkpoints_dir'], exist_ok=True)

def train_step(net, data, optimizer, criterion, device):
    net.train()
    images, targets, target_lengths = [d.to(device) for d in data]
    outputs = net(images)
    log_probs = log_softmax(outputs, dim=2)
    batch_size = images.size(0)
    input_lengths = torch.LongTensor([outputs.size(0)] * batch_size)
    loss = criterion(log_probs, targets, input_lengths, target_lengths)
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    return loss.item()

# 训练阶段计算准确率（贪婪解码），修复1D targets问题
def train_eval_accuracy(net, data, device):
    net.eval()
    images, targets, target_lengths = [d.to(device) for d in data]
    with torch.no_grad():
        outputs = net(images)
        log_probs = log_softmax(outputs, dim=2)
        preds = log_probs.argmax(2).transpose(0, 1)  # [B, T]

        # 贪婪解码去掉重复和 blank
        pred_texts = []
        for pred in preds:
            pred_text = []
            prev = -1
            for p in pred.cpu().numpy():
                if p != 0 and p != prev:
                    pred_text.append(p)
                prev = p
            pred_texts.append(pred_text)

        # 将 1D targets 按 target_lengths 切分
        target_texts = []
        start = 0
        for l in target_lengths.cpu().numpy():
            target_texts.append(targets[start:start + l].cpu().numpy().tolist())
            start += l

        correct = sum([p == t for p, t in zip(pred_texts, target_texts)])
        acc = correct / len(pred_texts)
    return acc

if __name__ == '__main__':
    pre_acc = -1.0
    DEVICE = common_config['device']
    print("Using device:", DEVICE)

    net = CRNN(input_c=common_config['img_channel'],
               input_h=common_config['img_height'], num_classes=common_config['num_classes'] + 1)

    # 载入预训练模型
    if train_config['reload_checkpoint']:
        net.load_state_dict(torch.load(train_config['reload_checkpoint'], map_location=DEVICE))
        print('Pretrained model loaded!')

    net.to(DEVICE)
    optimizer = Adam(net.parameters(), lr=train_config['lr'])
    criterion = CTCLoss(blank=0, reduction='sum')
    train_loader, val_loader = get_loader()

    count = 1
    num_epoch = train_config['epochs']
    history = []  # 记录训练历史

    for epoch in range(num_epoch):
        print(f'-----Begin epoch {epoch + 1} / {num_epoch}-----')
        total_train_loss = 0
        total_train_size = 0
        total_correct = 0

        for data in train_loader:
            loss = train_step(net, data, optimizer, criterion, DEVICE)
            batch_size = data[0].size(0)
            total_train_loss += loss
            total_train_size += batch_size

            acc = train_eval_accuracy(net, data, DEVICE)
            total_correct += acc * batch_size
            count += 1

        # 计算整个 epoch 的训练损失和准确率
        train_loss = total_train_loss / total_train_size
        train_acc = total_correct / total_train_size

        # 验证集统计
        metrics = evaluate(net, val_loader, criterion, device=DEVICE,
                           decode_method=train_config['decode_method'],
                           beam_size=train_config['beam_size'])
        val_loss = metrics['loss']
        val_acc = metrics['acc']

        print(f'Epoch[{epoch+1}/{num_epoch}] '
              f'TrainLoss:{train_loss:.6f} TrainAcc:{train_acc:.4f} '
              f'ValLoss:{val_loss:.6f} ValAcc:{val_acc:.4f}')

        # 保存训练历史
        history.append({
            'epoch': epoch + 1,
            'train_loss': train_loss,
            'train_acc': train_acc,
            'val_loss': val_loss,
            'val_acc': val_acc
        })

        # 根据验证集保存模型
        if pre_acc < val_acc and val_acc > 0.9:
            print('Excellent model appears!')
            pre_acc = val_acc
            checkpoint_path = os.path.join(
                train_config['checkpoints_dir'],
                'crnn_epoch{}_valloss{:.6f}.pth'.format(epoch + 1, val_loss)
            )
            torch.save(net.state_dict(), checkpoint_path)
            print('Saved model at', checkpoint_path)

    # 保存成 CSV 文件
    csv_path = os.path.join(train_config['checkpoints_dir'], 'train_history.csv')
    keys = ['epoch', 'train_loss', 'train_acc', 'val_loss', 'val_acc']
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(history)
    print('Training history saved to', csv_path)