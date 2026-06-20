package com.lpr.service;

import com.lpr.config.MqConfig;
import com.lpr.config.SseService;
import com.lpr.mapper.RecognitionTaskMapper;
import com.lpr.model.RecognitionTask;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import javax.annotation.Resource;
import java.time.LocalDateTime;
import java.util.Map;

/**
 * 死信队列监控 —— 处理失败的消息最终流入 DLQ，用于告警 + 人工排查
 */
@Component
public class DlqMonitor {

    private static final Logger log = LoggerFactory.getLogger(DlqMonitor.class);

    @Resource
    private RecognitionTaskMapper taskMapper;

    @Resource
    private SseService sseService;

    @RabbitListener(queues = MqConfig.DLQ)
    public void onDlqMessage(Map<String, Object> message) {
        String taskId = (String) message.get("taskId");
        log.warn("[DLQ] 死信消息: taskId={} type={}", taskId, message.get("type"));

        RecognitionTask task = taskMapper.selectOne(
            new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<RecognitionTask>()
                .eq(RecognitionTask::getTaskId, taskId));
        if (task != null) {
            task.setStatus("FAILED");
            task.setErrorMsg("消息进死信队列(DLQ)");
            task.setCompleteTime(LocalDateTime.now());
            taskMapper.updateById(task);
            log.info("[DLQ] 已标记FAILED: {}", taskId);
        }
    }
}
