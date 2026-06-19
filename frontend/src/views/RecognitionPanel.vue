<template>
  <div class="panel">
    <!-- ===== 上传区域 ===== -->
    <!-- OCR 模型选择 -->
    <div class="model-selector">
      <span>OCR引擎：</span>
      <label><input type="radio" v-model="ocrModel" value="lprnet" /> LPRNet</label>
      <label><input type="radio" v-model="ocrModel" value="crnn" /> CRNN</label>
    </div>

    <div
      class="upload-zone"
      :class="{ 'is-dragover': dragging }"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="handleDrop"
      @click="triggerInput"
    >
      <input
        ref="fileInput"
        type="file"
        accept="image/*,video/*"
        style="display:none"
        @change="handleFileChange"
      />
      <div class="upload-hint">
        <div class="upload-icon">📁</div>
        <p>点击上传 或 拖拽文件到此处</p>
        <span class="upload-sub">支持 JPG / PNG / MP4 / AVI / MOV 等格式</span>
      </div>
    </div>

    <!-- ===== 已上传文件预览 ===== -->
    <div v-if="currentFile" class="file-info">
      <span class="file-name">{{ currentFile.name }}</span>
      <span class="file-size">{{ formatSize(currentFile.size) }}</span>
    </div>

    <!-- ===== 识别结果卡片 ===== -->
    <div v-if="result" class="result-card" :class="{ 'is-success': result.status === 'SUCCESS', 'is-fail': result.status === 'FAILED' }">
      <!-- 加载中 -->
      <div v-if="result.status === 'PENDING' || result.status === 'PROCESSING'" class="result-status">
        <div class="spinner"></div>
        <p>{{ result.status === 'PENDING' ? '任务排队中...' : streamProgress }}</p>
        <div v-if="uploadProgress > 0 && uploadProgress < 100" class="progress-bar">
          <div class="progress-fill" :style="{width: uploadProgress + '%'}"></div>
          <span>{{ uploadProgress }}%</span>
        </div>
      </div>

      <!-- 成功 -->
      <div v-else-if="result.status === 'SUCCESS'" class="result-body">
        <div class="result-header">
          <span class="status-badge success">✅ 识别完成</span>
          <span class="result-file">{{ currentFile?.name }}</span>
        </div>

        <!-- 图片结果 -->
        <template v-if="result.fileType === 'image'">
          <div class="plate-display">
            <div v-for="(plate, i) in parsedPlates" :key="i" class="plate-number">
              {{ plate }}
            </div>
            <div v-if="parsedPlates.length === 0" class="no-result">未检测到车牌</div>
          </div>
          <!-- 标注图展示 -->
          <div v-if="result.annotatedImageUrl" class="annotated-image-section">
            <img :src="result.annotatedImageUrl" alt="标注结果" class="annotated-image" />
          </div>
        </template>

        <!-- 视频结果 -->
        <template v-else>
          <div v-if="result.annotatedVideoUrl" class="annotated-video-section">
            <video :src="result.annotatedVideoUrl" controls class="annotated-video"
                   @loadstart="onVideoLoadStart"
                   @canplay="onVideoCanPlay" />
          </div>
        </template>

        <div class="result-time">
          {{ result.completeTime ? '完成时间: ' + result.completeTime : '' }}
        </div>
      </div>

      <!-- 失败 -->
      <div v-else-if="result.status === 'FAILED'" class="result-body">
        <div class="result-header">
          <span class="status-badge fail">❌ 识别失败</span>
        </div>
        <p class="error-msg">{{ result.errorMsg }}</p>
      </div>
    </div>

    <!-- ===== 历史记录 ===== -->
    <div class="history-section">
      <h3 @click="loadHistory" style="cursor:pointer; user-select:none;">
        📋 历史记录 <span style="font-size:12px;color:#999;">(点击刷新)</span>
      </h3>
      <div v-if="history.length === 0" class="history-empty">暂无记录</div>
      <div v-for="item in history" :key="item.taskId" class="history-item" @click="loadHistoryItem(item)">
        <div class="history-left">
          <span class="history-status" :class="item.status">
            {{ item.status === 'SUCCESS' ? '✅' : item.status === 'FAILED' ? '❌' : '⏳' }}
          </span>
          <span class="history-name">{{ item.fileName }}</span>
        </div>
        <div class="history-right">
          <span class="history-time">{{ item.createTime }}</span>
          <button class="retry-btn" @click.stop="handleRetry(item)" title="用最新逻辑重新识别">🔄</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { uploadFile, getHistory, connectWebSocket, computeFileHash, checkFileHash, retryTask, getUploadUrl, uploadToMinio, notifyUpload } from '../api/recognition.js'

