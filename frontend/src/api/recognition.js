import axios from 'axios'

const API_BASE = '/api/recognition'

/**
 * 获取 MinIO 预签名上传 URL
 */
export function getUploadUrl(fileName) {
  return axios.get('/api/minio/upload-url', { params: { fileName } }).then(res => res.data)
}

/**
 * 上传到 MinIO（XHR, 带进度, 支持 AbortController 取消）
 */
export function uploadToMinio(uploadUrl, file, onProgress, signal) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', uploadUrl)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round(e.loaded / e.total * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response)
      else reject(new Error(`Upload failed: ${xhr.status}`))
    }
    xhr.onerror = () => reject(new Error('Network error'))
    if (signal) {
      signal.addEventListener('abort', () => { xhr.abort(); reject(new DOMException('Aborted', 'AbortError')) })
    }
    xhr.send(file)
  })
}

/**
 * 通知 Java 文件已上传到 MinIO，开始推理
 */
export function notifyUpload(taskId, objectName, fileType, hash = '') {
  return axios.post(`${API_BASE}/notify`, { taskId, objectName, fileType, hash }).then(res => res.data)
}

/**
 * 计算文件 SHA-256（Web Worker，不卡页面）
 */
export function computeFileHash(file) {
  return new Promise((resolve) => {
    const worker = new Worker('/hash.worker.js')
    worker.onmessage = (e) => {
      if (e.data.error) console.warn('[Hash] Worker 错误:', e.data.error)
      resolve(e.data.hash)
    }
    worker.onerror = (e) => {
      console.warn('[Hash] Worker 启动失败:', e)
      resolve(null)
    }
    worker.postMessage(file)
  })
}

/**
 * 重新识别
 */
export function retryTask(taskId) {
  return axios.post(`${API_BASE}/retry/${taskId}`).then(res => res.data)
}

/**
 * 大文件后台算完 Hash 后异步更新
 */
export function notifyHash(taskId, hash) {
  return axios.post(`${API_BASE}/hash`, { taskId, hash }).catch(() => {})
}

/**
 * 秒传检查
 */
export function checkFileHash(hash) {
  return axios.get(`${API_BASE}/check`, { params: { hash } }).then(res => res.data)
}


/**
 * 上传文件，创建识别任务
 */
export function uploadFile(file, ocr = 'lprnet') {
  const formData = new FormData()
  formData.append('file', file)
  return axios.post(`${API_BASE}/upload?ocr=${ocr}`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }).then(res => res.data)
}

/**
 * 查询任务结果（用于刷新/轮询）
 * @param {string} taskId
 */
export function getTaskResult(taskId) {
  return axios.get(`${API_BASE}/task/${taskId}`).then(res => res.data)
}

/**
 * 查询历史记录
 */
export function getHistory() {
  return axios.get(`${API_BASE}/history`).then(res => res.data)
}

/**
 * 建立 WebSocket 连接
 * @param {string} taskId
 * @param {function} onMessage 收到消息的回调
 * @returns {WebSocket}
 */
export function connectWebSocket(taskId, onMessage) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const url = `${protocol}//${host}/ws/recognition/${taskId}`
  const ws = new WebSocket(url)
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      onMessage(data)
    } catch (e) {
      console.error('WebSocket 消息解析失败', e)
    }
  }
  ws.onerror = (err) => console.error('WebSocket 错误:', err)
  return ws
}
