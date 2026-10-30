"""Build fresh candidate-C FP32 engines and check numerical parity, not accuracy."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import onnxruntime as ort
import tensorrt_bindings as trt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'aihub188_mobilenetv2/candidate_c'))
from adapter_core import ROI, decode
from trt_backend import TRTBackend


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signature(row):
    result = decode(row, ROI(1, 0, 0, 0, 70, 20))
    return (result['label'], result['reason'],
            [(x['color'], x['shape'], x['status']) for x in result['elements']])


def build(source, target):
    log = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(log)
    network = builder.create_network(0)
    parser = trt.OnnxParser(network, log)
    if not parser.parse(source.read_bytes()):
        raise RuntimeError([str(parser.get_error(i)) for i in range(parser.num_errors)])
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 512*1024**2)
    config.clear_flag(trt.BuilderFlag.TF32)
    config.builder_optimization_level = 2
    start = time.monotonic()
    plan = builder.build_serialized_network(network, config)
    if plan is None:
        raise RuntimeError('TensorRT engine build failed')
    with target.open('xb') as stream:
        stream.write(bytes(plan))
    return time.monotonic()-start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = json.loads((ROOT/'models/manifest.json').read_text())['files']
    rows = sorted((r for r in records if r['kind']=='classifier'), key=lambda r:r['batch'])
    assert [r['batch'] for r in rows] == [1, 6]
    for row in rows:
        source = args.models/row['file']
        assert source.stat().st_size == row['bytes'] and sha(source)==row['sha256']
    args.output.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(20261030)
    data = np.concatenate([np.zeros((1,3,20,70),np.float32),
                           np.ones((1,3,20,70),np.float32),
                           rng.random((16,3,20,70),dtype=np.float32)])
    report = dict(schema=1, scope='synthetic FP32 GPU/CPU parity only',
                  accuracy_test=False, integration_complete=False, results=[])
    for row in rows:
        batch = row['batch']; source = args.models/row['file']
        target = args.output/f'mobilenetv2_batch_{batch}_fp32.engine'
        print(f'Building candidate C batch {batch}', flush=True)
        elapsed = build(source, target)
        options = ort.SessionOptions(); options.intra_op_num_threads = 2
        reference = ort.InferenceSession(str(source), sess_options=options, providers=['CPUExecutionProvider'])
        assert reference.get_inputs()[0].shape == [batch,3,20,70]
        chunks = [data[i:i+batch] for i in range(0,len(data),batch)]
        expected = np.concatenate([reference.run(None,{reference.get_inputs()[0].name:x})[0] for x in chunks])
        with TRTBackend(target) as backend:
            actual = np.concatenate([backend.infer(x) for x in chunks])
            stable = True; durations = []
            for _ in range(20): backend.infer(chunks[0])
            for i in range(500):
                j=i%len(chunks); start=time.perf_counter()
                y=backend.infer(chunks[j]); durations.append((time.perf_counter()-start)*1000)
                stable = stable and np.array_equal(y,actual[j*batch:(j+1)*batch])
        maximum = float(np.max(np.abs(actual-expected)))
        normalized = bool(np.isfinite(actual).all() and (actual>=0).all() and
                          (actual<=1.0001).all() and np.allclose(actual.sum(1),1,atol=1e-4))
        top1 = bool(np.array_equal(actual.argmax(1),expected.argmax(1)))
        gates = all(signature(a)==signature(b) for a,b in zip(actual,expected))
        passed = normalized and top1 and gates and stable and maximum<=0.0002
        result = dict(engine=target.name, engine_sha256=sha(target), onnx_sha256=sha(source),
                      batch=batch, trt_version=trt.__version__, precision_request='fp32',
                      tf32=False, workspace_mib=512, build_seconds=elapsed,
                      cases=len(data), case_type='zeros, ones, seeded uniform noise',
                      max_absolute_error=maximum, atol=0.0002, finite_normalized=normalized,
                      top1_agreement=top1, signal_gate_agreement=gates,
                      repeat_500_bitwise_stable=bool(stable),
                      latency_p95_ms=float(np.percentile(durations,95)), passed=bool(passed))
        report['results'].append(result)
        (args.output/'trt_validation.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(result), flush=True)
        if not passed: raise RuntimeError('Numerical acceptance failed; engine must not be activated')
        # Exercise the exact activation gate, not merely the unchecked test backend.
        with TRTBackend(target, require_validated=True) as backend:
            backend.infer(chunks[0])


if __name__ == '__main__':
    main()
