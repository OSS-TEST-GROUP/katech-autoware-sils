# KATECH Autoware SILS 통합 설치·검증 매뉴얼

작성 기준: 2026-11-01. **검증 완료 범위: 같은 PC의 별도 새 설치에서 headless 저속 SILS 기본 통합, 일반 호스트 NVIDIA Docker의 GUI 기본 실행·약 8m 제한 주행**입니다. 다운로드·새 빌드·NDT·경로·인지·선택 구간 주행·신호 판단·정지·종료·재시작을 확인했습니다. 전체 도로, 고속, 다른 PC, 모든 GUI 마우스 조작, HIL·실차의 검증 완료를 뜻하지 않습니다. 실행 환경별 상세 증거는 저장소의 `validation.json`에 기록합니다.

## 1. 배포 구성과 권한

- 공개 소스: `OSS-TEST-GROUP/katech-autoware-sils`. 고정 소스 버전과 SILS 전용 변경을 빌드합니다.
- CARLA: 공식 0.9.15 패키지를 다운로드하고 고정 SHA256으로 확인합니다.
- 학습 모델: 공개 Release `models-korean-tl-20261030`의 ONNX 4개를 다운로드합니다.
- C-Track: 권한이 있는 사용자만 비공개 `OSS-TEST-GROUP/katech-C-Track-Carla-map`의 지도·PCD·3D 자산·실행 프로필을 다운로드합니다.

비공개 지도에서 생성된 헤더와 판단 컨테이너에도 지도 정보가 포함됩니다. 공개 Git/컨테이너 레지스트리에 게시하지 마세요. 다른 Town에는 해당 지도용 Lanelet2·PCD·좌표 설정이 필요하며 C-Track 프로필을 재사용하면 안 됩니다.

## 2. 호스트 준비

현재 확인 환경은 Ubuntu 22.04, amd64, NVIDIA RTX 4080입니다. Python 3, Git, PyYAML, vcstool, zstd, Docker Buildx, NVIDIA 컨테이너 실행 환경과 보안 업데이트된 Python tarfile이 필요합니다. 모델 검사 의존성은 `requirements-inference.txt`를 참고하세요. 지도 연결 생성에는 Native Lanelet2 Python 바인딩이 필요합니다.

새 설치 디렉터리를 사용하세요. 자산 설치 도구는 60 GiB 이상의 여유 공간을 요구하며 **소스·컨테이너 빌드 공간은 별도**입니다. 소스 경로를 SSD로 바꾸어도 Docker 저장 위치는 바뀌지 않습니다. Docker 저장 볼륨과 임시 파일 볼륨도 확인하세요. RAID에 오류가 있으면 작업을 중단하고 복구 후 재개합니다.

현재 PC에서는 RAID 전용 빌드 데몬을 사용했습니다. 44 GiB 메모리 및 8개 CPU affinity 제한으로 빌드했고, 패키지 병렬 수는 2였습니다. 이는 모든 장치에 필요한 최소 사양이 아니라 이 PC에서 사용한 설정입니다.

## 3. 다운로드와 설치

공개 저장소를 새 경로에 복제하고 해당 저장소에서 실행합니다. 아래 경로는 사용자가 충분한 공간이 있는 볼륨으로 바꾸어야 합니다. 토큰을 명령 인자나 문서에 기록하지 마세요. 비공개 자산은 기존 GitHub 자격 증명 또는 토큰 환경 변수를 이용합니다.

