#!/usr/bin/env python3
"""Render a reviewable report and a small metrics snapshot, excluding full transcripts."""
import hashlib
import html
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    subprocess.run(['python3', str(HERE / 'analyze.py')], check=True, stdout=subprocess.DEVNULL)
    data = json.loads((HERE / 'results/summary.json').read_text())
    good = [x for x in data if x['success']]
    by_id = {x['id']: x for x in good}
    snapshot = []
    for item in good:
        item = dict(item)
        item['config'] = {k: v for k, v in item['config'].items() if k not in ['event', 'time_ms']}
        item['trials'] = [{k: v for k, v in t.items() if k not in ['last_held_text', 'final_text']}
                          | {'final_text_sha256': hashlib.sha256(t['final_text'].encode()).hexdigest(),
                             'final_text_chars': len(t['final_text'])} for t in item['trials']]
        snapshot.append(item)
    (ROOT / 'docs/qwen3-asr-p0-metrics.json').write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + '\n')

    def dist(item, key, field='p95_nearest_rank'):
        d = item.get(key)
        return f'{d[field] / 1000:.2f}' if d else '—'

    def table(headers, rows):
        return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{x}</th>' for x in headers) + \
            '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>' for row in rows) + \
            '</tbody></table></div>'

    offline_ids = ['zh3-t3', 'zh8-t2', 'zh15-t2', 'en30-t2', 'en60-t2']
    offline = table(['输入', '次数', '单次解码中位数 / 最大值（秒）', '采样峰值 PSS / RSS 高水位（MiB）'], [
        [name, by_id[name]['decode_ms']['n'],
         dist(by_id[name], 'decode_ms', 'median') + ' / ' + dist(by_id[name], 'decode_ms', 'max'),
         f"{by_id[name]['peak_pss_mib']:.0f} / {by_id[name]['peak_rss_mib']:.0f}"]
        for name in offline_ids if name in by_id])
    thread_table = table(['线程', '8 秒中文解码中位数（秒）', '最大值（秒）', '次数'], [
        [t, dist(by_id[f'zh8-t{t}'], 'decode_ms', 'median'), dist(by_id[f'zh8-t{t}'], 'decode_ms', 'max'), 3]
        for t in [2, 3, 4] if f'zh8-t{t}' in by_id])
    stream_ids = ['ime-fast3-t2', 'ime-fast5-t2', 'ime-fast8-t2', 'ime-zh15-t2', 'ime-en30-t2', 'ime-en60-t2', 'mic-fast8-t2', 'mic-loud8-t2']
    streamed = table(['输入 / 方式', '会话数', '首条文字 p95（秒）', '变化更新间隔 p95（秒）', '最终等待 p95（秒）', '峰值 PSS（MiB）'], [
        [name, by_id[name]['config']['repeats'], dist(by_id[name], 'first_nonempty_from_audio_start_ms'),
         dist(by_id[name], 'held_changed_update_gap_ms'), dist(by_id[name], 'final_wait_ms'),
         f"{by_id[name]['peak_pss_mib']:.0f}"] for name in stream_ids if name in by_id])
    optimizations = [x for x in good if x['id'].startswith('opt-')]
    optimize_table = table(['实验', '模式', '解码中位数（秒）', '最终等待 p95（秒）', '峰值 / 释放后 PSS（MiB）'], [
        [x['id'], html.escape(x['memory_mode']), dist(x, 'decode_ms', 'median'), dist(x, 'final_wait_ms'),
         f"{x['peak_pss_mib']:.0f} / {x['after_release_pss_mib']:.0f}"] for x in optimizations])
    mic = by_id.get('mic-loud8-t2')
    mic_note = ('采集停止相对定时截止的最大偏差为 ' +
                f"{mic['capture_stop_after_deadline_ms']['max']:.1f} ms。" if mic and mic['capture_stop_after_deadline_ms'] else '')
    stress = by_id.get('stress-zh8-t2')
    stress_note = (f"30 次同模型连续 8 秒解码：中位数 {dist(stress, 'decode_ms', 'median')} 秒，"
                   f"峰值 PSS {stress['peak_pss_mib']:.0f} MiB，释放并 GC 后 {stress['after_release_pss_mib']:.0f} MiB。"
                   if stress else '稳定性实验尚未完成。')
    idle = [x for x in good if x['idle_pss_mib'] is not None and x['after_release_pss_mib'] is not None]
    release_table = table(['实验', 'release + GC 约 2 秒（MiB）', '后续 PSS（MiB）', '后续采样相距 release（秒）'], [
        [x['id'], f"{x['after_release_pss_mib']:.0f}", f"{x['idle_pss_mib']:.0f}",
         f"{x['idle_sample_after_release_ms']/1000:.1f}"] for x in idle])
    noise_table = table(['输入', '重复次数', '空结果次数', '非空结果次数'], [
        [name, by_id[name]['decode_ms']['n'], by_id[name]['decoded_empty_count'],
         by_id[name]['decode_ms']['n'] - by_id[name]['decoded_empty_count']]
        for name in ['silence3', 'noise3'] if name in by_id])
    all_peak = max(x['peak_pss_mib'] for x in good)
    loads = [n for x in good if x['memory_mode'] == 'default' for n in x['load_ms']]
    warnings = by_id.get('en60-t2', {}).get('context_warnings', [])
    warning = next((x.split('W sherpa-onnx: ')[-1] for x in warnings if 'Truncating audio' in x), '')
    observer_ok = all(x['display_failures'] == 0 and x['composing_observed_in_host'] for x in good if x['trials'])
    rows = []
    for item in good:
        raw = [json.loads(l) for l in (HERE / f'results/{item["id"]}.jsonl').read_text().splitlines() if l]
        source = HERE / f'results/{item["id"]}.jsonl'
        files = [source, source.with_name(source.stem + '-device.json'), source.with_name(source.stem + '-logcat.txt')]
        rows.append({'id': item['id'], 'event_count': len(raw), 'files': [
            {'name': f.name, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest(), 'bytes': f.stat().st_size}
            for f in files if f.exists()]})
    (ROOT / 'docs/qwen3-asr-p0-evidence.json').write_text(json.dumps(rows, indent=2) + '\n')
    report = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qwen3-ASR P0 真机验证报告 · 2026-10-31</title><style>
:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{margin:0;background:#f2f5f7;color:#1b3040;font:16px/1.85 system-ui,sans-serif}}main{{max-width:1140px;margin:auto;padding:38px 25px 70px}}header{{border-top:6px solid #146b65;padding:26px 0}}h1{{font-size:32px;line-height:1.4}}h2{{font-size:23px;margin-top:0}}h3{{font-size:18px}}section{{background:white;border:1px solid #dae3e9;border-radius:14px;padding:25px;margin:20px 0}}.callout{{padding:18px;background:#fff0d4;border-left:4px solid #ac7815}}.good{{background:#e6f4ef;border-color:#146b65}}.meta,small{{color:#566b7a}}a{{color:#086d8c;overflow-wrap:anywhere}}code{{font-size:.87em;overflow-wrap:anywhere}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf2f5;padding:16px;border-radius:8px}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;vertical-align:top;padding:11px 12px;border-bottom:1px solid #dce5eb}}th{{background:#edf3f5}}li{{margin:7px 0}}@media(max-width:700px){{main{{padding:20px 12px}}section{{padding:20px 15px}}h1{{font-size:27px}}td,th{{min-width:115px}}}}
</style></head><body><main><header><small>P0 实测 · 2026-10-31 · 可复现制品与事件数据</small>
<h1>短句能实时显示，整段重复解码方案未通过 P0</h1>
<p>Qwen3-ASR 已在真实 Android 手机 CPU 上运行，并经测试 IME 更新宿主 composing。当前整段前缀反复解码路线在长句延迟、内存与上下文容量上有明确限制，不能据此进入生产功能开发。</p>
<p><a href="qwen3-asr-voice-input-spec.html">功能 spec</a> · <a href="../tools/voice-p0/README.html">复现步骤</a> · <a href="qwen3-asr-p0-metrics.json">指标 JSON</a> · <a href="qwen3-asr-p0-evidence.json">原始事件文件哈希</a> · <a href="../tools/voice-p0/artifacts.json">模型 / 运行时清单</a></p></header>
<section><h2>1. 决策结论</h2><div class="callout"><strong>P0 未通过，本轮尚未确认可发布的通用时长上限。</strong>3 秒快速中文样本达到热模型延迟目标；8 秒样本的最终等待已超过 2 秒目标。更长音频继续恶化，60 秒输入发生裁切并返回无效内容。默认配置内存超预算；低内存配置尚不能同时满足速度目标。</div>
<ul><li>模型选择保持 Qwen3-ASR；本轮失败针对固定 ONNX 导出、CPU 配置和整段重复解码路线，不代表所有 Qwen3-ASR 端内实现均不可行。</li>
<li>已验证的短句能力不等于已验证“所有 3 秒语音可发布”，也不能把 8 秒直接设为通用保护上限；语速、语言、停顿和生成 token 数都会改变耗时。</li>
<li>先评估有界音频分段 / 重叠窗口、上下文重导出与内存配置，再重新过 P0。暂不接入生产长按动作、录音权限设置和 Fcitx composing 所有权。</li></ul></section>
<section><h2>2. 设备、模型与实验条件</h2><ul>
<li>真机 NX888J，系统报告 SoC <code>SM8850</code>，Android 16 / API 36，arm64-v8a，4 KB 页；系统 MemTotal 11,330,448 KiB。USB 连接并充电，测试 APK 前台可见。</li>
<li>sherpa-onnx <code>v2.0.1</code> 原始 AAR，CPU；默认 3 线程起测，再比较 2 / 3 / 4 线程。后续主要用 2 线程，样本比较不构成显著性证明。</li>
<li>Qwen3-ASR-0.6B INT8，导出版本 2026-03-25；维护者模型仓库 revision <code>68818b2313fe77bd06f6a7c5068ff3ef59d02b8a</code>。模型与 tokenizer 共 987,015,347 字节（约 941 MiB）。主 ONNX 文件已在设备端 SHA-256 复核。</li>
<li><code>maxTotalLen=512</code>，<code>maxNewTokens=256</code>；相同模型复用，各 run 新启进程。进程首次加载约 {min(loads)/1000:.2f}–{max(loads)/1000:.2f} 秒；未清空 Android 页缓存，不能称为首次安装冷盘加载。</li>
<li>独立 Debug APK；native 推理为真实预编译库。测得的是测试进程总 PSS / RSS；生产 Fcitx 的额外常驻内存未包含。没有做 Release/R8 或 16 KB 设备运行测试；AAR 四个 arm64 .so 的 LOAD 段静态对齐为 0x4000。</li></ul></section>
<section><h2>3. 整段解码与线程对比</h2>{offline}<p>单次解码时间不包含录音等待；RTF 小于 1 仍可能无法满足每 1.5 秒更新和抬手后 2 秒定稿的要求。60 秒的短耗时来自裁切 / 无效输出，不能作为速度优势。</p>{thread_table}</section>
<section><h2>4. 可见测试 IME 的增量 composing</h2>{streamed}
<p>首条文字和最终等待的单位为秒；p95 使用 nearest-rank，n=10 时就是该组最大值。3 / 8 秒快速中文各 10 次，15 秒中文 3 次，30 / 60 秒英文各 1 次；小样本长音频属于诊断，不代表总体 p95。短句首条文字仍未达到 spec 要求的至少 30 次同条件验收规模。实验不启用生产方案的 5 秒 final 丢弃规则，以观察真实耗时。</p>
<p>另补测 5 秒快速中文 3 次：最终等待 2.09–3.41 秒，属于探查时长边界的小样本，也已超过 2 秒目标。麦克风两组均为 3 次；第一组信号不足，不能与有效听写质量混算。</p>
<p>首条文字从音频流起点计，可能包含错误或随后被修改的内容，不是逐词对齐后的稳定正确词延迟。绕口令和长英文在开头约 0.84 / 0.80 秒才出现显著信号；快速中文从起点已有语音。更新间隔只统计截止前不同的非空 partial，未剔除语音自然停顿；末尾等待和失败另列，防止漏掉“后来不再更新”的情况。</p>
<p>系统 InputConnection 返回值和宿主 TextWatcher 均有记录；本轮有效流式实验的 composing span / 写入检查：<strong>{'均观察到宿主 composing，未记录写入失败' if observer_ok else '存在未通过或缺失观测，见指标 JSON'}</strong>。测试 IME 只承担 P0 通路，不是最终键盘界面。</p></section>
<section><h2>5. 真实麦克风路径</h2><p>使用可见 InputMethodService 中的 AudioRecord（VOICE_RECOGNITION、16 kHz、单声道、PCM16），手机扬声器播放已知公开测试语音并由麦克风声学回采；未保存原始麦克风录音。第一轮 <code>mic-fast8-t2</code> 使用原媒体音量 2/15，RMS 约 0.0003，转写与刺激内容不符，该组不作为有效听写质量证据。第二轮 <code>mic-loud8-t2</code> 将测试音量临时升至 8/15，结束后恢复原值；确认输出路由为内置扬声器、输入为内置麦克风。{mic_note}</p>
<p>这验证了录音权限、采样、在推理进行中独立停止录音，以及系统 IC composing 路径。不是人现场口述；没有完成不同距离、蓝牙耳机、真实按住 / 抬手手势及尾字完整性验证。P0 的停止由定时截止模拟，最终等待包含在途 partial 和最后一次完整解码。</p></section>
<section><h2>6. 内存、释放与稳定性</h2><p>基线测试峰值 PSS 从约 2.1 GiB 随时长上升；全部有效实验中最高采样 PSS 为 {all_peak:.0f} MiB。相对 45–60 MiB 左右的测试进程基线，明显超过暂定 1.5 GiB 增量预算。PSS 为每秒及关键阶段采样值，可能漏掉尖峰；RSS 高水位来自内核 VmHWM。</p>
<p>{stress_note}</p><p>默认配置 release + GC 后约 2 秒仍可能有约 1 GiB 驻留，稍后的系统 meminfo 已明显回落。它不是确定的长期常驻，更不能仅凭两秒快照断言泄漏；尚未进一步归因到具体分配器或后台清理机制。</p>{release_table}<p>系统 thermal status 已记录；这不代表所有厂商温控频点都已受控。早期 8 秒绕口令的 2 线程中位数约 1.48 秒，后续连续压力测试约 2.09 秒；存在时段 / 状态差异，不能把顺序测试的微小线程差异当作确定收益。</p></section>
<section><h2>7. 内存配置对照</h2>{optimize_table}
<p>维护方 v2.0.1 的 <a href="https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/sherpa-onnx/csrc/session.cc">session.cc</a> 已支持 provider 配置：<code>EnableCpuMemArena=0</code>、<code>EnableMemPattern=0</code>，以及转发 <code>SessionConfig.*</code>。no-arena 同时关闭前两项；no-prepack 设置 <code>SessionConfig.session.disable_prepacking=1</code>；compact 同时关闭三项。对照仍使用同一 AAR、同一权重与 CPU 线程数。</p>
<p>本次 compact 的峰值约 1402 MiB，达到暂定内存预算，但 8 秒单次解码中位数约 8.93 秒，已慢于音频时长。no-arena 的文本哈希与默认一致；关闭预打包的两组文本哈希与默认不同，未完成人工 CER/WER，不能认定质量变好或变差。默认配置前后对照中位数为 2.88 / 2.88 秒，支持当前比较窗口内的速度差异。</p><p>配置优化的结果须同时检查质量、首字、刷新、final 和内存；不能只看峰值下降就宣告整条路线通过。</p></section>
<section><h2>8. 可支持时长：本轮能确认什么</h2><ul>
<li><strong>3 秒：</strong>选定快速中文在热模型下能持续 composing，延迟样本达标；该默认配置的整体内存门槛仍未通过。</li>
<li><strong>5 秒：</strong>补测的 3 次快速中文 final 等待均超过 2 秒目标；不支持把“3 秒通过”线性外推到稍长语句。</li>
<li><strong>8 秒：</strong>有持续文字，但快速中文最终等待超标；不能宣称“8 秒内都实时”。</li>
<li><strong>15 秒：</strong>可解码中文，但单次完整解码已约 3.3 秒，持续刷新和 final 无法稳定达到目标。</li>
<li><strong>30 秒：</strong>能够输出英文；本轮没有完整人工词级对齐，不能仅凭返回文本证明首尾完整。</li>
<li><strong>60 秒：</strong>确认不支持当前整段配置的完整转写。运行时日志直接报告裁切，三次 offline 最终仅得到 <code>language</code>。</li></ul>
<pre>{html.escape(warning)}</pre><p>该导出图的实际 model limit 为 512；音频 token 与生成文本共享序列空间。上调 Kotlin maxTotalLen 不能突破导出图上限。即使输入音频尚未裁切，也须为语言前缀和输出留空间；因此不能把裁切开始位置推算成安全产品时长。</p></section>
<section><h2>9. 静音 / 噪声与下一步</h2>{noise_table}<p>使用同一 3 秒零音频及固定 seed 的白噪声各重复 20 次。这是基础稳定性检查，不等价于 20 种真实噪声场景，也没有证明语音存在性过滤已完成；不能用“非空”指标替代正确文字或人工准确率。</p><ol>
<li>保留 Qwen3-ASR，优先对 2 / 4 / 6 / 8 秒候选音频窗口或自然语音分段做延迟、接缝准确率、重复 / 漏字对比；全会话仍维持一段 composing。窗口数值作为实验档位，不能直接固化为用户录音上限。</li>
<li>结合内存配置对照，决定是否需要自定义运行时 / 独立私有推理进程。独立进程可以隔离崩溃和回收，但不能降低推理本身峰值，不能当作内存预算已解决。</li>
<li>如需更长上下文，重新导出 decoder 并锁定量化和 tokenizer；重新测移动端内存与质量，不直接替换现有制品。</li>
<li>通过修订后的 P0 后再推进 P1。当前未做 100 句 CER/WER、真实口述、多语言完整验收、Release/R8、16 KB 运行、生产 Fcitx 并发 composing 协议与所有生命周期竞态测试。</li></ol></section>
<section><h2>10. 可复现证据</h2><p>已完成运行 {len(good)} 组，不代表全部通过质量 / 性能门槛。完整 JSONL、设备元数据和测试进程 logcat 在 <code>tools/voice-p0/results/</code>（Git 忽略）；轻量指标与文件哈希已保存到文档旁，未把完整转写正文和大模型提交到 Git。</p>
<p>初次 smoke 曾因 shell 推送到外部目录的访问权限失败，已改为 run-as 写应用私有目录；该失败未纳入任何性能统计。测试脚本在每轮结束后恢复原默认输入法并停止测试包。</p>
<p>外部来源：<a href="https://huggingface.co/csukuangfj2/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/tree/68818b2313fe77bd06f6a7c5068ff3ef59d02b8a">固定模型 revision</a>、<a href="https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1">固定 AAR 发行版</a>、<a href="https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/sherpa-onnx/csrc/offline-recognizer-qwen3-asr-impl.cc">上下文限制的 owning source</a>。本文数字来自真机事件文件，不来自上游宣传性能。</p></section>
</main></body></html>'''
    (ROOT / 'docs/qwen3-asr-p0-report.html').write_text(report)


if __name__ == '__main__':
    main()
