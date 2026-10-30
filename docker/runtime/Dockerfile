# This derived image adds Python inference dependencies, not maps/models/engines.
# Pass a local tag after verifying its image ID; a bare sha256 ID is not a FROM reference.
ARG BASE_IMAGE=katech-autoware-sils:adsw-perception-carla-cuda
FROM ${BASE_IMAGE}
USER root
COPY requirements.txt /opt/katech-sils/requirements-runtime.txt
RUN test "$(dpkg-query -W -f='${Version}' libnvinfer10)" = '10.8.0.43-1+cuda12.8' && \
    python3 -m pip install --no-cache-dir --no-deps --only-binary=:all: \
      --target /opt/katech-sils/python -r /opt/katech-sils/requirements-runtime.txt
ENV PYTHONPATH=/opt/katech-sils/python
RUN python3 -c "import numpy, PIL, onnxruntime, tensorrt_bindings, cv2; assert numpy.__version__ == '1.26.4'; assert tensorrt_bindings.__version__ == '10.8.0.43'"