```bash
git clone https://github.com/OSS-TEST-GROUP/katech-autoware-sils.git
cd katech-autoware-sils
export SILS_DOWNLOADS=/your/ssd/sils-downloads
export SILS_INSTALL=/your/ssd/sils-install
export SILS_SOURCE=/your/ssd/sils-source
python3 tools/prepare.py plan
python3 tools/prepare.py fetch-carla --destination "$SILS_DOWNLOADS/carla"
python3 tools/prepare.py fetch-models --destination "$SILS_DOWNLOADS/models"
python3 tools/fetch_centerpoint.py --destination "$SILS_DOWNLOADS/centerpoint"
python3 tools/private_assets.py --map ctrack --cache "$SILS_DOWNLOADS/private"
python3 tools/install_assets.py --map ctrack --downloads "$SILS_DOWNLOADS" --destination "$SILS_INSTALL"
python3 tools/check_models.py --models "$SILS_DOWNLOADS/models" --output "$SILS_INSTALL/models-check.json"
```

파일 크기·SHA256이 다르면 중단합니다. 기존 설치를 덮어쓰지 않습니다. NDT에는 보충 프로필의 PCD를 설치한 `autoware_map/pointcloud_map.pcd`를 사용합니다. 기본 자산에 있는 이전 PCD를 섞지 마세요. `models-check.json`은 CPU 기본 추론 검사이며 실제 신호등 정확도나 GPU 추론 검증이 아닙니다.

CenterPoint는 고정된 상위 저장소의 공식 URL·SHA256으로 일반형과 기본값인 tiny형의 ONNX 및 설정 8개를 받습니다. 실행 시 `lidar_centerpoint` 데이터 디렉터리에 연결해야 하며, 클래스 매핑 YAML까지 빠짐없이 필요합니다. 모델별 TensorRT 엔진은 대상 GPU에서 생성합니다.

## 4. SILS 소스와 이미지 빌드

```bash
python3 tools/prepare.py sources --destination "$SILS_SOURCE"
python3 tools/generate_movements.py --installation "$SILS_INSTALL"
python3 tools/overlay_sources.py apply --destination "$SILS_SOURCE" --installation "$SILS_INSTALL"
python3 tools/overlay_sources.py verify --destination "$SILS_SOURCE"
python3 tools/prepare.py build-sils --destination "$SILS_SOURCE"
```

빌드 전 `DOCKER_HOST`/Docker context가 의도한 저장 볼륨의 데몬인지 확인하세요. 기존 제품용 소스나 실행 컨테이너에 덮어쓰지 않습니다. 일반 Lanelet2의 `speed_bump` 경고는 연결 생성 도구가 지정된 조건에서만 허용하며 원본 지도 규칙을 삭제하지 않습니다.

완료 확인 대상은 `katech-autoware-sils:adsw-perception-carla-cuda`, `:adsw-decision-carla`, `:adsw-control-carla` 세 이미지입니다. 기본 이미지 빌드만 성공한 것은 SILS 빌드 완료가 아닙니다. 빌드 결과를 자동 업로드하지 않습니다.

2026-10-30 새 설치 빌드는 종료 코드 0이며 세 이미지 ID는 각각 `c2448546755b`, `93fe736ac762`, `5f3699d2a5320`입니다. 환경에 따라 이미지 ID는 달라질 수 있으므로 다른 PC의 합격 조건으로 사용하지 않습니다.

### Python 추론 의존성과 GPU 엔진

네이티브 인지 이미지에는 ONNX Runtime·Pillow·TensorRT Python 바인딩이 포함되지 않았으므로 별도 실행 이미지를 만듭니다. Dockerfile은 TensorRT 네이티브 버전과 Python 바인딩 버전을 일치시킵니다. `BASE_IMAGE`에는 이미지 ID를 확인한 로컬 태그 또는 레지스트리 digest 참조를 사용합니다. bare `sha256:...`를 FROM 인자로 사용하지 마세요.

```bash
docker build --build-arg BASE_IMAGE=katech-autoware-sils:adsw-perception-carla-cuda \
  -t katech-autoware-sils:perception-runtime docker/runtime
```