// ===== 状态 =====
const fileInput = ref(null)
const dragging = ref(false)
const currentFile = ref(null)
const uploadProgress = ref(0)
const ocrModel = ref('lprnet')
let videoLoadStart = 0
let uploadStartTime = 0
function onVideoLoadStart() { videoLoadStart = performance.now() }
function onVideoCanPlay() {
  const loadTime = (performance.now() - videoLoadStart).toFixed(0)
  const totalTime = (performance.now() - uploadStartTime).toFixed(0)
  console.log(`[前端] MinIO加载: ${loadTime}ms | 上传到可播总耗时: ${totalTime}ms (${(totalTime/1000).toFixed(1)}s)`)
}
const result = ref(null)
const history = ref([])

// ===== 计算属性 =====
const parsedPlates = computed(() => {
  if (!result.value || result.value.fileType !== 'image') return []
  try {
    const plates = typeof result.value.plates === 'string'
      ? JSON.parse(result.value.plates)
      : result.value.plates
    return plates?.plates || plates || []
  } catch { return [] }
})

const sampledFrames = computed(() => {
  if (!result.value) return 0
  try {
    const data = typeof result.value.plates === 'string'
      ? JSON.parse(result.value.plates)
      : result.value.plates
    return data?.sampled_frames || 0
  } catch { return 0 }
})

const frameResults = computed(() => {
  if (!result.value) return []
  try {
    const data = typeof result.value.plates === 'string'
      ? JSON.parse(result.value.plates)
      : result.value.plates
    return data?.results || []
  } catch { return [] }
})

const streamProgress = computed(() => {
  if (!result.value || result.value.status !== 'PROCESSING') return '正在识别中...'
  const frames = frameResults.value
  if (frames.length === 0) return '正在启动推理...'
  const last = frames[frames.length - 1]
  const lastPlate = (last.plates && last.plates.length > 0)
    ? (Array.isArray(last.plates) ? last.plates.join(', ') : last.plates)
    : '—'
  return `处理到第 ${last.frame} 帧 | ${lastPlate}`
})

const totalPlatesInVideo = computed(() => {
  return frameResults.value.reduce((sum, fr) => sum + (fr.plates?.length || 0), 0)
})

// ===== 方法 =====
function triggerInput() {
  fileInput.value?.click()
}

function handleFileChange(e) {
  const file = e.target.files[0]
  if (file) submitFile(file)
}

function handleDrop(e) {
  dragging.value = false
  const file = e.dataTransfer.files[0]
  if (file) submitFile(file)
}

