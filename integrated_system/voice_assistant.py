#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""voice_assistant.py - 集成语音助手（云端 LLM 对话 + 意图识别控制）

全链路：麦克风 → VAD → Vosk ASR → DeepSeek LLM → 意图分流 → TTS 播报 + 运动控制

设计参考 ESP32 小智项目：
- 端侧只做语音 I/O，LLM 推理走云端
- LLM 同时完成对话回复和运动意图识别
- 控制指令通过仲裁器(5005)下发，优先级: 避障 > 语音 > 手势

用法:
  python3 voice_assistant.py
  python3 voice_assistant.py --mic plughw:1,0 --speaker plughw:0,0
  python3 voice_assistant.py --no-wakeup       # 跳过唤醒词
  python3 voice_assistant.py --tts edge         # 强制 edge-tts（需联网）
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import wave

# 把本目录加入 path 以导入 llm_dialogue
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llm_dialogue import LlmDialogue

# ---------- Vosk ASR ----------
try:
    from vosk import Model, KaldiRecognizer
except ImportError:
    print('[ERROR] pip3 install vosk')
    sys.exit(1)

# ---------- VAD ----------
try:
    import webrtcvad
    HAS_VAD = True
except ImportError:
    HAS_VAD = False

# ---------- TTS ----------
try:
    import sherpa_onnx
    import numpy as np
    import soundfile as sf
    HAS_SHERPA = True
except ImportError:
    HAS_SHERPA = False

try:
    import edge_tts
    import asyncio
    HAS_EDGE = True
except ImportError:
    HAS_EDGE = False

import audioop


# ============ 快速指令匹配（绕过 LLM，降低延迟） ============
FAST_COMMANDS = {
    '坐下': 'sit', '坐下来': 'sit', '坐下吧': 'sit',
    '站立': 'stand', '站起来': 'stand', '起来': 'stand',
    '趴下': 'crouch', '爬下': 'crouch', '卧倒': 'crouch',
    '停下': 'stop', '停止': 'stop', '别动': 'stop', '不要动': 'stop', '停': 'stop',
    '前进': 'forward', '向前走': 'forward', '往前走': 'forward', '直走': 'forward',
    '后退': 'backward', '向后走': 'backward', '倒车': 'backward',
    '左转': 'turn_left', '向左转': 'turn_left', '左拐': 'turn_left',
    '右转': 'turn_right', '向右转': 'turn_right', '右拐': 'turn_right',
}

# 持续型动作：需要定时自动停
CONTINUOUS_ACTIONS = {'forward', 'backward', 'turn_left', 'turn_right'}

# sit.py 动作映射（语音 LLM action → sit.py action）
SIT_ACTION_MAP = {
    'sit': 'sit', 'stand': 'stand', 'stop': 'stop', 'crouch': 'crouch',
    'forward': 'walk',          # sit.py 用 walk 表示前进
    'backward': 'backward',     # sit.py 原生支持 backward
    'turn_left': 'turn_left', 'turn_right': 'turn_right',
}

# 动作中文名（用于序列播报）
ACTION_NAMES = {
    'sit': '坐下', 'stand': '站起来', 'stop': '停下', 'crouch': '趴下',
    'forward': '前进', 'backward': '后退',
    'turn_left': '左转', 'turn_right': '右转',
}

# 按词长降序，保证最长匹配优先（"站起来"先于"起来"，"坐下来"先于"坐下"）
_FAST_PHRASES = sorted(FAST_COMMANDS.items(), key=lambda kv: len(kv[0]), reverse=True)


def extract_action_sequence(text: str) -> list:
    """按出现顺序从文本中提取动作序列（不重叠最长匹配）

    例: "先站起来然后再坐下" → ['stand', 'sit']
        "前进再左转"         → ['forward', 'turn_left']
    """
    result = []
    i, n = 0, len(text)
    while i < n:
        matched = False
        for phrase, cmd in _FAST_PHRASES:
            if text.startswith(phrase, i):
                # 相邻相同动作去重（如"站起来站起来"只执行一次）
                if not result or result[-1] != cmd:
                    result.append(cmd)
                i += len(phrase)
                matched = True
                break
        if not matched:
            i += 1
    return result