`tools/build_classifier_engines.py --models <모델폴더> --output <새출력폴더>`는 위 실행 이미지의 GPU 환경에서 수행할 도구입니다. 저장소와 모델을 읽기 전용으로 연결하고 출력만 쓰도록 구성해야 합니다. 기존 출력 폴더는 덮어쓰지 않습니다. 현재 GPU에서 생성한 FP32 batch 1·6은 합성 입력 18개에서 CPU 대비 최대 절대 오차 `1.1920928955078125e-07`, 각 500회 반복 안정성, 신호 상태 변환 일치 검사를 통과했습니다. 이는 사진 정확도 시험이 아닙니다.

## 5. 통합 실행 명령

`tools/session.py`가 새 세션 준비·기동·감시·정지·재시작을 담당합니다. `init`은 지도·모델·엔진·이미지 ID를 확인하고 새 전용 볼륨을 만들지만 **기동하거나 출발하지 않습니다**. `run`은 항상 STOP으로 시작합니다. 현재 실행 프로필은 `--map ctrack`만 지원하며 다른 Town은 대응 Lanelet2·PCD·차량·신호 프로필을 등록하기 전까지 거부합니다. 자산 목록에 Town이 있다는 것과 Autoware 연동 완료는 다릅니다.

현재 프로필의 호스트 사용자 ID는 1000이어야 합니다. 호스트 Python에는 `carla==0.9.15`와 PyYAML이 필요합니다. 공식 배포본에 포함된 Python 2.7/3.7 wheel을 Ubuntu 22.04의 Python 3.10에 설치하지 마세요. 이 검증에서는 Python 3.10용 CARLA 0.9.15 모듈을 사용했습니다.

### 5.1 GPU 엔진 생성

아래 예시는 **호스트 NVIDIA Docker 실행 환경**용입니다. 동일 GPU에서 새 엔진을 생성하며, 기존 출력 디렉터리가 있으면 중단합니다. `docker` 명령은 앞에서 이미지를 빌드한 데몬을 대상으로 해야 합니다. 별도 중첩 데몬을 쓴 경우 호스트 bind 경로와 GPU 전달 방식이 다르므로 아래 명령을 그대로 사용하지 마세요.

```bash
export SILS_ENGINE_PARENT=/your/ssd/sils-engine-output
mkdir -p "$SILS_ENGINE_PARENT"
docker run --rm --gpus all --network none --user 1000:1000 \
  --cap-drop ALL --security-opt no-new-privileges \
  --mount "type=bind,src=$PWD,dst=/repo,readonly" \
  --mount "type=bind,src=$SILS_DOWNLOADS/models,dst=/models,readonly" \
  --mount "type=bind,src=$SILS_ENGINE_PARENT,dst=/output" \
  --entrypoint /usr/bin/python3 katech-autoware-sils:perception-runtime \
  /repo/tools/build_classifier_engines.py --models /models --output /output/classifier
```

`classifier/trt_validation.json`의 두 결과가 모두 passed여야 합니다. 다른 GPU·드라이버로 바뀌면 새 엔진을 생성하고 새 세션을 준비합니다. 엔진·캐시는 공개 Git에 포함하지 않습니다. CenterPoint 엔진은 새 데이터 볼륨의 ONNX에서 최초 기동 시 생성됩니다.

### 5.2 새 세션 준비

큰 자산·Docker 저장소는 여유가 있는 SSD에, 세션 로그는 **그와 다른 ext4 파일시스템**에 둡니다. 현재 실행기는 자산 볼륨 150 GiB, 로그 볼륨 20 GiB 여유와 ext4/RAID 오류 상태를 검사합니다. 이 기준을 맞추기 위해 검사 코드를 끄거나 마운트를 강제 변경하지 마세요. 로그 상한은 세션당 1.5 GiB입니다.

```bash
export SILS_SESSION=/your/independent-volume/sils-session-01
python3 tools/session.py init \
  --installation "$SILS_INSTALL" --map ctrack \
  --models "$SILS_DOWNLOADS/models" \
  --centerpoint "$SILS_DOWNLOADS/centerpoint" \
  --engines "$SILS_ENGINE_PARENT/classifier" \
  --bundle "$SILS_SESSION" --name sils-session-01 --port 2490 --domain 223
```

