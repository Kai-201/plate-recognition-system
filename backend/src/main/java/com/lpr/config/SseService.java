package com.lpr.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * SSE 推送服务 —— 替换 WebSocket
 * 同一个 taskId 可以广播给所有订阅者（多客户端、多窗口）
 */
@Service
public class SseService {

    private static final Logger log = LoggerFactory.getLogger(SseService.class);

    /** taskId → 订阅者列表 */
    private final ConcurrentHashMap<String, Set<SseEmitter>> emitters = new ConcurrentHashMap<>();

    /** 客户端订阅某个任务 */
    public SseEmitter subscribe(String taskId) {
        SseEmitter emitter = new SseEmitter(0L);  // 无超时
        emitters.computeIfAbsent(taskId, k -> ConcurrentHashMap.newKeySet()).add(emitter);

        emitter.onCompletion(() -> remove(taskId, emitter));
        emitter.onTimeout(() -> remove(taskId, emitter));
        emitter.onError(e -> remove(taskId, emitter));

        log.info("SSE 订阅: taskId={}, 当前订阅数={}", taskId, emitters.get(taskId).size());
        return emitter;
    }

    /** 向某个 taskId 的所有订阅者推送消息 */
    public void push(String taskId, Object data) {
        Set<SseEmitter> set = emitters.get(taskId);
        if (set == null || set.isEmpty()) {
            log.info("SSE 无订阅者: taskId={}", taskId);
            return;
        }
        List<SseEmitter> dead = new ArrayList<>();
        for (SseEmitter e : set) {
            try {
                e.send(SseEmitter.event().name("result").data(data));
            } catch (Exception ex) {
                dead.add(e);
            }
        }
        set.removeAll(dead);
        log.info("SSE 推送: taskId={}, 成功={}, 失败={}", taskId, set.size(), dead.size());
    }

    private void remove(String taskId, SseEmitter emitter) {
        Set<SseEmitter> set = emitters.get(taskId);
        if (set != null) {
            set.remove(emitter);
            if (set.isEmpty()) emitters.remove(taskId);
        }
    }
}