async function submitFile(file) {
  currentFile.value = file
  result.value = { status: 'PROCESSING' }
  uploadStartTime = performance.now()

  try {
    const t0 = performance.now()

    // 小文件等 Hash，大文件上传+Hash 并行
    const isBig = file.size > 10 * 1024 * 1024
    const hashPromise = computeFileHash(file)
    let hash = isBig ? '' : await hashPromise

    // 小文件秒传检查
    if (!isBig && hash) {
      const check = await checkFileHash(hash)
      if (check.code === 200 && check.data) {
        const cd = check.data
        // SUCCESS → 秒传，PENDING/PROCESSING → 等结果
        if (cd.status === 'SUCCESS') {
          result.value = cd; loadHistory()
          console.log(`[秒传] ${(performance.now() - t0).toFixed(0)}ms`)
          return
        }
        if (cd.taskId) {
          console.log(`[秒传-处理中] 复用 taskId: ${cd.taskId}`)
          setupVideoWait(cd.taskId, t0)
          return
        }
      }
    }

    // 上传 MinIO（大文件可被 abort 中断，带进度条）
    uploadProgress.value = 0
    const { uploadUrl, objectName, taskId } = await getUploadUrl(file.name)
    const controller = new AbortController()
    const uploadPromise = uploadToMinio(uploadUrl, file, (pct) => { uploadProgress.value = pct }, controller.signal)

    // 大文件：Hash 并行跑，命中则中断上传
    if (isBig) {
      hash = await hashPromise
      if (hash) {
        const check = await checkFileHash(hash)
        if (check.code === 200 && check.data) {
          controller.abort()
          const cd = check.data
          if (cd.status === 'SUCCESS') {
            result.value = cd; loadHistory()
            console.log(`[秒传(大文件)] ${(performance.now() - t0).toFixed(0)}ms`)
            return
          }
          if (cd.taskId) {
            console.log(`[秒传-处理中(大)] 复用 taskId: ${cd.taskId}`)
            setupVideoWait(cd.taskId, t0)
            return
          }
        }
      }
    }

    await uploadPromise.catch(() => {})  // 被秒传中断则不报错
    const res = await notifyUpload(taskId, objectName, file.type.startsWith('video') ? 'video' : 'image', hash || '')
    console.log(`[前端] 上传耗时: ${(performance.now() - t0).toFixed(0)}ms  OCR=${ocrModel.value}`)
    if (res.code === 200) {
      const resData = res.data

      // 判断后端返回的是同步结果还是 taskId
      if (resData.status || resData.plates) {
        // 图片：同步返回，直接展示结果
        result.value = resData
        loadHistory()
      } else if (resData.taskId) {
        setupVideoWait(taskId, t0)
      }
    }
  } catch (err) {
    if (err.name === 'AbortError' || err.name === 'DOMException') return  // 秒传中断上传，不报错
    result.value = { status: 'FAILED', errorMsg: err.message || '上传失败' }
  }
}

function setupVideoWait(taskId, t0) {
  result.value = { status: 'PROCESSING', taskId }
  let done = false

  // SSE 订阅（支持多客户端广播）
  const es = new EventSource(`/api/recognition/subscribe/${taskId}`)
  es.addEventListener('result', (e) => {
    if (done) return
    const data = JSON.parse(e.data)
    if (data.status === 'SUCCESS') {
      result.value = { ...data, taskId }; done = true; es.close(); loadHistory()
      console.log(`[SSE-完成] ${(performance.now() - t0).toFixed(0)}ms`)
    } else if (data.status === 'FAILED') {
      result.value = { ...data, taskId }; done = true; es.close()
    }
  })

  // 轮询兜底
  const pollTimer = setInterval(async () => {
    if (done) { clearInterval(pollTimer); return }
    try {
      const { getTaskResult } = await import('../api/recognition.js')
      const r = await getTaskResult(taskId)
      if (r.code === 200 && r.data && (r.data.status === 'SUCCESS' || r.data.status === 'FAILED')) {
        result.value = r.data; done = true
        clearInterval(pollTimer); try { es.close() } catch {}
        if (r.data.status === 'SUCCESS') loadHistory()
      }
    } catch {}
  }, 3000)
}

async function loadHistory() {
  try {
    const res = await getHistory()
    if (res.code === 200) {
      history.value = res.data || []
    }
  } catch (err) {
    console.error('加载历史记录失败', err)
  }
}

function loadHistoryItem(item) {
  currentFile.value = { name: item.fileName, size: 0 }
  result.value = item
}

async function handleRetry(item) {
  result.value = { status: 'PROCESSING', taskId: item.taskId }
  currentFile.value = { name: item.fileName, size: 0 }

  if (item.fileType === 'video') {
    setupVideoWait(item.taskId, performance.now())

    // WS 建好后再调重试
    ws.onopen = async () => {
      try { await retryTask(item.taskId) }
      catch (err) { result.value = { status: 'FAILED', errorMsg: err.message || '重试失败' } }
    }
  } else {
    // 图片：同步，直接调
    try {
      const res = await retryTask(item.taskId)
      if (res.code === 200 && res.data) { result.value = res.data; loadHistory() }
    } catch (err) {
      result.value = { status: 'FAILED', errorMsg: err.message || '重试失败' }
    }
  }
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++ }
  return size.toFixed(1) + ' ' + units[i]
}

onMounted(() => {
  loadHistory()
})
</script>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* OCR 模型选择 */
.model-selector {
  display: flex; align-items: center; gap: 16px;
  padding: 8px 0; font-size: 14px; color: #666;
}
.model-selector label { cursor: pointer; display: flex; align-items: center; gap: 4px; }
.model-selector input[type=radio] { margin: 0; }