`SILS_SESSION`은 존재하지 않는 새 디렉터리여야 하고 그 부모는 미리 만들어야 합니다. 공개 저장소 내부에는 만들지 마세요. 기본 Docker socket은 `/var/run/docker.sock`입니다. 이미지 태그를 다르게 빌드했다면 `--perception`, `--decision`, `--control`로 전달합니다. 세션은 실제 이미지 ID와 파일 해시를 고정합니다.

10월 30일의 선택 구간·신호 시험은 RAID 전용 중첩 Docker 데몬을 사용했습니다. 그 방식에는 `init`에 `--docker-host unix:///선택한/socket.sock --parent 기존부모컨테이너 --gpu-driver-dir /부모내/검증한GPU라이브러리경로`를 추가합니다. 데몬·부모 ID와 CPU/메모리 한도·현재 GPU/드라이버 일치를 검사합니다. 해당 디렉터리는 호스트 경로가 아니라 부모 컨테이너의 경로입니다. 이 실행기는 privileged 데몬을 새로 만들거나 관리자 설정을 변경하지 않습니다.

11월 1일에는 같은 검증 이미지를 별도 일반 호스트 Docker에 등록하고 `--gpus all` 방식으로 GUI·8m 주행을 추가 시험했습니다. 기본 socket이 아니라면 `--docker-host`와 `--parent-host`를 모두 같은 로컬 socket으로 지정하고, `--parent`와 `--gpu-driver-dir`는 사용하지 않습니다. 기존 시스템 Docker의 저장소·서비스는 변경하지 않았습니다. 별도 데몬 운영에는 독립된 저장소·실행 경로·socket과 관리자 설정이 필요하며, 실행기가 자동 구성하지 않습니다.

### 5.3 정지 상태 확인, 제한 주행, 종료

```bash
# 기동 → NDT 초기화 → 프로필의 시험 goal 설정 → 정지 상태 검사 → 종료
python3 tools/session.py run --session "$SILS_SESSION/session.json" --check-route --check-only

# 명시적으로 요청할 때만: 5 km/h 상한, 약 8m 제한 자율주행 → STOP → 종료
python3 tools/session.py run --session "$SILS_SESSION/session.json" --trial --seconds 400

# 최대 한 시간 정지 상태 유지. 자동 출발하지 않음
python3 tools/session.py run --session "$SILS_SESSION/session.json" --check-route --seconds 3600
```

다른 터미널에서 다음 명령으로 종료를 요청합니다.

```bash
python3 tools/session.py shutdown --session "$SILS_SESSION/session.json"
```

실행기는 native STOP 응답을 확인하고 자신이 생성한 세 파티션과 CARLA만 종료합니다. Ctrl+C도 같은 정리 경로를 사용합니다. `last-run.json`에서 `startup_passed`, `shutdown_passed`, 시험을 요청했다면 `explicit_bounded_trial.passed`를 확인하세요. 상세 증거는 세션의 `runs/`에 있으며 비공개입니다. 정상 종료 후 같은 `run` 명령으로 새 실행 ID를 생성해 재시작할 수 있습니다. 실패한 실행·로그·컨테이너는 자동 삭제하지 않습니다.

중단 후 `active.json`이 남으면 이전 소유 프로세스가 종료됐는지 확인하기 전까지 새 기동을 거부합니다. 무조건 지우거나 시스템 전체 컨테이너를 종료하지 마세요. 시작 포트 3개가 다른 프로세스에 점유됐거나 GPU 여유가 8000 MiB 미만이면 시작하지 않습니다. 세션 설정을 변경하려면 새 세션을 초기화합니다.

위 기본 명령은 **headless 실행과 제공된 시험 경로**용입니다. 화면을 표시하려면 아래의 별도 GUI 세션을 준비합니다. 직접 내부 제어 명령을 주입하여 모드 전환이나 신호 정지를 우회하지 마세요.

