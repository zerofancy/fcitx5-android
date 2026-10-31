#!/usr/bin/env python3
"""Keep the second P0 report separate from the original full-prefix baseline."""
import hashlib
import html
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
DOCS = HERE.parents[1] / 'docs'


def main():
    subprocess.run(['python3', str(HERE / 'analyze_windows.py')], check=True, stdout=subprocess.DEVNULL)
    data = json.loads((HERE / 'results/window-summary.json').read_text())
    by_id = {x['id']: x for x in data}
    required = {'win-c2o1-60', 'win-c6o1-60', 'win-compact-c1o05-60', 'win-c2o1-en90',
        'win-c2o1-180', 'win-mic-c2o1-24', 'win-ref-zh21', 'win-c2o1-zh21',
        'win-c6o1-zh21', 'win-confirm-c2o1-12', 'win-noarena-c2o1-60'}
    if missing := required - by_id.keys():
        raise RuntimeError('Experiments not finished: ' + ', '.join(sorted(missing)))
    good = [x for x in data if x['success']]
    (DOCS / 'qwen3-asr-window-p0-metrics.json').write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    evidence = []
    experiments = []
    for item in data:
        files = [HERE / f'results/{item["id"]}{suffix}' for suffix in ['.jsonl', '-device.json', '-logcat.txt']]
        evidence.append({'id': item['id'], 'files': [{'name': p.name,
            'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
            for p in files if p.exists()]})
        metadata = HERE / f'results/{item["id"]}-device.json'
        if metadata.exists():
            args = json.loads(metadata.read_text())['arguments']
            experiments.append({k: v for k, v in args.items() if k != 'serial'})
    (DOCS / 'qwen3-asr-window-p0-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    (HERE / 'window-experiments.json').write_text(json.dumps(experiments, indent=2) + '\n')

    def number(x, key, stat='p95_nearest_rank'):
        d = x.get(key)
        return f'{d[stat]/1000:.2f}' if d else '—'

    def quality(x):
        values = x.get('quality', [])
        return f"{sum(v['rate'] for v in values)/len(values)*100:.2f}%" if values else '—'

    def table(headers, rows):
        return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{x}</th>' for x in headers) + \
            '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'

    matrix_ids = ['win-smoke-c2o1', 'win-c2o05', 'win-c4o1', 'win-c6o1', 'win-v2-c2o2',
                  'win-v2-c3o15', 'win-v2-c4o2', 'win-compact-c2o05', 'win-v2-compact-c1o05', 'win-basic-c2o1']
    matrix = table(['配置 / 调度', '新音频 + 左重叠', '更新间隔 p95 / final（秒）', '峰值 PSS（MiB）', '中文 CER'], [
        [html.escape(x['id']), f"{x['config']['core_ms']/1000:g} + {x['config']['overlap_ms']/1000:g} s",
         number(x, 'held_changed_update_gap_ms') + ' / ' + number(x, 'final_wait_ms'),
         f"{x['peak_pss_mib']:.0f}", quality(x)] for name in matrix_ids if (x := by_id.get(name)) and x['success']])
    long_ids = ['win-c2o1-60', 'win-c6o1-60', 'win-compact-c1o05-60', 'win-c2o1-en90',
                'win-c2o1-180', 'win-noarena-c2o1-60', 'win-mic-c2o1-24', 'win-c2o1-zh21', 'win-c6o1-zh21', 'win-confirm-c2o1-12']
    long_rows = []
    for name in long_ids:
        if name not in by_id:
            continue
        x = by_id[name]
        if not x['success']:
            elapsed = x.get('failure_since_start_ms')
            label = f"计划 {x['config']['seconds']} s；{elapsed/1000:.2f} s 过载" if elapsed else '运行失败'
            long_rows.append([name, label, '—', '—', f"{x['peak_pss_mib']:.0f}" if x.get('peak_pss_mib') else '—', '未定稿'])
        else:
            long_rows.append([name, f"{x['config']['seconds']} s × {x['config']['repeats']}",
                number(x, 'held_changed_update_gap_ms'), number(x, 'final_wait_ms'),
                f"{x['peak_pss_mib']:.0f}", quality(x)])
    long_table = table(['实验', '时长 × 次数', '更新间隔 p95（秒）', '结束等待（秒）', '峰值 PSS（MiB）', 'CER / WER'], long_rows)
    steady = by_id.get('win-c2o1-180', {})
    bins = steady.get('pss_30s_bins_mib', {})
    memory_table = table(['录音阶段', '采样次数', 'PSS 中位数 / 最大值（MiB）'], [
        [f'{int(k)*30}–{int(k)*30+30} s', v['n'], f"{v['median']:.0f} / {v['max']:.0f}"] for k, v in bins.items()])
    full_bins = [v for v in bins.values() if v['n'] >= 10]
    rise = full_bins[-1]['median'] - full_bins[0]['median'] if len(full_bins) >= 2 else None
    rise_note = f'首尾完整 30 秒桶的 PSS 中位数相差约 +{rise:.0f} MiB，仍存在缓慢增长，尚未证明长期平台期。' if rise is not None else ''
    noarena = by_id.get('win-noarena-c2o1-60', {})
    arena_note = (f"额外关闭 CPU arena / memory pattern 的 60 秒对照：峰值 PSS {noarena['peak_pss_mib']:.0f} MiB，"
        f"相对加载前增量 {noarena['peak_pss_mib']-noarena['baseline_pss_mib']:.0f} MiB，"
        f"结束等待 {number(noarena, 'final_wait_ms')} 秒。占用有所降低，但仍高于预算；只测了 60 秒，不能据此认定长期增长已经解决。"
        if noarena.get('success') else '')
    coverage_bad = [x['id'] for x in good if x['config'].get('mode', '').startswith('window') and
                    (not x['audio_coverage'] or not all(c['contiguous'] for c in x['audio_coverage']))]
    truncated = [x['id'] for x in good if x['config'].get('mode', '').startswith('window') and x.get('context_warnings')]
    failed = [x for x in data if not x['success']]
    failures = ''.join(f'<li><code>{html.escape(x["id"])}</code>: ' +
        html.escape('; '.join(e.get('message', '') for e in x.get('errors', []))) + '</li>' for x in failed)
    ref = by_id.get('win-ref-fast12', {})
    confirmed = by_id.get('win-confirm-c2o1-12', {})
    first = number(confirmed, 'first_nonempty_from_audio_start_ms') if confirmed else '待完成'
    mic = by_id.get('win-mic-c2o1-24', {})
    mic_max = f"{max(x['after_release_ms'] for x in mic['capture_stop']):.1f}" if mic.get('capture_stop') else '待完成'
    pairs = table(['独立音频', '整段对照 CER', '2+1 窗口 CER', '6+1 窗口 CER'], [
        [label, quality(by_id.get(a, {})), quality(by_id.get(b, {})), quality(by_id.get(c, {}))]
        for label, a, b, c in [('快速中文 12 s', 'win-ref-fast12', 'win-smoke-c2o1', 'win-c6o1'),
                              ('绕口令 21 s', 'win-ref-zh21', 'win-c2o1-zh21', 'win-c6o1-zh21')]])
    report = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qwen3-ASR 有界窗口 P0 真机报告 · 2026-10-31</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1f5f7;color:#203443;font:16px/1.85 system-ui,sans-serif}}main{{max-width:1160px;margin:auto;padding:38px 26px 70px}}header{{border-top:6px solid #126e65;padding:25px 0}}h1{{font-size:32px;line-height:1.4}}h2{{font-size:23px;margin-top:0}}section{{background:white;border:1px solid #d9e3e9;padding:26px;border-radius:14px;margin:20px 0}}a{{color:#086e8c;overflow-wrap:anywhere}}code{{font-size:.88em;overflow-wrap:anywhere}}small,.meta{{color:#536c7b}}.note{{padding:16px 20px;background:#fff1d7;border-left:4px solid #b17c12}}.ok{{background:#e5f4ed;border-color:#126e65}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;vertical-align:top;padding:11px 13px;border-bottom:1px solid #dde6eb}}th{{background:#edf4f6}}li{{margin:8px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf3f5;padding:16px;border-radius:8px}}@media(max-width:700px){{main{{padding:22px 12px}}section{{padding:20px 15px}}h1{{font-size:27px}}th,td{{min-width:120px}}}}
</style></head><body><main><header><small>P0 第二轮 · 有界窗口 / 重叠拼接 · 模型保持 Qwen3-ASR</small>
<h1>窗口改善持续转写延迟，内存与拼接质量仍需解决</h1>
<p>不新增总录音时长上限。以固定容量音频环形缓冲和短窗解码取代整段前缀重复解码，测试长录音时的延迟、内存、完整音频覆盖及文字重复 / 漏字。</p>
<p><a href="qwen3-asr-p0-report.html">上一轮整段基线</a> · <a href="qwen3-asr-voice-input-spec.html">更新后的 spec</a> · <a href="qwen3-asr-window-p0-metrics.json">本轮指标 JSON</a> · <a href="qwen3-asr-window-p0-evidence.json">原始证据哈希</a> · <a href="../tools/voice-p0/README.html">复现说明</a></p></header>
<section><h2>1. 结论</h2><div class="note"><strong>尚未找到同时满足延迟、1.5 GiB 增量内存预算及拼接质量的配置。</strong>默认 CPU 配置可以显著缩短长录音的刷新和结束等待，测试进程峰值 PSS 仍约 2.1–2.3 GiB，扣除加载前基线后仍超预算；低内存配置约 1.3–1.4 GiB，但速度、积压和短段识别质量仍有问题。</div>
<ul><li>总时长与单次解码长度已经分离；长录音不再整段送入 512-token 导出模型，因此不应把原模型上下文上限换算成产品录音上限。</li>
<li>3 分钟是实验观测时长，不是产品限制，也不是“任意时长已通过”的承诺。持续输出文字仍会自然增长；有界的是音频缓冲与单次模型输入。</li>
<li>本轮不接入生产空格长按。先解决模型常驻内存与稳定拼接，再按原交互规范推进。</li></ul></section>
<section><h2>2. 实验条件与实现</h2><p>同一 NX888J / SM8850 / Android 16 / arm64 / 4 KB 真机；同一 sherpa-onnx v2.0.1 AAR、同一固定 Qwen3-ASR-0.6B INT8 权重和 tokenizer，未更换模型。CPU 默认 2 线程，低内存组合额外试 4 线程。</p>
<ol><li>音频生产线程独立采样或按真实时间重放，样本位置使用 Long；解码保持一个 worker。每段处理 C 秒新音频，附带 O 秒左侧音频重叠，单次输入不超过 C+O 秒。</li>
<li>环形缓冲容量固定为 3C+O+1 秒。2+1 配置容量 8 秒 / 128,000 个 Float32 样本，约 0.49 MiB；单次 3 秒快照约 0.18 MiB。实验音频 fixture 是固定源，不随总录音长度复制。</li>
<li>逐段按顺序处理，既不跳过旧段，也不提前 commit。已识别段和当前假设拼成同一份全文，通过系统 InputConnection 替换同一个宿主 composing。</li>
<li>文字拼接使用归一化 token 的最长精确后缀 / 前缀匹配，或有限编辑距离匹配；重叠文字可回改。无法匹配时保留内容并记录 unmatched；多个匹配记录 ambiguous，不能假装没有风险。</li>
<li>plain 调度保留原增量更新节奏；deadline 调度估算下一次 partial 成本，若可能跨过分段边界则等待段结束，减少冗余解码。这个策略也可能造成更长刷新间隔，已单独列出。</li>
<li>如果 worker 落后到环形缓冲覆盖了未处理音频，明确报 overrun 并失败，不静默丢音。没有按总录音时长自动停止的产品规则；实验 seconds 只模拟本次有限时间后的抬手。</li></ol></section>
<section><h2>3. 短样本参数矩阵</h2>{matrix}<p>各矩阵项为一条完整 12 秒快速中文样本，未足够支持总体 p95；更新间隔基于该次按住期间发生变化的非空 partial。段间自然停顿未剔除；final 列为该次观测等待。basic 仅保留基础图优化并关闭 arena；compact 同时关闭预打包、arena 与 memory pattern。</p>
<p>同一 12 秒音频整段解码的 CER 为 <strong>{quality(ref)}</strong>。较短窗口的速度收益不能直接当作质量通过；例如最初 2+1 的 CER 为 18.46%，存在重叠重复和改写错误；6+1 的短样本 CER 较接近整段，但刷新已接近门槛。</p></section>
<section><h2>4. 长时间与重复测量</h2>{long_table}<p>表内 CER 用于中文、WER 用于英文。单次长录音的更新 p95 来自该次多次文字变化；首次文字与 final 只有一条样本时只是观测值。10 次确认组是独立会话、同一已热模型；首次文字从音频起点计的 p95 为 {first} 秒。</p><p>10 次确认组的 final 等待 p95 约 2.35 秒，仍高于 2 秒目标；不能只引用早期单次 0.81 秒的较快结果。时延记录以系统 IC 写入与宿主回调为依据，未测屏幕扫描 / 光学呈现，也未做稳定正确词的逐词延迟标注。</p>
<p>60 / 180 秒中文源为“完整 11.38 秒快速中文 + 静音补到 12 秒”的周期性重放，预期参考正文同步重复，不是自然 3 分钟长演讲。英文源为原始 88.193 秒含噪音频，补静音到 90 秒，无循环；停顿未做独立声学标注。21 秒绕口令是第二条独立中文源。快速语音与绕口令是压力样本，这些错误率不代表普通口述的平均准确率。</p></section>
<section><h2>5. 180 秒内存走势与音频覆盖</h2>{memory_table}
<p>分桶只包含录音开始到最终输出结束的内存采样，排除了模型释放阶段；全流程峰值还包含加载期。默认配置的主要占用来自模型 / 运行时，不是录音缓冲，因此限制单次解码窗口不会自动把模型峰值降至 1.5 GiB。</p>
<p>{rise_note}有界音频缓存不等于全部进程内存恒定；原始数据同时记录 native 已分配字节数，尚未进一步归因到 arena、其他分配器或日志 / 编辑器开销，不能仅凭增长就断言泄漏。</p><p>{arena_note}</p>
<p>成功执行的窗口实验中，音频顺序覆盖异常：<strong>{html.escape(str(coverage_bad)) if coverage_bad else '无'}</strong>；导出上下文 / 输出截断警告：<strong>{html.escape(str(truncated)) if truncated else '无'}</strong>。coverage 验证的是已接受采样被连续处理，并不等于识别正文没有漏字。</p></section>
<section><h2>6. 重叠拼接的准确率限制</h2>{pairs}<p>第二条独立中文的 2+1 窗口出现大量重复，不能把第一条样本较好的延迟推广成可用结论。参考转写来自固定模型包附带的 transcript.txt；标点去除，中文按字符、英文按单词计算编辑距离，列出替换、删除和插入数。参考文本尚未独立人工审听核对，结果用于诊断回归，不应当作公开标准测试集或最终绝对准确率。精确计数、正文哈希与 seam 类型可在指标 JSON 复核。</p>
<p>模型在不同音频边界可能改写同一个词；重复词组也可能让后缀 / 前缀存在多个合理对齐。纯文字重叠启发式缺少可靠时间戳，存在重复、误删和错误冻结前段文字的风险。更大重叠不保证更准确，也会增加计算。不能只用刷新频率判断方案可用。</p></section>
<section><h2>7. 可见 IME 的真实麦克风验证</h2><p>WindowMicrophone 使用真实 AudioRecord 将 PCM 写入同一固定 ring；手机扬声器播放已知语音、内置麦克风回采，媒体音量临时调至 8/15 后恢复。该项最大停止采集偏差为 {mic_max} ms。不是人工现场口述，也不保存原始麦克风录音。</p><p>采音与解码分线程；关闭采集后，只处理 ring 内剩余段。初始设备采音延迟和末尾硬件缓冲未做逐词对齐，因此不能把 accepted sample 覆盖检查当成物理尾字已经验收。</p></section>
<section><h2>8. 失败实验与剩余工作</h2><ul>{failures if failures else '<li>当前已完成实验未出现进程 / ring 错误，但性能与文字质量仍按前述门槛单独判定。</li>'}</ul>
<p>后续优先级：识别运行时的预打包 / 权重内存布局与更可靠的流式 / 分段文字对齐。窗口和总录音时长保持独立，不通过设置人为总时长上限掩盖问题。继续使用 Qwen3-ASR；尚未做 GPU/NPU、重新量化 / 导出、更换运行时或生产 Fcitx 集成。</p></section>
<section><h2>9. 复现与证据</h2><p>本轮完成运行 {len(good)} 组，失败 {len(failed)} 组。原始 JSONL、仅测试进程的 logcat、设备状态与安装 APK SHA-256 位于 <code>tools/voice-p0/results/</code>；模型清单与输入哈希位于 <code>tools/voice-p0/artifacts.json</code> 和 <code>window-inputs.json</code>。完整参数已保存到 <code>window-experiments.json</code>，可用 run_window_suite.py 加新后缀复测。前一轮报告和事件保留。长文本 logcat 可能被系统截断，完整正文与评分以未截断 JSONL 为准。</p><pre>python3 tools/voice-p0/prepare_windows.py
python3 tools/voice-p0/deploy.py --serial DEVICE_SERIAL
python3 tools/voice-p0/run.py win-EXAMPLE_UNIQUE_ID --serial DEVICE_SERIAL --mode ime-window \\
  --seconds 180 --core-ms 2000 --overlap-ms 1000 --threads 2 \\
  --wave fixtures/window-fast12.wav --timeout 360
python3 tools/voice-p0/analyze_windows.py</pre>
<p>新增 ring 环绕 / overrun 和拼接行为自检在设备上执行；评分器另检查插入、删除、替换计数。Debug APK 构建通过，未做生产 Release/R8 或 16 KB 设备验收。脚本结束后恢复原输入法与测试音量并停止测试进程。</p></section>
</main></body></html>'''
    (DOCS / 'qwen3-asr-window-p0-report.html').write_text(report)


if __name__ == '__main__':
    main()
