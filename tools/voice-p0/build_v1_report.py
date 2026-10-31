#!/usr/bin/env python3
"""Publish aggregate V1 evidence. Recognition text remains only in ignored lab results."""
import argparse
import hashlib
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('id')
parser.add_argument('--target-switch-id')
parser.add_argument('--instrumentation-log', type=Path, required=True)
args = parser.parse_args()
prefix = Path(__file__).resolve().parent / 'results' / args.id
raw = prefix.with_suffix('.jsonl')
driver_file = Path(str(prefix) + '-driver.json')
driver = json.loads(driver_file.read_text())
rows = [json.loads(line) for line in raw.read_text().splitlines()]
states = [x for x in rows if x['event'] == 'host_state']
marks = {x['name']: x['device_ms'] for x in driver['events']}

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    index = (len(values)-1)*p
    lo, hi = math.floor(index), math.ceil(index)
    return values[lo] + (values[hi]-values[lo])*(index-lo)

def phase(label):
    start, end = marks[label+'_begin'], marks[label+'_done']
    selected = [x for x in states if start <= x['time_ms'] <= end]
    composing = []
    for x in selected:
        if x['composing_start'] >= 0 and (not composing or composing[-1]['text'] != x['text']):
            composing.append(x)
    release = next(x['device_ms'] for x in driver['events'] if x['name'] == 'release' and start < x['device_ms'] < end)
    final = next(x for x in selected if x['time_ms'] >= release - 150 and x['composing_start'] == -1)
    return dict(first_composing_from_down_ms=composing[0]['time_ms']-start,
        changed_update_gap_p95_ms=percentile([b['time_ms']-a['time_ms'] for a,b in zip(composing, composing[1:])], .95),
        release_to_finished_ms=max(0, final['time_ms']-release),
        composing_update_count=len(composing), final_text_length=len(final['text']))

before_cancel = [x for x in states if x['time_ms'] < marks['cancel_begin']][-1]
after_cancel = [x for x in states if marks['back_cancel']-500 <= x['time_ms'] <= marks['cancel_done']][-1]
switch_id = args.target_switch_id or args.id
switch_file = prefix.parent / (switch_id + '.jsonl')
switch_driver = json.loads((prefix.parent / (switch_id + '-driver.json')).read_text())
switch_rows = [json.loads(line) for line in switch_file.read_text().splitlines()]
switch_mark = next(x['device_ms'] for x in switch_driver['events'] if x['name'] == 'switch_begin')
focus = [x for x in switch_rows if x['event'] == 'host_state' and x['time_ms'] >= switch_mark and x.get('focused_editor') == 2]
checks = dict(short_tap_is_one_space=any(x['text'] == ' ' and x['composing_start'] == -1 and
    x['time_ms'] < marks['cold_begin'] for x in states),
    explicit_cancel_preserves_previous_text=after_cancel['text'] == before_cancel['text'] and after_cancel['composing_start'] == -1,
    second_editor_really_focused=bool(focus),
    no_late_text_in_second_editor=bool(focus) and all(x['second_text'] == '' for x in focus),
    no_decoder_protocol_inserted=all('<|' not in x['text'] and '|>' not in x['text'] for x in states))
assert all(checks.values()), checks
instrument = args.instrumentation_log.read_text()
assert 'OK (2 tests)' in instrument, instrument
suites = [ET.parse(p).getroot().attrib for p in (ROOT/'app/build/test-results/testDebugUnitTest').glob('TEST-*.xml')]
unit_count = sum(int(x['tests']) for x in suites)
assert all(int(x['failures'])+int(x['errors']) == 0 for x in suites)
apk = max((ROOT/'app/build/outputs/apk/debug').glob('*arm64-v8a-debug.apk'), key=lambda p:p.stat().st_mtime)
paths = subprocess.check_output(['git','diff','--name-only'], cwd=ROOT, text=True).splitlines()
paths += subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines()
sources = {name: sha(ROOT/name) for name in sorted(set(paths)) if name.startswith('app/') and
    (ROOT/name).is_file() and Path(name).suffix in ('.kt','.xml','.kts','.json','.pro')}
