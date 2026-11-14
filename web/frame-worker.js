/* Frame encoder worker: ImageBitmap -> JPEG Blob, off the rendering thread.
 * Message in:  { id, bitmap, maxWidth, quality }   (bitmap is transferred)
 * Message out: { id, blob } or { id, error }
 * Frames stay UNMIRRORED: only the on-screen preview is mirrored (CSS). Never flip here.
 */
let canvas = null;
let ctx = null;

self.onmessage = async (e) => {
  const { id, bitmap, maxWidth, quality } = e.data;
  try {
    const w = Math.min(maxWidth, bitmap.width);
    const h = Math.round((bitmap.height / bitmap.width) * w);
    if (!canvas || canvas.width !== w || canvas.height !== h) {
      canvas = new OffscreenCanvas(w, h);
      ctx = canvas.getContext("2d");
    }
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close();
    const blob = await canvas.convertToBlob({ type: "image/jpeg", quality });
    self.postMessage({ id, blob });
  } catch (err) {
    try { bitmap.close(); } catch {}
    self.postMessage({ id, error: String(err && err.message || err) });
  }
};
