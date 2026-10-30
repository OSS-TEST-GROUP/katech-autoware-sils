# KATECH Autoware SILS 통합 설치·검증 매뉴얼

작성 기준: 2026-10-30. **새 설치 통합 검증 진행 중인 초안**입니다. 아래의 준비·빌드는 실행 확인했으며, 전체 주행을 통과했다는 의미는 아닙니다. 다른 PC와 HIL·실차는 검증 범위에 포함하지 않습니다.

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

## 5. 통합 실행 준비 — 구현·검증 중

현재 공개 `reference_runtime`은 명시적인 `runtime.json`의 접속 주소·포트·ROS domain을 확인하도록 이식 중입니다. 컨테이너 경로 연결과 호스트 안전 감시가 필요하므로 개별 파일을 그대로 실행하지 마세요. 지도 선택부터 실행까지 이어지는 배포 런처는 아직 완료되지 않았습니다. 존재하지 않는 시작 명령을 이 문서에서 안내하지 않습니다.

새 실행 환경에는 다음 연결이 필요합니다.

1. 새 CARLA 설치와 지도별 프로필, 고유 RPC 포트·ROS domain·실행 이름·결과 디렉터리.
2. 이번에 빌드한 세 이미지와 읽기 전용 소스·지도 마운트, 분리된 로그·모델 엔진 캐시.
3. YOLOX와 MobileNetV2 후보 C의 전처리·후처리, 대상 GPU에서 만든 엔진 및 검사 결과. 다른 GPU의 기존 TensorRT 엔진을 검증 없이 재사용하지 않습니다.
4. NDT·gyro odometry·EKF 연결과 초기 위치 설정. GT 위치로 대체한 시험을 NDT 통과로 기록하지 않습니다.
5. 학습 모델의 신호 출력 연결. CARLA 정답 신호를 인식 결과처럼 사용하지 않습니다.
6. 시작 시 정지 상태, 장애 시 정지, 소유권을 확인한 종료·재시작 처리.

현재 실행 프로필은 차량 위치추정에 NDT를 사용하지만 신호등 ROI 투영에는 기존 시뮬레이터 GT 기반 위치 입력 가정이 남아 있습니다. 따라서 모든 인지 입력이 센서만으로 구성된 검증으로 표현하면 안 됩니다. 신호 상태 자체는 카메라 모델 추론으로 판단하며 CARLA 정답 상태를 대입하지 않습니다.

**카메라 인지 시험은 `-quality-level=Epic`을 사용합니다.** 새 설치의 Low 품질 시험에서 신호등 외형은 검출됐으나 켜진 램프 색상 근거가 사라져 `no_visible_lamp_evidence` → unknown → 정지 대기가 발생했습니다. Epic으로 실행하자 카메라의 색상 표현이 복원됐고, 동일 교차로 직진 구간 약 40.6m를 완주해 native ARRIVED·정지·종료를 확인했습니다. 자산 로딩만 확인하는 저화질 시험을 신호 인식 시험으로 간주하지 마세요. 이 문제를 해결하기 위해 인식 신뢰도나 안전 정지 조건을 완화하지 않았습니다.

## 6. 통합 검증과 예상 결과

아래 표는 **실행한 검사와 아직 남은 검사**를 구분합니다. 부분 성공을 전체 통합 완료로 해석하면 안 됩니다.

| 검사 | 확인할 결과 | 현재 상태 |
|---|---|---|
| 새 컨테이너 기동 | 필수 노드·토픽·시간 동기 정상, 예상치 못한 종료 없음 | 새 이미지 3개 기동 및 필수 토픽 수신 확인 |
| 위치추정 | 올바른 PCD와 좌표 설정, NDT 수렴·TF 정상, GT 대체 없음 | NDT·EKF 초기화 및 약 8m 저속 시험에서 EKF–GT 최대 평면 오차 0.156m; 전체 도로 오차 미검증 |
| 경로 생성 | 유효 초기 위치와 goal에서 새 route와 trajectory 생성 | 정지 상태 API 요청 성공, 133점 trajectory와 제어 출력 확인 |
| 인지 | 실제 카메라 입력으로 검출·분류, 신호 ID·시간·상태 정상 | 메시지 연결 확인; 시작 위치에서 신호등이 투영되지 않아 실제 신호 분류 정확도 미검증 |
| 신호와 판단 | 적색 정지, 녹색 직진, 녹색+좌회전 허용, 적색+좌회전은 직진 금지 | 미실행 |
| 주행 제어 | 선택 구간 완주, 정지·재출발·좌우 선회 및 경계 이탈 측정 | 8.157m 저속 시험 및 Epic에서 교차로 직진 40.596m native ARRIVED·정지 확인. 직진 물리 최고속도 약 5.15km/h, EKF–GT 최대 평면 오차 0.164m, 충돌 없음. 좌회전·신호 시점 대조·경계 이탈은 별도 검증 |
| 종료·재시작 | 정지 요청, 소유 프로세스만 종료, 같은 설치에서 재기동 | 새 이미지 반복 기동 및 저속 주행 후 세 컨테이너 모두 exit 0·OOM 없음, CARLA 종료 확인; 반복 경로 시험 진행 중 |

고속 시험은 저속 기본 시험 이후에 수행합니다. 속도 상한은 실제 도달 속도와 다릅니다. 경로의 곡률·정지선·계획 속도 제한을 함께 기록합니다. 실패 사례는 누락하거나 허용 기준을 느슨하게 바꾸지 않고 원인과 재시험 결과를 남깁니다.

## 7. 현재 확보한 증거와 배포 기준

같은 PC의 별도 설치에서 다운로드 무결성, ONNX 4개 CPU 기본 추론, 지도 연결 재생성, CARLA 자산 단독 기동·카메라·종료, 기본 및 SILS 이미지 빌드를 확인했습니다. 이 결과는 다른 PC 설치나 통합 주행 성공을 보장하지 않습니다.

최종 배포 문서는 실행 명령, 실제 사용 버전, 지도·모델 해시, 시험 구간, 통과/실패 결과, 남은 제한 사항을 포함해야 합니다. 본 문서의 미실행 항목을 실제 증거로 갱신한 뒤 통합 검증 완료 여부를 판단합니다. HIL·실차 검증은 배포를 받는 기관에서 별도로 수행합니다.
