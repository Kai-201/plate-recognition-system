package com.lpr.service;

import com.lpr.config.MqConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Service;

import javax.annotation.Resource;
import java.util.Map;

/**
 * MQ 服务: Java ↔ Python 解耦通信
 */
@Service
public class MqService {

    private static final Logger log = LoggerFactory.getLogger(MqService.class);

    @Resource
    private RabbitTemplate rabbitTemplate;

    /** 发送推理任务给 Python（Publisher Confirm 确保到达 Broker） */
    public void sendTask(Map<String, Object> task) {
        String taskId = (String) task.get("taskId");
        rabbitTemplate.convertAndSend(MqConfig.TASK_QUEUE, task,
            new org.springframework.amqp.rabbit.connection.CorrelationData(taskId));
        log.info("MQ 发送任务: taskId={}", taskId);
    }
}
