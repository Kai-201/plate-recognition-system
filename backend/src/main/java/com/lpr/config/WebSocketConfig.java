package com.lpr.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

import javax.annotation.Resource;

/**
 * WebSocket 配置 —— 注册 WebSocket 处理器和拦截器
 *
 * WebSocket 和普通 HTTP 的区别：
 * - HTTP:  请求 → 响应，一问一答，服务端不能主动推送
 * - WebSocket: 全双工，建立连接后双方随时互发消息
 *
 * 在本项目中用于：后端异步处理完视频识别后，主动推送结果给前端
 */
@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    @Resource
    private com.lpr.websocket.RecognitionWebSocketHandler handler;

    @Resource
    private com.lpr.websocket.WebSocketInterceptor interceptor;

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(handler, "/ws/recognition/{taskId}")
                .addInterceptors(interceptor)
                .setAllowedOrigins("*");   // 生产环境应该限制具体域名
    }
}
