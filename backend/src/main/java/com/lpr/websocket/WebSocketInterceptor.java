package com.lpr.websocket;

import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;

import java.util.Map;

/**
 * WebSocket 握手拦截器
 *
 * 在 WebSocket 握手阶段，从 URL 中提取 {taskId}，
 * 存入 attributes，后续 Handler 可以通过 session.getAttributes() 获取。
 */
@Component
public class WebSocketInterceptor implements HandshakeInterceptor {

    @Override
    public boolean beforeHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                   WebSocketHandler wsHandler, Map<String, Object> attributes) {
        // 从 URL 路径中提取 taskId： /ws/recognition/ABC123
        String path = request.getURI().getPath();
        String[] segments = path.split("/");
        if (segments.length > 0) {
            String taskId = segments[segments.length - 1];
            attributes.put("taskId", taskId);
        }
        return true;
    }

    @Override
    public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response,
                               WebSocketHandler wsHandler, Exception exception) {
        // nothing to do
    }
}