metrics = dict(run=args.id, target_switch_run=switch_id, target_switch_host_sha256=sha(switch_file), device='NX888J / SM8850 / Android 16 / 12 GB',
    configuration=dict(model='Qwen3-ASR-0.6B INT8',runtime='sherpa-onnx 2.0.1',cpu_threads=2,
        core_ms=6000, overlap_ms=1000,hop_ms=500,max_input_ms=7000,audio_ring_seconds=20,
        total_recording_cap=False,memory_mode='default',max_total_len=512,max_new_tokens=256),
    cold=phase('cold'),warm=phase('warm'),checks=checks,
    sampled_peak_process_pss_mib=max(x['pss_kib'] for x in driver['memory'])/1024,
    memory_sampling='dumpsys meminfo, about 1 second; not a native allocation high-water mark',
    unit_tests_passed=unit_count,instrumentation_tests_passed=2,
    apk_bytes=apk.stat().st_size,apk_sha256=sha(apk),
    host_jsonl_sha256=sha(raw),driver_json_sha256=sha(driver_file),
    instrumentation_log_sha256=sha(args.instrumentation_log),source_sha256=sources,
    limits=['one end-to-end run, not P95 across sessions',
        'device speaker stimulus plus ambient capture; no CER/WER claimed for this run',
        'first result is from key down, including long-press and cold loading, not stable correct-word latency',
        '4 KB page device; 16 KB runtime not tested'])
installed_file = prefix.parent / (args.id + '-installed-apk.json')
if installed_file.exists():
    installed = json.loads(installed_file.read_text())
    assert installed['sha256'] == metrics['apk_sha256']
    metrics['installed_apk_matches_final_build'] = installed['installed_matches']