현재 실행 프로필은 차량 위치추정에 NDT를 사용하지만 신호등 ROI 투영에는 기존 시뮬레이터 GT 기반 위치 입력 가정이 남아 있습니다. 따라서 모든 인지 입력이 센서만으로 구성된 검증으로 표현하면 안 됩니다. 신호 상태 자체는 카메라 모델 추론으로 판단하며 CARLA 정답 상태를 대입하지 않습니다.

**카메라 인지 시험은 `-quality-level=Epic`을 사용합니다.** 새 설치의 Low 품질 시험에서 신호등 외형은 검출됐으나 켜진 램프 색상 근거가 사라져 `no_visible_lamp_evidence` → unknown → 정지 대기가 발생했습니다. Epic으로 실행하자 카메라의 색상 표현이 복원됐고, 동일 교차로 직진 구간 약 40.6m를 완주해 native ARRIVED·정지·종료를 확인했습니다. 자산 로딩만 확인하는 저화질 시험을 신호 인식 시험으로 간주하지 마세요. 이 문제를 해결하기 위해 인식 신뢰도나 안전 정지 조건을 완화하지 않았습니다.

### 5.4 화면 표시: 선택적 CARLA·RViz 세션

GUI 지원 코드는 일반 호스트 NVIDIA Docker와 현재 로그인한 사용자의 로컬 X11 세션을 대상으로 합니다. 같은 PC에서 실제 창 표시와 제한 주행, RViz와 같은 위치·목표 입력 토픽 경로를 확인했습니다. 마우스로 모든 버튼을 눌러 본 시험은 아니며, 기존 headless 신호 시험을 GUI의 모든 시나리오 성공으로 간주하지 않습니다.

5.2절의 `init`에 `--gui`를 추가하고 새 `--bundle`과 `--name`을 사용하세요. `DISPLAY`, `XAUTHORITY`는 현재 데스크톱 로그인 환경의 값을 그대로 사용합니다. 호스트의 `xauth`, `xdpyinfo`가 필요합니다. 다른 호스트 주소의 X11, 중첩 Docker의 수동 GPU 라이브러리 연결은 GUI 모드에서 거부합니다. `xhost +`는 사용하지 않습니다.

기본 socket이 아닌 별도 **호스트** Docker를 사용하는 경우 두 인자를 같은 로컬 socket으로 명시합니다. `--parent`는 추가하지 않습니다.

```bash
# 5.2절 init의 다른 필수 인자와 함께 사용
--gui --docker-host unix:///your/runtime/docker.sock \
      --parent-host unix:///your/runtime/docker.sock
```

화면 인증은 선택한 display의 쿠키만 권한 0600으로 세션에 복사하고 인지 컨테이너에 읽기 전용으로 전달합니다. 이 파일을 공유하거나 Git에 넣지 마세요. 세션 종료 후 로그아웃·재로그인으로 인증 정보가 바뀌면 새 세션을 준비합니다. NVIDIA의 graphics/display 기능은 인지·RViz 컨테이너에만 활성화합니다.

`run` 명령은 동일합니다. CARLA는 1280×720 창으로 표시되고 RViz는 새 세션의 Autoware 설정으로 실행됩니다. 지도는 `base_link`를 중심으로 표시하고 `Camera6RawImage` 패널은 `/sensing/camera/camera6/image_raw`의 원본 영상을 보여줍니다. 이 패널은 검출 박스나 정답 신호 상태를 표시하는 인식 결과 영상이 아닙니다. 기존 설치 설정은 바꾸지 않습니다. 기동 완료 전에는 도구를 조작하지 마세요.

