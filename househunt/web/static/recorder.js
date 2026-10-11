const root = document.querySelector('#voice-enrollment');
const el = (name) => document.querySelector(`#voice-${name}`);
const endpoint = root.dataset.api;
let context, stream, capture, source, recording = false, starting = false, chunks = [], frames = 0;
let sampleBlob, sampleURL, pollTimer, enrollment, phase = 'loading', unloaded = false;
const status = (text) => { el('status').textContent = text; };
const hide = (name, hidden) => { el(name).hidden = hidden; };
const readName = () => el('name').value.trim();

function ready() {
  el('start').disabled = starting || recording || phase !== 'empty' || !el('consent').checked || !readName();
}
el('consent').addEventListener('change', ready);
el('name').addEventListener('input', () => { el('name-preview').textContent = readName() || 'Your'; ready(); });

async function request(suffix = '', options = {}) {
  const response = await fetch(endpoint + suffix, { ...options, credentials: 'same-origin', cache: 'no-store',
    headers: { 'X-KeyHunt-Voice': '1', ...options.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : 'That step could not finish. Please try again.');
  }
  return response.json();
}

async function refresh() {
  clearTimeout(pollTimer);
  try {
    const data = await request();
    phase = data.phase; enrollment = data.enrollmentId;
    hide('record-form', phase !== 'empty');
    hide('audition', phase !== 'audition');
    hide('approved', phase !== 'approved');
    hide('retry', !data.canRetryPreview);
    hide('remove', !['audition', 'approved', 'error', 'verification_required'].includes(phase));
    if (phase === 'empty') {
      status(data.canCreate ? 'Ready when you are. Record two minutes, then listen back.' : 'Voice creation is not connected yet. Ask your host to finish setup.');
      if (!data.canCreate) phase = 'unavailable';
    } else if (phase === 'creating' || phase === 'creating_preview') {
      status('Creating your voice and a short preview. You can leave this page and return.');
      if (!unloaded) pollTimer = setTimeout(refresh, 2000);
    } else if (phase === 'audition') {
      status('Your voice preview is ready.');
      const url = `${endpoint}/preview?v=${enrollment}`;
      if (el('preview').getAttribute('src') !== url) { el('preview').src = url; el('approve').disabled = true; }
    } else if (phase === 'approved') {
      status('Your voice is approved.');
      el('availability').textContent = data.callingEnabled ? 'Custom voice calling is enabled on this server.' : 'Your voice is saved. Your host still needs to enable custom voice calling.';
    } else if (phase === 'verification_required') {
      status('ElevenLabs needs speaker verification. Ask your host to open the voice in ElevenLabs to complete it.');
    } else status(data.error || 'Voice setup needs attention.');
    ready();
  } catch (error) { status(error.message); ready(); }
}

function cleanupMic() {
  recording = false;
  if (capture) { capture.port.onmessage = null; capture.disconnect(); capture = null; }
  if (source) { source.disconnect(); source = null; }
  stream?.getTracks().forEach((track) => track.stop()); stream = null;
  if (context) { void context.close().catch(() => {}); context = null; }
  hide('stop', true); hide('level', true);
  el('name').disabled = false; el('consent').disabled = false;
}

function resetSample() {
  if (sampleURL) URL.revokeObjectURL(sampleURL);
  sampleURL = undefined; sampleBlob = undefined; chunks = []; frames = 0;
  el('original').removeAttribute('src');
  el('progress').value = 0;
  el('timer').textContent = '0:00 / 2:00';
  hide('sample', true); hide('start', false);
  ready();
}

function wav(chunks, rate) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const samples = new Float32Array(total);
  let offset = 0;
  for (const chunk of chunks) { samples.set(chunk, offset); offset += chunk.length; }
  const count = Math.round(total * 16000 / rate);
  const buffer = new ArrayBuffer(44 + count * 2), view = new DataView(buffer);
  const text = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  text(0, 'RIFF'); view.setUint32(4, 36 + count * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, count * 2, true);
  for (let i = 0; i < count; i++) {
    const pos = i * rate / 16000, start = Math.floor(pos), end = Math.min(samples.length - 1, Math.ceil(pos));
    const sample = Math.max(-1, Math.min(1, samples[start] + (samples[end] - samples[start]) * (pos - start)));
    view.setInt16(44 + i * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

el('start').addEventListener('click', async () => {
  if (starting || recording) return;
  starting = true; ready(); resetSample();
  try {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      throw new Error('Recording needs HTTPS (or localhost) in a current Chrome, Edge, Firefox, or Safari browser.');
    }
    // Microphone access happens only after this explicit button click.
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    if (unloaded) { cleanupMic(); return; }
    context = new AudioContext({ sampleRate: 16000 });
    await context.resume();
    await context.audioWorklet.addModule('/voice-assets/voice-capture.js');
    const rate = context.sampleRate;
    source = context.createMediaStreamSource(stream);
    capture = new AudioWorkletNode(context, 'keyhunt-voice-capture');
    capture.port.onmessage = ({ data }) => {
      chunks.push(data.chunk); frames += data.chunk.length;
      const elapsed = frames / rate;
      el('timer').textContent = `${Math.floor(elapsed / 60)}:${String(Math.floor(elapsed % 60)).padStart(2, '0')} / 2:00`;
      el('progress').value = Math.min(120, elapsed);
      let sum = 0; for (const sample of data.chunk) sum += sample * sample;
      const rms = Math.sqrt(sum / data.chunk.length);
      el('level').value = Math.min(1, rms * 5);
      el('tip').textContent = rms < .005 ? 'Speak naturally and keep reading. Check the microphone if the level stays low.' : 'Good—keep reading at your normal pace. Repeat a paragraph if you finish early.';
      if (data.done) {
        sampleBlob = wav(chunks, rate); chunks = [];
        cleanupMic(); sampleURL = URL.createObjectURL(sampleBlob);
        el('original').src = sampleURL; hide('sample', false); hide('start', true);
        status('Two minutes recorded. Listen back, then create your voice.');
      }
    };
    source.connect(capture); capture.connect(context.destination); // processor outputs silence; no microphone feedback
    recording = true; el('name').disabled = true; el('consent').disabled = true;
    hide('stop', false); hide('level', false);
    status('Recording your voice. Read the script naturally.');
    stream.getAudioTracks()[0].addEventListener('ended', () => {
      if (recording) { cleanupMic(); resetSample(); status('Microphone disconnected. Please start a new recording.'); }
    });
  } catch (error) {
    cleanupMic(); status(error.name === 'NotAllowedError' ? 'Microphone access was declined. Allow it in your browser, then try again.' : error.message);
  } finally { starting = false; ready(); }
});
el('stop').addEventListener('click', () => { cleanupMic(); resetSample(); status('Recording discarded. Ready for a fresh take.'); });
el('retake').addEventListener('click', () => { resetSample(); status('Ready for a fresh take.'); });
el('upload').addEventListener('click', async () => {
  if (!sampleBlob || !el('consent').checked) return;
  el('upload').disabled = true; el('retake').disabled = true;
  status('Sending your recording to create your voice…');
  try {
    await request('', { method: 'POST', body: sampleBlob, headers: { 'Content-Type': 'audio/wav', 'X-Voice-Consent': 'true', 'X-Voice-Name': encodeURIComponent(readName()) } });
    resetSample(); await refresh();
  } catch (error) { status(error.message + ' If upload status is uncertain, refresh this page before retrying.'); }
  finally { el('upload').disabled = false; el('retake').disabled = false; }
});
el('preview').addEventListener('ended', () => { el('approve').disabled = false; });
el('retry').addEventListener('click', async () => {
  el('retry').disabled = true;
  try { await request('/preview', { method: 'POST' }); await refresh(); }
  catch (error) { status(error.message); }
  finally { el('retry').disabled = false; }
});
el('approve').addEventListener('click', async () => {
  el('approve').disabled = true;
  try { await request('/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enrollmentId: enrollment, approved: true }) }); await refresh(); }
  catch (error) { status(error.message); el('approve').disabled = false; }
});
el('remove').addEventListener('click', async () => {
  if (!window.confirm('Remove this voice from KeyHunt and delete the clone created here from ElevenLabs? Existing call recordings are kept with their calls.')) return;
  el('remove').disabled = true;
  try { await request('', { method: 'DELETE' }); resetSample(); await refresh(); }
  catch (error) { status(error.message); }
  finally { el('remove').disabled = false; }
});
window.addEventListener('pagehide', () => { unloaded = true; cleanupMic(); clearTimeout(pollTimer); if (sampleURL) URL.revokeObjectURL(sampleURL); chunks = []; });
window.addEventListener('beforeunload', (event) => { if (recording) { event.preventDefault(); event.returnValue = ''; } });
void refresh();