/* 上传区域 */
.upload-zone {
  background: white;
  border: 2px dashed #d0d5dd;
  border-radius: 12px;
  padding: 48px 24px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}

.upload-zone:hover,
.upload-zone.is-dragover {
  border-color: #1a73e8;
  background: #f0f5ff;
}

.upload-icon { font-size: 48px; margin-bottom: 12px; }
.upload-hint p { font-size: 16px; color: #333; margin-bottom: 4px; }
.upload-sub { font-size: 12px; color: #999; }

.progress-bar {
  width: 200px; height: 20px; background: #e0e0e0; border-radius: 10px;
  margin: 8px auto 0; overflow: hidden; position: relative;
}
.progress-fill {
  height: 100%; background: #1a73e8; border-radius: 10px; transition: width 0.2s;
}
.progress-bar span {
  position: absolute; top: 0; left: 0; width: 100%; text-align: center;
  font-size: 12px; color: #333; line-height: 20px;
}

.spinner {
  width: 36px; height: 36px;
  border: 3px solid #e0e0e0;
  border-top: 3px solid #1a73e8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 12px;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* 文件信息 */
.file-info {
  background: white;
  padding: 12px 16px;
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  font-size: 14px;
  color: #666;
}

/* 结果卡片 */
.result-card {
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}

.result-status { text-align: center; padding: 20px; }
.result-status p { margin-top: 12px; color: #666; }

.result-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.status-badge {
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 500;
}
.status-badge.success { background: #e8f5e9; color: #2e7d32; }
.status-badge.fail { background: #ffebee; color: #c62828; }
.result-file { font-size: 13px; color: #999; }

/* 车牌号显示 */
.plate-display {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.plate-number {
  background: #1a4b9e;
  color: white;
  font-size: 22px;
  font-weight: bold;
  letter-spacing: 3px;
  padding: 10px 24px;
  border-radius: 6px;
  font-family: 'Courier New', monospace;
  border: 2px solid #0d3b7a;
}

.no-result { color: #999; font-size: 14px; }

/* 标注图 */
.annotated-image-section {
  margin-top: 16px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e0e0e0;
}
.annotated-image {
  width: 100%;
  display: block;
}

/* 标注视频 */
.annotated-video-section {
  margin-bottom: 16px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #e0e0e0;
}
.annotated-video {
  width: 100%;
  display: block;
  max-height: 450px;
  background: #000;
}

.frame-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  background: #f8f9fa;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s;
}
.frame-item:hover { background: #e8f5e9; }
.frame-item.has-plate { border-left: 3px solid #00c853; }

/* 视频结果 */
.video-summary { margin-bottom: 12px; color: #333; font-size: 14px; }

.video-frames {
  max-height: 300px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.frame-idx { color: #666; min-width: 60px; }
.frame-plates { display: flex; flex-wrap: wrap; gap: 4px; }
.frame-plate-tag {
  background: #e3f2fd;
  color: #1565c0;
  padding: 2px 8px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
}
.frame-none { color: #bbb; }

.result-time { margin-top: 16px; font-size: 12px; color: #aaa; }
.error-msg { color: #c62828; font-size: 14px; }

/* 历史记录 */
.history-section {
  background: white;
  border-radius: 12px;
  padding: 20px 24px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}

.history-section h3 { margin-bottom: 12px; color: #333; }
.history-empty { color: #ccc; font-size: 14px; text-align: center; padding: 20px; }

.history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 8px;
  border-bottom: 1px solid #f0f0f0;
  cursor: pointer;
  transition: background 0.15s;
}
.history-item:hover { background: #f8f9fa; }
.history-left { display: flex; align-items: center; gap: 8px; }
.history-status { font-size: 16px; }
.history-name { font-size: 14px; color: #333; }
.history-right { display: flex; align-items: center; gap: 8px; }
.history-time { font-size: 12px; color: #aaa; }
.retry-btn {
  background: none; border: 1px solid #ddd;
  border-radius: 4px; cursor: pointer;
  padding: 2px 6px; font-size: 14px;
  opacity: 0; transition: opacity 0.15s;
}
.history-item:hover .retry-btn { opacity: 1; }
.retry-btn:hover { background: #e3f2fd; border-color: #1a73e8; }
</style>
