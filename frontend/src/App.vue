<template>
  <div class="app-container">
    <header class="header">
      <h1>车牌识别系统</h1>
      <p>上传图片或视频，自动检测并识别车牌号</p>
    </header>
    <main class="main">
      <RecognitionPanel />
    </main>
  </div>
</template>

<script setup>
import RecognitionPanel from './views/RecognitionPanel.vue'
</script>

<style>
.app-container {
  min-height: 100vh;
  background: #f0f2f5;
}

.header {
  background: linear-gradient(135deg, #1a73e8 0%, #0d47a1 100%);
  color: white;
  text-align: center;
  padding: 32px 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}

.header h1 {
  font-size: 28px;
  margin-bottom: 8px;
  letter-spacing: 2px;
}

.header p {
  font-size: 14px;
  opacity: 0.85;
}

.main {
  max-width: 900px;
  margin: 24px auto;
  padding: 0 16px;
}
</style>
