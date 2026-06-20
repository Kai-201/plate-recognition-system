package com.lpr.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lpr.config.MqConfig;
import com.lpr.config.SseService;
import com.lpr.mapper.RecognitionTaskMapper;
import com.lpr.model.RecognitionResultVO;
import com.lpr.model.RecognitionTask;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import com.rabbitmq.client.Channel;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import javax.annotation.Resource;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

/**
 * 接收 Python 处理完的结果
 */
@Component
public class MqResultReceiver {

    private static final Logger log = LoggerFactory.getLogger(MqResultReceiver.class);

    @Resource
    private RecognitionTaskMapper taskMapper;

    @Resource
    private SseService sseService;

    @Resource
    private com.lpr.service.RecognitionService recognitionService;

    @RabbitListener(queues = MqConfig.RESULT_QUEUE)
    public void onResult(Map<String, Object> result, Channel channel, Message message) {
        String taskId = (String) result.get("taskId");
        String status = (String) result.get("status");
        log.info("MQ 收到结果: taskId={}, status={}", taskId, status);

        RecognitionTask task = taskMapper.selectOne(
            new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<RecognitionTask>()
                .eq(RecognitionTask::getTaskId, taskId));
        if (task == null) {
            log.warn("MQ 结果找不到任务: taskId={}", taskId);
            return;
        }

        if ("SUCCESS".equals(status)) {
            task.setStatus("SUCCESS");
            Map<String, Object> s = new HashMap<>();
            String annotatedImg = (String) result.get("annotatedImageUrl");
            String annotatedVid = (String) result.get("annotatedVideoUrl");
            if (annotatedImg != null && !annotatedImg.isEmpty()) {
                s.put("plates", result.getOrDefault("plates", ""));
                s.put("annotated_url", annotatedImg);
            }
            if (annotatedVid != null && !annotatedVid.isEmpty()) {
                s.put("fps", result.getOrDefault("fps", 0));
                s.put("total_frames", result.getOrDefault("totalFrames", 0));
                s.put("annotated_video_url", annotatedVid);
            }
            try { task.setPlatesJson(new ObjectMapper().writeValueAsString(s)); }
            catch (Exception ignored) {}
        } else {
            task.setStatus("FAILED");
            task.setErrorMsg((String) result.getOrDefault("error", "未知错误"));
        }
        task.setCompleteTime(LocalDateTime.now());
        taskMapper.updateById(task);

        RecognitionResultVO vo = recognitionService.toVO(task);
        sseService.push(taskId, vo);
        log.info("MQ ✅ 结果处理完成+ACK: taskId={}", taskId);
    }
}