1. STOP과 위치추정 초기화 상태를 확인합니다. 위치를 바꾸려면 정지 상태에서만 **2D Pose Estimate**를 사용합니다.
2. 주행 가능한 차로 안에서 **2D Goal Pose**를 지정하고 경로·trajectory가 생성됐는지 확인합니다. 차로 밖 목표나 임의 지도 프로필은 자동으로 지원하지 않습니다.
3. 출발은 AutowareStatePanel의 Autoware Control과 Autonomous 기능을 명시적으로 조작할 때만 허용됩니다. 첫 시험은 낮은 속도 상한으로 진행하세요.
4. 정지는 패널의 STOP을 사용합니다. 전체 종료는 5.3절 `shutdown` 명령으로 요청하고 `shutdown_passed`를 확인합니다. RViz 창 닫기만으로 전체 시스템이 종료됐다고 간주하지 마세요.

GUI 모드는 실행 자원도 제한합니다. 인지·판단·제어는 각각 메모리 24/8/4 GiB와 CPU 8/4/2 코어 상당을 상한으로 사용하며, 추가 swap은 허용하지 않습니다. 실제 여유 메모리·GPU 메모리가 부족하면 실행하지 마세요.

## 6. 실제 통합 검증 결과

아래 표는 실제 실행 결과와 범위 밖 항목을 구분합니다. 기존 선택 구간·신호 결과는 10월 30일 headless 시험이며, 일반 호스트 GUI 시험은 별도 행으로 구분합니다.

| 검사 | 확인할 결과 | 현재 상태 |
|---|---|---|
| 새 컨테이너 기동 | 필수 노드·토픽·시간 동기 정상, 예상치 못한 종료 없음 | 새 이미지 3개 기동 및 필수 토픽 수신 확인 |
| 위치추정 | 올바른 PCD와 좌표 설정, NDT 수렴·TF 정상, GT 대체 없음 | NDT·EKF 초기화 및 약 8m 저속 시험에서 EKF–GT 최대 평면 오차 0.156m; 전체 도로 오차 미검증 |
| 경로 생성 | 유효 초기 위치와 goal에서 새 route와 trajectory 생성 | 정지 상태 API 요청 성공, 133점 trajectory와 제어 출력 확인 |
| 인지 | 실제 카메라 입력으로 검출·분류, 신호 ID·시간·상태 정상 | Epic 교차로 시험에서 적색·황색·녹색·녹색+좌회전·적색+좌회전 카메라 분류 확인. 하나의 접근 방향 시험이며 전체 신호/거리/날씨 정확도 인증 아님 |
| 신호와 판단 | 적색 정지, 녹색 직진, 녹색+좌회전 허용, 적색+좌회전은 직진 금지 | 좌회전 경로에서 적색 8.35초·녹색 직진 19.90초 정지 후 녹색+좌회전에 통과. 별도 좌회전 경로에서 적색+좌회전 신호로 실제 통과·37.941m ARRIVED. 직진 재시험은 적색+좌회전 9.55초 정지 후 녹색에 통과·34.675m ARRIVED. 정지선은 차체 앞끝 기준으로 판정했으며 통과 시 표시 신호·카메라 분류 모두 허용 상태 |
| 주행 제어 | 선택 구간 완주, 정지·재출발·좌우 선회 및 경계 이탈 측정 | 8.157m 저속 시험, Epic 직진 40.596m 및 좌회전 38.123m native ARRIVED·정지 확인. 두 구간 모두 충돌 없음, 최대 EKF–GT 평면 오차는 각각 0.164m·0.227m. 직진 물리 최고속도 약 5.15km/h. 경계 이탈/전체 도로 검증과 구분 |
| 종료·재시작 | 정지 요청, 소유 프로세스만 종료, 같은 설치에서 재기동 | 공개 세션 실행기로 새 포트 2490·ROS domain 223·새 전용 볼륨에서 8.014m 주행 후 STOP·종료. 같은 세션을 재시작해 경로 생성·14개 필수 토픽·STOP 상태 확인 후 공개 shutdown 명령으로 다시 종료. 두 실행 모두 세 컨테이너 exit 0·OOM 없음·CARLA 종료·포트 해제 |
| 일반 호스트 GPU·GUI | 표준 NVIDIA 연결, 실제 두 창, 위치·목표 연동, 제한 주행·정지 | 11월 1일 별도 호스트 Docker의 `--gpus all`로 CARLA·RViz 표시. 정지 상태 위치 입력 후 새 NDT 114개 수신, 목표 토픽으로 9구간·133점 새 경로 생성. 5 km/h 상한 시험에서 8.022m 주행·충돌 0·STOP·세 컨테이너 exit 0·OOM 없음·CARLA 정상 종료. 최대 EKF–GT 평면 오차 0.193m. 마우스 조작 전체·다른 PC·전체 도로 시험은 아님 |

