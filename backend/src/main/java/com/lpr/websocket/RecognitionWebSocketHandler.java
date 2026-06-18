package com.lpr.websocket;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * WebSocket 处理器 —— 管理前端连接，支持按 taskId 推送识别结果
 *
 * 核心数据结构：ConcurrentHashMap
 *   key   = taskId
 *   value = 对应的 WebSocketSession
 *
 * 为什么用 ConcurrentHashMap？
 * WebSocket 的 onMessage/onClose 是多线程并发的，
 * HashMap 线程不安全，要用 ConcurrentHashMap。
 *
 * 面试点：WebSocket 和轮询的对比？
 * - 轮询：前端定时发 HTTP 请求查询状态，浪费带宽、有延迟
 * - WebSocket：长连接，服务端有结果立即推送，实时性高
 * - 企业里：简单场景用轮询（5秒一次），实时要求高用 WebSocket
 */
@Component
public class RecognitionWebSocketHandler extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(RecognitionWebSocketHandler.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** taskId → WebSocketSession 映射 */
    private final ConcurrentHashMap<String, WebSocketSession> sessionMap = new ConcurrentHashMap<>();

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        String taskId = (String) session.getAttributes().get("taskId");
        if (taskId != null) {
            sessionMap.put(taskId, session);
            log.info("WebSocket 连接建立: taskId={}", taskId);
        }
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        String taskId = (String) session.getAttributes().get("taskId");
        if (taskId != null) {
            sessionMap.remove(taskId);
            log.info("WebSocket 连接关闭: taskId={}", taskId);
        }
    }

    /**
     * 快速推送（不重试）—— 流式处理进度更新用，前端没连就直接丢弃
     */
    public void pushQuick(String taskId, Object data) {
        WebSocketSession session = sessionMap.get(taskId);
        if (session != null && session.isOpen()) {
            try {
                String json = MAPPER.writeValueAsString(data);
                session.sendMessage(new TextMessage(json));
            } catch (Exception e) {
                log.error("WebSocket 快速推送失败: taskId={}", taskId, e);
            }
        }
    }

    /**
     * 向指定 taskId 的前端推送识别结果（带重试）
     *
     * 为什么需要重试？前端拿到 taskId 后才建 WebSocket，存在时序竞争：
     * 如果后端推理极快（<100ms），可能 WebSocket 还没建好结果就出来了。
     * 重试 5 次 × 500ms = 2.5s 窗口，足够前端完成握手。
     */
    /**
     * 发送心跳保活（防止长时间无消息被断开）
     */
    public void sendHeartbeat(String taskId) {
        try {
            WebSocketSession session = sessionMap.get(taskId);
            if (session != null && session.isOpen()) {
                session.sendMessage(new TextMessage("{\"type\":\"heartbeat\"}"));
            }
        } catch (Exception ignored) {}
    }

    public void pushResult(String taskId, Object data) {
        WebSocketSession session = sessionMap.get(taskId);
        if (session != null && session.isOpen()) {
            try {
                String json = MAPPER.writeValueAsString(data);
                session.sendMessage(new TextMessage(json));
                log.info("WebSocket 推送成功: taskId={}", taskId);
            } catch (Exception e) {
                log.error("WebSocket 推送失败: taskId={}", taskId, e);
            }
        } else {
            log.info("WebSocket 未连接，跳过推送（由HTTP轮询兜底）: taskId={}", taskId);
        }
    }
}
