// Web Worker: 采样 SHA-256（头1MB+尾1MB+文件大小，大文件秒出结果）
self.onmessage = async (e) => {
  const file = e.data
  try {
    let hashInput
    const SAMPLE_SIZE = 1024 * 1024  // 1MB

    if (file.size <= SAMPLE_SIZE * 2) {
      // 小文件直接全量 Hash
      hashInput = await file.arrayBuffer()
    } else {
      // 大文件采样：头1MB + 尾1MB
      const head = await file.slice(0, SAMPLE_SIZE).arrayBuffer()
      const tail = await file.slice(file.size - SAMPLE_SIZE, file.size).arrayBuffer()
      const sizeStr = new TextEncoder().encode(String(file.size))
      // 合并：head + tail + file_size
      const combined = new Uint8Array(head.byteLength + tail.byteLength + sizeStr.byteLength)
      combined.set(new Uint8Array(head), 0)
      combined.set(new Uint8Array(tail), head.byteLength)
      combined.set(sizeStr, head.byteLength + tail.byteLength)
      hashInput = combined.buffer
    }

    const hashBuffer = await crypto.subtle.digest('SHA-256', hashInput)
    const hashArray = Array.from(new Uint8Array(hashBuffer))
    const hash = hashArray.map(b => b.toString(16).padStart(2, '0')).join('')
    self.postMessage({ hash, error: null })
  } catch (err) {
    self.postMessage({ hash: null, error: err.message })
  }
}