고속 시험은 저속 기본 시험 이후에 수행합니다. 속도 상한은 실제 도달 속도와 다릅니다. 경로의 곡률·정지선·계획 속도 제한을 함께 기록합니다. 실패 사례는 누락하거나 허용 기준을 느슨하게 바꾸지 않고 원인과 재시험 결과를 남깁니다.

적색+좌회전 직진 시험의 앞선 두 실행은 도착·정지선 미진입에는 성공했지만 해당 신호 중 정지 관측이 1.65초·1.90초로 2초 기준에 못 미쳤습니다. 기준을 낮추지 않고 실제 관측된 정지선 앞 위치를 새 시험 시작점으로 사용하여 9.55초 대기를 확인했습니다. 원본 지도·신호 주기는 바꾸지 않았습니다. 모드 전환 중 사용자 STOP은 신호에 의한 정지 시간으로 계산하지 않습니다.

표시 신호와 인식 결과는 전환 경계에서 일시적으로 다를 수 있습니다. 마지막 직진 시험에서는 전환 후 1~4개 표본이 이전 상태로 관측됐으며 실제 정지선 통과 시에는 모두 녹색이었습니다. 이를 모든 프레임 100% 분류 정확도나 모든 신호의 시간 안전성 인증으로 표현하지 않습니다.

## 7. 배포 확인 및 제한

최종 소스 자동 검사 169개를 통과했습니다. 같은 PC의 별도 설치에서 다운로드 무결성, ONNX 4개 CPU 기본 추론, 지도 연결 재생성, CARLA 자산 단독 기동, 기본 및 SILS 이미지 빌드, 새 GPU 엔진 수치 검사, 위 표의 통합 실행을 확인했습니다. 공개 실행기의 경로·포트·ROS domain을 바꾼 실제 실행도 통과했습니다. 원래 작업 폴더를 그대로 실행한 결과로 대체하지 않았습니다.

새 실행기의 첫 기동에서는 CARLA 준비 전에 생성한 RPC 연결이 회복되지 않아 시간 초과가 발생했습니다. 해당 실행은 서버를 종료하고 실패 증거를 보존했습니다. 소유 포트가 열린 뒤 새 클라이언트로 연결하도록 수정한 후 실제 주행과 재시작을 모두 통과했습니다. 실패를 숨기거나 빌드를 반복해 덮지 않았습니다.

차량 위치추정은 NDT·EKF이지만 신호등 ROI 투영의 GT 위치 가정은 남아 있습니다. 전체 도로·우회전 차체 경계·50 km/h 실도달·여러 날씨/거리의 인지 정확도·전체 GUI 마우스 조작 절차·다른 PC 설치는 이 새 설치 시험으로 인증하지 않습니다. 특히 신호 전환 경계의 짧은 지연을 없다고 가정하지 마세요. 대상 환경에서 추가 검증이 필요합니다.

지도·PCD·좌표·3D 자산·개별 주행 원시 로그·지도 포함 판단 이미지는 비공개로 유지합니다. 공개 Git에는 소스, 모델 명세, 집계된 검증 결과와 이 문서만 포함합니다. 기존 `katech-autoware`의 main/HIL 설정은 이번 SILS 통합 검증에서 추가 변경하지 않았습니다. HIL·실차 검증은 배포받는 기관이 별도로 수행합니다.
