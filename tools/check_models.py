"""Verify freshly downloaded ONNXs and synthetic inference; not an accuracy test."""
import argparse
import json
from pathlib import Path
import numpy as np
import onnxruntime as ort
from prepare import load
from install_assets import checked


def check(folder):
    results=[]
    for row in load('models/manifest.json')['files']:
        path=folder/row['file'];checked(path,row)
        options=ort.SessionOptions();options.intra_op_num_threads=2
        session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        n=row['batch'];detector=row['kind']=='detector'
        shape=[n,3,416,416] if detector else [n,3,20,70]
        output_shape=[n,3549,8] if detector else [n,6]
        if session.get_inputs()[0].shape!=shape or session.get_outputs()[0].shape!=output_shape:raise ValueError('Model shape contract mismatch')
        for value in (0.,1.):
            output=session.run(None,{session.get_inputs()[0].name:np.full(shape,value,np.float32)})[0]
            if list(output.shape)!=output_shape or not np.isfinite(output).all():raise ValueError('Invalid model output')
            if detector and np.max(np.abs(output[:,:,5]))>1e-7:raise ValueError('Detector adapter slot mismatch')
            if not detector:np.testing.assert_allclose(output.sum(1),np.ones(n),atol=1e-5)
        results.append(dict(file=row['file'],sha256=row['sha256'],passed=True,input_shape=shape,output_shape=output_shape,synthetic_cases=2))
    return {'passed':True,'scope':'fresh model hash and CPU synthetic inference only',
            'accuracy_test':False,'tensorrt_test':False,'onnxruntime_version':ort.__version__,'numpy_version':np.__version__,'models':results}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--models',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=check(a.models)
    with a.output.open('x') as out:json.dump(result,out,indent=2);out.write('\n')
    print(json.dumps(result,indent=2))
