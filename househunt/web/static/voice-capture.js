/* Capture only. The browser handles the microphone and sample rate conversion. */
class VoiceCapture extends AudioWorkletProcessor {
  constructor() { super(); this.buffer = new Float32Array(4096); this.used = 0; this.frames = 0; }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const sample of input) {
      if (this.frames >= sampleRate * 120) return false;
      this.buffer[this.used++] = sample;
      this.frames++;
      if (this.used === this.buffer.length || this.frames >= sampleRate * 120) {
        const chunk = this.buffer.slice(0, this.used);
        this.port.postMessage({ chunk, done: this.frames >= sampleRate * 120 }, [chunk.buffer]);
        this.used = 0;
      }
    }
    return this.frames < sampleRate * 120;
  }
}
registerProcessor('keyhunt-voice-capture', VoiceCapture);