# ============ TTS 后端 ============
class SherpaTts:
    """sherpa-onnx 离线 TTS"""
    def __init__(self, model_root='/opt/sherpa-models'):
        tts_dir = os.path.join(model_root, 'matcha-zh-baker')
        vocoder_dir = os.path.join(model_root, 'vocoder')

        model_candidates = [
            os.path.join(tts_dir, 'model-steps-3.onnx'),
            os.path.join(tts_dir, 'matcha-zh-baker.onnx'),
            os.path.join(tts_dir, 'model.onnx'),
        ]
        model_path = next((p for p in model_candidates if os.path.exists(p)), None)

        vocoder_candidates = [
            os.path.join(vocoder_dir, 'vocos-22khz-univ.onnx'),
            os.path.join(vocoder_dir, 'hifigan_v2.onnx'),
            os.path.join(vocoder_dir, 'hifigan_v1.onnx'),
        ]
        vocoder_path = next((p for p in vocoder_candidates if os.path.exists(p)), None)

        if not model_path:
            raise FileNotFoundError(f'Matcha 模型不存在: {tts_dir}')
        if not vocoder_path:
            raise FileNotFoundError(f'Vocoder 不存在: {vocoder_dir}')

        tokens_path = os.path.join(tts_dir, 'tokens.txt')
        lexicon_path = os.path.join(tts_dir, 'lexicon.txt')
        lexicon_val = lexicon_path if os.path.exists(lexicon_path) else ''

        tts_config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                    acoustic_model=model_path,
                    vocoder=vocoder_path,
                    lexicon=lexicon_val,
                    tokens=tokens_path,
                ),
            ),
        )
        self.tts = sherpa_onnx.OfflineTts(tts_config)
        print(f'[TTS] sherpa Matcha 加载成功')

    def speak(self, text: str, device: str, volume_db='+0'):
        audio = self.tts.generate(text)
        samples = np.array(audio.samples, dtype=np.float32)
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            raw = f.name
        out = raw.replace('.wav', '.out.wav')
        sf.write(raw, samples, audio.sample_rate)
        subprocess.run(
            ['ffmpeg', '-y', '-i', raw,
             '-af', f'volume={volume_db}dB',
             '-ar', '44100', '-ac', '1', out],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ['aplay', '-D', device, out],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        os.remove(raw)
        os.remove(out)


class EdgeTts:
    """edge-tts 在线 TTS（需联网）"""
    def __init__(self, voice='zh-CN-XiaoxiaoNeural'):
        self.voice = voice
        print(f'[TTS] edge-tts 加载成功, voice={voice}')

    def speak(self, text: str, device: str, volume_db='+0'):
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            mp3_path = f.name
        wav_path = mp3_path.replace('.mp3', '.wav')
        asyncio.run(self._save(text, mp3_path))
        subprocess.run(
            ['ffmpeg', '-y', '-i', mp3_path,
             '-af', f'volume={volume_db}dB',
             '-ar', '44100', '-ac', '1', wav_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ['aplay', '-D', device, wav_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        os.remove(mp3_path)
        os.remove(wav_path)

    async def _save(self, text, mp3_path):
        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(mp3_path)


def init_tts(backend: str):
    if backend in ('sherpa', 'auto'):
        if HAS_SHERPA:
            try:
                return SherpaTts()
            except Exception as e:
                print(f'[WARN] sherpa 初始化失败: {e}')
                if backend == 'sherpa':
                    return None
    if backend in ('edge', 'auto'):
        if HAS_EDGE:
            return EdgeTts()
        print('[WARN] edge-tts 未安装: pip3 install edge-tts')
    return None


# ============ VAD 录音 ============
def record_wav(device: str, wav_path: str, seconds: int, rate: int = 16000,
               use_vad: bool = True, vad_aggressiveness: int = 2,
               silence_dur: float = 1.0, gain_db: int = 0):
    if use_vad and HAS_VAD:
        return _record_with_vad(device, wav_path, rate, vad_aggressiveness,
                                silence_dur, gain_db)
    raw = wav_path + '.raw.wav'
    subprocess.run(
        ['arecord', '-D', device, '-d', str(seconds),
         '-f', 'S16_LE', '-r', str(rate), '-c', '1', '-t', 'wav', raw],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    _postprocess_audio(raw, wav_path, gain_db)


def _record_with_vad(device, wav_path, sample_rate, aggressiveness, silence_dur, gain_db):
    vad = webrtcvad.Vad(aggressiveness)
    frame_duration = 30  # ms
    frame_size = int(sample_rate * frame_duration / 1000) * 2

    proc = subprocess.Popen(
        ['arecord', '-D', device,
         '-f', 'S16_LE', '-r', str(sample_rate), '-c', '1',
         '-t', 'raw', '-q'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )

    raw_path = wav_path + '.raw.wav'
    raw_frames = []
    state = 'waiting'
    wait_start = time.time()
    max_wait = 10.0
    speech_start = 0
    silence_start = 0
    total_speech = 0
    speech_frame_count = 0
    min_speech_frames = 6
    silence_frame_count = 0
    min_silence_frames = int(silence_dur * 1000 / frame_duration)

    try:
        while True:
            frame = proc.stdout.read(frame_size)
            if len(frame) < frame_size:
                break
            is_speech = vad.is_speech(frame, sample_rate)
            now = time.time()

            if state == 'waiting':
                if is_speech:
                    speech_frame_count += 1
                    raw_frames.append(frame)
                    if speech_frame_count >= min_speech_frames:
                        state = 'speaking'
                        speech_start = now
                        silence_start = now
                        silence_frame_count = 0
                        print('[VAD] 说话开始', end='', flush=True)
                else:
                    speech_frame_count = 0
                    raw_frames = []
                    if now - wait_start > max_wait:
                        print('[VAD] 超时', end='', flush=True)
                        break

            elif state == 'speaking':
                raw_frames.append(frame)
                if is_speech:
                    silence_frame_count = 0
                    silence_start = now
                    total_speech = now - speech_start
                    if total_speech > 8.0:
                        print(' → 超时', end='', flush=True)
                        break
                else:
                    silence_frame_count += 1
                    if silence_frame_count >= min_silence_frames:
                        print(f' → 结束({total_speech:.1f}s)', end='', flush=True)
                        break
    finally:
        proc.terminate()
        proc.wait()

    if not raw_frames:
        with wave.open(wav_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
        return

    with wave.open(raw_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b''.join(raw_frames))

    _postprocess_audio(raw_path, wav_path, gain_db)


def _postprocess_audio(raw_path, wav_path, gain_db):
    if gain_db != 0:
        subprocess.run(
            ['sox', raw_path, wav_path, 'gain', str(gain_db)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        os.remove(raw_path)
    else:
        os.rename(raw_path, wav_path)


def wav_to_text(model: Model, wav_path: str) -> str:
    """Vosk 识别 wav → 文本"""
    wf = wave.open(wav_path, 'rb')
    if wf.getframerate() != 16000:
        pcm = wf.readframes(wf.getnframes())
        pcm, _ = audioop.ratecv(pcm, 2, 1, wf.getframerate(), 16000, None)
        wf.close()
        tmp = wav_path + '.16k.wav'
        with wave.open(tmp, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm)
        wf = wave.open(tmp, 'rb')
        tmp_path = tmp
    else:
        tmp_path = None

    rec = KaldiRecognizer(model, 16000)
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        rec.AcceptWaveform(data)
    result = json.loads(rec.FinalResult())
    wf.close()
    if tmp_path:
        os.remove(tmp_path)
    return result.get('text', '').strip()


# ============ 运动控制 ============
def execute_action_sequence(actions: list, arbiter_ip: str, arbiter_port: int,
                            move_duration: float = 2.5,
                            discrete_wait: float = 2.0,
                            heartbeat: float = 0.4):
    """按顺序执行动作序列，每个动作时长可控

    actions: [{'action': 'forward', 'duration': 3.0}, ...]
             duration 为 None 时用默认值（持续型=move_duration, 离散型=discrete_wait）

    注意: 仲裁器语音通道 1s 无包会超时自动停车, 所以持续型动作
    必须以 heartbeat 间隔心跳重发来保持通道存活, 否则会被截断成 1s。
    """
    for idx, item in enumerate(actions):
        action = item['action']
        duration = item.get('duration')
        sit_action = SIT_ACTION_MAP.get(action, action)
        is_last = (idx == len(actions) - 1)

        if action in CONTINUOUS_ACTIONS:
            dur = duration if duration is not None else move_duration
            dur = max(0.5, min(30.0, dur))
            print(f'  [SEQ {idx+1}/{len(actions)}] {action} 持续 {dur:.1f}s')
            _send_continuous(sit_action, arbiter_ip, arbiter_port, dur, heartbeat)
        else:
            print(f'  [SEQ {idx+1}/{len(actions)}] {action}')
            _send_udp(arbiter_ip, arbiter_port, sit_action)
            if not is_last:
                # 离散动作之间留出执行时间; stop 只需短暂间隔
                if action == 'stop':
                    wait = 0.5
                else:
                    wait = duration if duration is not None else discrete_wait
                    wait = max(0.0, min(30.0, wait))
                time.sleep(wait)


def _send_continuous(sit_action: str, ip: str, port: int,
                     duration: float, heartbeat: float = 0.4):
    """持续动作: 心跳重发保持仲裁通道活跃, 到时后自动 stop"""
    t_end = time.time() + duration
    while True:
        _send_udp(ip, port, sit_action)
        remaining = t_end - time.time()
        if remaining <= 0:
            break
        time.sleep(min(heartbeat, remaining))
    _send_udp(ip, port, 'stop')


def _send_udp(ip: str, port: int, action: str):
    """发送带 source=voice 的 JSON 到仲裁器"""
    payload = json.dumps({'action': action, 'source': 'voice'}, ensure_ascii=False)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(payload.encode('utf-8'), (ip, port))
        sock.close()
        print(f'  [UDP] → {action}  (→ {ip}:{port})')
    except Exception as e:
        print(f'  [UDP] 发送失败: {e}')


# ============ 主程序 ============
def load_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        print(f'[ERROR] 配置文件不存在: {config_path}')
        print('请复制 config.example.json 为 config.json 并填入 API Key')
        sys.exit(1)
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description='集成语音助手（云端 LLM）')
    parser.add_argument('--config', default=None,
                        help='配置文件路径 (默认: 同目录 config.json)')
    parser.add_argument('--mic', default=None, help='麦克风 ALSA 设备')
    parser.add_argument('--speaker', default=None, help='音响 ALSA 设备')
    parser.add_argument('--tts', choices=['auto', 'sherpa', 'edge'], default=None)
    parser.add_argument('--no-wakeup', action='store_true', help='关闭唤醒词')
    parser.add_argument('--no-vad', action='store_true', help='关闭 VAD')
    parser.add_argument('--gain', type=int, default=None, help='录音增益 dB')
    parser.add_argument('--silence', type=float, default=None, help='静音结束秒数')
    parser.add_argument('--vad-aggressiveness', type=int, default=None)
    parser.add_argument('--volume', default=None, help='TTS 音量 dB')
    parser.add_argument('--move-sec', type=float, default=None, help='持续动作默认秒数')
    parser.add_argument('--discrete-sec', type=float, default=None,
                        help='序列中离散动作(sit/stand)后的等待秒数')
    args = parser.parse_args()

    # 加载配置
    config_path = args.config or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'config.json')
    config = load_config(config_path)

    voice_cfg = config.get('voice', {})
    motion_cfg = config.get('motion', {})
    asr_cfg = config.get('asr', {})

    # 命令行参数覆盖配置
    mic = args.mic or voice_cfg.get('mic', 'plughw:1,0')
    speaker = args.speaker or voice_cfg.get('speaker', 'plughw:0,0')
    tts_backend = args.tts or voice_cfg.get('tts_backend', 'auto')
    gain = args.gain if args.gain is not None else voice_cfg.get('gain_db', 10)
    silence = args.silence or voice_cfg.get('silence_duration', 1.0)
    vad_aggr = args.vad_aggressiveness or voice_cfg.get('vad_aggressiveness', 2)
    volume = args.volume or voice_cfg.get('tts_volume_db', '-5')
    move_sec = args.move_sec or motion_cfg.get('move_duration_sec', 2.5)
    discrete_sec = args.discrete_sec or motion_cfg.get('discrete_wait_sec', 2.0)
    wakeup_enabled = not args.no_wakeup and voice_cfg.get('wakeup_enabled', True)
    wakeup_keywords = voice_cfg.get('wakeup_keywords', ['小狗'])
    vosk_model_path = asr_cfg.get('vosk_model_path', '/app/puppy_ws/models/vosk-model-small-cn-0.22')

    arbiter_ip = motion_cfg.get('arbiter_ip', '127.0.0.1')
    arbiter_port = motion_cfg.get('arbiter_port', 5005)

    use_vad = HAS_VAD and not args.no_vad

    print('=' * 60)
    print(' 集成语音助手（云端 LLM 对话 + 意图识别控制）')
    print(f' 麦克风: {mic}')
    print(f' 音响:   {speaker}')
    print(f' TTS:    {tts_backend}')
    print(f' 音量:   {volume}dB')
    print(f' 录音:   {"VAD" if use_vad else "固定秒数"} + {gain}dB增益')
    print(f' 唤醒词: {"关闭" if not wakeup_enabled else wakeup_keywords}')
    print(f' LLM:    {config["llm"].get("provider", "?")} / {config["llm"].get("model", "?")}')
    print(f' 控制:   UDP → {arbiter_ip}:{arbiter_port} (仲裁器)')
    print(f' 移动持续: {move_sec} 秒, 离散动作间隔: {discrete_sec} 秒')
    print('=' * 60)

    # 初始化 ASR
    if not os.path.exists(vosk_model_path):
        print(f'[ERROR] Vosk 模型不存在: {vosk_model_path}')
        return
    print('[ASR] 加载 Vosk 模型...', end=' ', flush=True)
    asr_model = Model(vosk_model_path)
    print('OK')

    # 初始化 TTS
    tts = init_tts(tts_backend)
    if tts is None:
        print('[ERROR] 没有 TTS 后端可用，退出')
        return

    # 初始化 LLM
    print('[LLM] 初始化 DeepSeek...', end=' ', flush=True)
    try:
        llm = LlmDialogue(config)
    except Exception as e:
        print(f'失败: {e}')
        return
    print('OK')

    # 开场白
    if tts:
        tts.speak('你好，我是小狗。请说小狗唤醒我，然后就可以和我聊天了。',
                  speaker, volume)

    wakeup_mode = wakeup_enabled

    while True:
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                wav_path = f.name

            if use_vad:
                print('\n[请说话] 随时开始...', end=' ', flush=True)
            else:
                print('\n[录音] 4 秒...', end=' ', flush=True)

            record_wav(mic, wav_path, 4,
                       use_vad=use_vad,
                       vad_aggressiveness=vad_aggr,
                       silence_dur=silence,
                       gain_db=gain)
            text = wav_to_text(asr_model, wav_path)
            os.remove(wav_path)

            if not text:
                print('（没听到）')
                continue
            print(f'\n识别: "{text}"')

            # 唤醒词检测
            if wakeup_mode:
                if any(kw in text for kw in wakeup_keywords):
                    print('  → 唤醒成功！')
                    if tts:
                        tts.speak('我在，请说。', speaker, volume)
                    wakeup_mode = False
                    continue
                else:
                    print('  → 未唤醒')
                    continue

            # ===== 快速指令匹配（按出现顺序提取动作序列，绕过 LLM 降低延迟） =====
            fast_seq = extract_action_sequence(text)

            if fast_seq:
                names = [ACTION_NAMES.get(a, a) for a in fast_seq]
                print(f'  → 快速指令序列: {fast_seq}')
                if len(names) == 1:
                    reply_text = f'好的，我{names[0]}了'
                else:
                    reply_text = '好的，我先' + '，再'.join(names)

                actions = [{'action': a, 'duration': None} for a in fast_seq]
                # 单个离散动作: 先动后说（响应更快）; 其他情况: 先说后动
                if len(fast_seq) == 1 and fast_seq[0] not in CONTINUOUS_ACTIONS:
                    execute_action_sequence(actions, arbiter_ip, arbiter_port,
                                            move_sec, discrete_sec)
                    if tts:
                        tts.speak(reply_text, speaker, volume)
                else:
                    if tts:
                        tts.speak(reply_text, speaker, volume)
                    execute_action_sequence(actions, arbiter_ip, arbiter_port,
                                            move_sec, discrete_sec)
                continue

            # ===== LLM 对话 + 意图识别 =====
            print('  → 调用 LLM...')
            try:
                reply, actions = llm.chat(text)
            except Exception as e:
                print(f'  [LLM] 错误: {e}')
                if tts:
                    tts.speak('抱歉，我好像走神了，请再说一遍。', speaker, volume)
                continue

            print(f'  LLM回复: {reply}')
            if actions:
                print(f'  LLM动作序列: {actions}')

            # TTS 播报
            if tts:
                tts.speak(reply, speaker, volume)

            # 按顺序执行动作序列（每个动作时长由 LLM 指定, 缺省用默认值）
            if actions:
                execute_action_sequence(actions, arbiter_ip, arbiter_port,
                                        move_sec, discrete_sec)

        except KeyboardInterrupt:
            print('\n再见！')
            break
        except subprocess.CalledProcessError as e:
            print(f'[ERROR] {e}')
            time.sleep(1)
        except Exception as e:
            print(f'[ERROR] {repr(e)}')
            time.sleep(1)


if __name__ == '__main__':
    main()