(ROOT/'docs/qwen3-asr-v1-metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
version_source = (ROOT/'build-logic/convention/src/main/kotlin/Versions.kt').read_text()
version_name = re.search(r'baseVersionName = "([^"]+)"', version_source)[1]
css=(ROOT/'docs/qwen3-asr-voice-input-spec.html').read_text().split('<style>')[1].split('</style>')[0]
f=lambda ms: '≤0.15 秒（观测精度内）' if ms < 150 else f'{ms/1000:.2f} 秒'
configrows=''.join(f'<tr><td>{a}</td><td>{b}</td></tr>' for a,b in [
 ('识别器','Qwen3-ASR-0.6B INT8，sherpa-onnx 2.0.1；权重版本 68818b2'),
 ('推理','CPU · 2 线程 · 默认 arena / prepack；上下文 512，输出预算 256 token'),
 ('窗口','每段 6 秒新音频，左侧重叠 1 秒；单次最多 7 秒，按顺序处理所有段'),
 ('刷新','至少积累 0.8 秒开始预览，之后每新增 0.5 秒可刷新；单 worker 不并发解码'),
 ('存储','20 秒固定音频 ring（约 1.22 MiB），超负荷明确报错，不静默跳段'),
 ('总时长','无产品总录音时长上限；正常由原始手指抬起停止'),
 ('加载与释放','冷启动先录音再加载；同一输入框内缓存模型 60 秒，隐藏、切换目标及空闲内存压力时释放'),
 ('步骤超时','加载 10 秒、松手后定稿 5 秒；保留已显示草稿，撤销迟到写入许可')])
testrows=''.join(f'<tr><td>{name}</td><td>{f(value["first_composing_from_down_ms"])}</td><td>{f(value["changed_update_gap_p95_ms"])}</td><td>{f(value["release_to_finished_ms"])}</td><td>{value["composing_update_count"]}</td></tr>' for name,value in [('冷模型 · 按住 24 秒',metrics['cold']),('同一编辑器热模型 · 按住 12 秒',metrics['warm'])])
html=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qwen3-ASR 语音输入 · 首版交付</title><style>{css}</style></head><body><main>
<header><span class="badge">V1 · 已实现 · NX888J 真机联调</span><h1>以转写质量优先，交付 6＋1 秒方案</h1><p class="lead">长按空格开始收音，识别文字持续覆盖宿主输入框内同一段 composing；松手停止采音并定稿。保留整个键盘，不设总录音时长上限。</p><p class="meta">2026-10-31 · 第一版 · <a href="qwen3-asr-voice-input-spec.html">更新后的 spec</a> · <a href="qwen3-asr-window-p0-report.html">窗口 P0 原始报告</a> · <a href="qwen3-asr-v1-metrics.json">本轮汇总证据</a></p><p class="meta">代码版本：{version_name}；性能数据与 APK 哈希对应所列实验记录。</p></header>
<section><h2>为什么选这组</h2><p>选择默认内存策略、CPU 2 线程、6 秒新音频＋1 秒左重叠。它在已测的连续中文与绕口令中保真度最好；2＋1 秒虽然刷新更快，但边界重复更严重。没有将未经验证的「6＋1 + 低内存」组合直接用作默认。</p>
<div class="scroll"><table><tr><th>同音频 P0</th><th>6＋1 秒 · 首版</th><th>2＋1 秒</th></tr><tr><td>60 秒中文 CER</td><td>14.15%</td><td>25.23%</td></tr><tr><td>21 秒绕口令 CER</td><td>24.29%</td><td>97.86%</td></tr><tr><td>60 秒刷新间隔 P95</td><td>2.39 秒</td><td>0.87 秒</td></tr><tr><td>60 秒松手定稿</td><td>3.40 秒</td><td>0.81 秒</td></tr><tr><td>60 秒采样峰值 PSS</td><td>2343 MiB</td><td>2185 MiB</td></tr></table></div>
<div class="callout warn">这是一组明确取舍后的首版配置，原有延迟与 1.5 GiB 内存增量目标仍未全部达到。选择它的依据是减少重复、漏字和错误回改；P0 的 CER 参考来自模型仓库，并非独立人工标注，样本量也有限。</div></section>
<section><h2>实际配置</h2><table>{configrows}</table></section>
<section><h2>已实现的交互与保护</h2><ul><li>在现有“空格键长按行为”中增加离线语音选项，保留用户原偏好。短按仍输入空格；横滑在长按前移动光标并阻止录音。</li><li>成功启动采音后提供一次开始振动，遵循现有振动偏好；抑制同次手势的通用长按及抬手振动。空格改为“松手结束”，状态占据原候选工具栏，点击 × 取消。</li><li>持续使用 setComposingText 替换整段语音草稿，最终只 finishComposingText 一次；不逐段 commit，不自动发送、回车或补空格。既有可见 Fcitx preedit 先原样定稿。</li><li>原始手指抬起结束；其他手指抬起不结束。系统 CANCEL、返回键、状态栏取消、键盘隐藏、主题重建、目标切换与销毁均撤销写入许可。显式取消只在范围仍可验证时清除本次草稿，其他不确定情况保留已有文字。</li><li>绑定连接与单调会话代次，使用服务的选区预测；外部光标、选区或 composing 变化取消。密码、非空选区、未知光标与 TYPE_NULL 不开始；宿主拒绝 composing 时停止，避免重复提交补救。</li><li>数字静音低能量门限只过滤极弱信号；拒绝模型控制标记与字面 language 输出。它不是完整 VAD，不能保证消除一般噪声、背景人声或弱信号幻觉。Android 10+ 检测系统静音，采音失败明确结束。</li><li>模型固定 SHA-256 校验后解包到 noBackupFilesDir，准备前检查可用空间；不存录音、不记录识别正文、不上传音频。JNI 加载、解码、释放均串行；取消不会并发释放仍在使用的 native 实例。</li></ul></section>
<section><h2>最终版本真机验证</h2><p>{metrics['unit_tests_passed']} 项 JVM 单元测试、2 项设备 instrumentation 测试通过。覆盖十分钟数据写入的固定 ring 与溢出报错、重叠拼接、控制标记过滤、首次模型校验解包及复用、多指抬手与系统 CANCEL。</p><p>以下是正式输入法通过实际触摸、真实麦克风及独立测试编辑器的单次主流程联调与一次目标切换补测。设备播放语音样本作为刺激，同时存在声学环境影响；本轮只验证 composing 与交互，不宣称转写准确率通过。</p>
<div class="scroll"><table><tr><th>会话</th><th>按下到首条 composing</th><th>本次更新间隔 P95</th><th>松手到定稿</th><th>composing 更新次数</th></tr>{testrows}</table></div>
<p>按下到首条结果包含长按阈值、冷加载及刺激音频起始等待，不是稳定正确字词延迟；最终 span 状态以宿主每 100 ms 采样，计时约有 ±0.1 秒误差；极快定稿可能早于 ADB 命令返回的释放标记，因此统一按 ≤0.15 秒记录。两个会话不足以统计跨会话 P95。</p>
<ul><li>短按实际只输入一个空格；边说边显示时宿主存在 composing span，最终 span 清除。</li><li>返回键取消后，之前已定稿文本完整保留，本次草稿清除；松手后立即切换到第二编辑器，确认实际焦点改变，第二框未收到语音文字。</li><li>最终测试未向宿主插入模型控制标记。采样到的整进程峰值 PSS 为 {metrics['sampled_peak_process_pss_mib']:.0f} MiB（包括 Fcitx），并非 native 分配的精确高水位。</li></ul>
<p class="meta">主流程 ID：{args.id}；目标切换补测 ID：{switch_id}。原始识别文字保留在被 Git 忽略的本地 lab results；公开汇总只含指标、源文件哈希与制品哈希。</p></section>
<section><h2>安装与启用</h2><ol><li>安装 ARM64 语音版 APK。当前制品约 {metrics['apk_bytes']/1024**2:.0f} MiB，另需约 941 MiB 私有模型副本及 Android 安装开销；普通构建不携带权重。</li><li>按系统方式启用并切换到该输入法，再打开应用 → 虚拟键盘 → 准备离线语音输入，允许麦克风权限并完成模型准备。</li><li>返回虚拟键盘设置，将“空格键长按行为”改为“离线语音输入（Qwen3-ASR）”。</li><li>在普通文本输入框长按空格，开始反馈后说话，松手定稿；状态栏 × 可取消。测试后恢复原默认输入法和长按偏好，不替用户长期切换。</li></ol>
<p>模型仅在构建阶段按固定版本下载，使用时无需联网。About 开源许可与 assets/voice-notices 包含 Qwen3-ASR、sherpa-onnx、ONNX Runtime 及第三方声明。</p></section>
<section><h2>构建与复现</h2><pre><code>ANDROID_HOME=/home/zero/Android/Sdk ./gradlew \\
  :app:assembleDebug :app:testDebugUnitTest :app:assembleDebugAndroidTest \\
  -PbuildABI=arm64-v8a -PbundleVoiceModel=true --offline --console=plain</code></pre>
<p>首次准备制品需要网络：Gradle 的 prepareVoice 调用 tools/prepare-voice.py，复用缓存或下载固定 AAR 与 6 个模型文件，并校验 SHA-256。上例 --offline 仅约束 Gradle 依赖解析；离线重建还要求模型缓存已备妥。普通构建默认 bundleVoiceModel=false，显式语音包仅允许 ARM64。</p>
<pre><code>python3 tools/voice-p0/verify_production.py \\
  --serial DEVICE_SERIAL --id FRESH_ID
python3 tools/voice-p0/build_v1_report.py FRESH_ID \\
  --instrumentation-log PATH_TO_DEVICE_TEST_OUTPUT</code></pre><p>复现脚本默认触点对应 NX888J 的 1260×2800 竖屏，其他布局使用 --space-x / --space-y；需先安装生产 APK、lab APK 和测试样本，并明确启用语音长按选项。有限录音档位是测试步骤，不是产品时长限制。前置制品与样本准备见 <a href="../tools/voice-p0/README.html">P0 复现说明</a>。</p>
<p class="meta">APK SHA-256：<code>{metrics['apk_sha256']}</code></p></section>
<section><h2>首版仍有的限制</h2><ul><li>目标是此次验证的高内存 ARM64 设备。内存仍约 2.3–2.4 GiB，6＋1 秒窗口在较长讲话中可能需要数秒刷新或定稿；低端机未验证。</li><li>重叠文本匹配没有可靠词级时间戳，重复句、专名、快语速及噪声仍可能重复、漏字或改错；过滤控制标记与静音不等于准确率达标。</li><li>未完成多应用编辑器兼容矩阵、30 次会话稳定性、长时间温控和内存平台验证；不声称无限时长已测。当前实机是 4 KB 页，16 KB 环境未运行验证。设置页只准备磁盘模型，不主动预热推理。</li></ul></section>
</main></body></html>'''
(ROOT/'docs/qwen3-asr-v1-report.html').write_text(html)
print(json.dumps({key:metrics[key] for key in ['cold','warm','checks','sampled_peak_process_pss_mib','unit_tests_passed','apk_bytes','apk_sha256']},ensure_ascii=False,indent=2))
