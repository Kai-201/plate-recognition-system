-- ============================================
-- 车牌识别系统 - 数据库初始化脚本
-- ============================================

CREATE DATABASE IF NOT EXISTS lpr_db
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE lpr_db;

-- 识别任务记录表
CREATE TABLE IF NOT EXISTS t_recognition_task (
    id              BIGINT          AUTO_INCREMENT  PRIMARY KEY     COMMENT '主键ID',
    task_id         VARCHAR(64)     NOT NULL        UNIQUE          COMMENT '任务唯一标识(UUID)',
    file_name       VARCHAR(255)    NOT NULL                        COMMENT '原始文件名',
    file_type       VARCHAR(10)     NOT NULL                        COMMENT '文件类型: image / video',
    file_hash       VARCHAR(64)     DEFAULT NULL                    COMMENT '文件SHA-256，用于秒传去重',
    file_path       VARCHAR(500)    NOT NULL                        COMMENT '服务器文件存储路径',
    status          VARCHAR(20)     NOT NULL    DEFAULT 'PENDING'   COMMENT '任务状态: PENDING / PROCESSING / SUCCESS / FAILED',
    plates_json     TEXT            DEFAULT NULL                    COMMENT '识别结果 JSON',
    error_msg       VARCHAR(1000)   DEFAULT NULL                    COMMENT '错误信息',
    create_time     DATETIME        NOT NULL    DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    complete_time   DATETIME        DEFAULT NULL                    COMMENT '完成时间',
    INDEX idx_task_id (task_id),
    INDEX idx_status (status),
    INDEX idx_create_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='车牌识别任务记录';

-- 已有数据库升级：
-- ALTER TABLE t_recognition_task ADD COLUMN file_hash VARCHAR(64) DEFAULT NULL COMMENT '文件SHA-256，用于秒传去重' AFTER file_type;
-- ALTER TABLE t_recognition_task ADD INDEX idx_file_hash (file_hash);
