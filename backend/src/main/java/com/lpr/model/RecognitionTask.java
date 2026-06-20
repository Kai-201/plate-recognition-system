package com.lpr.model;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 识别任务实体 —— 对应数据库 t_recognition_task 表
 */
@Data
@TableName("t_recognition_task")
public class RecognitionTask {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 任务唯一标识 (UUID) */
    private String taskId;

    /** 原始文件名 */
    private String fileName;

    /** 文件类型: image / video */
    private String fileType;

    /** 文件 SHA-256，用于秒传去重 */
    private String fileHash;

    /** 服务器文件存储路径 */
    private String filePath;

    /** 任务状态: PENDING / PROCESSING / SUCCESS / FAILED */
    private String status;

    /** 识别结果 JSON 字符串 */
    private String platesJson;

    /** 错误信息 */
    private String errorMsg;

    /** 创建时间 */
    private LocalDateTime createTime;

    /** 处理心跳（py 存活标志） */
    private LocalDateTime lastHeartbeat;

    /** 完成时间 */
    private LocalDateTime completeTime;
}
