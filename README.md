# KATECH Autoware SILS

CARLA 0.9.15와 K-Autoware의 설치·빌드를 한 곳에서 관리하기 위한 공개 저장소입니다.
현재는 **새 설치 환경의 통합 검증 단계 후보**입니다. 공식 CARLA, 공개 모델, 비공개 C-Track을 다시 다운로드해 별도 폴더에 설치했고, CARLA 지도·신호등 자산 기동 시험을 통과했습니다. **새 컨테이너로 Autoware까지 연결한 전체 주행 검증과 최종 매뉴얼은 아직 완료하지 않았습니다.**

## 구성

- `sources.lock.json`, `autoware.repos`: 기존 K-Autoware와 하위 저장소 32개의 고정 커밋.
- `patches/`: 별도 로컬 커밋으로만 존재하던 CARLA 센서 기본 설정. 기존 저장소에는 적용하지 않습니다.
- `reference_runtime/`: 현재 SILS의 신호 제어, 위치추정 감시, 조향·화면 추적, 브리지, 계획 보정 소스 스냅샷. 아직 새 설치 경로에 연결하지 않았습니다.
- `aihub188_mobilenetv2/`, `ctrack_perception_v2/`: 학습 모델 전처리·후처리·신호 분류 및 투영 코드.
- `models/manifest.json`: 공개 ONNX 파일의 버전·크기·SHA256·입출력 규약.
- `carla.lock.json`: 공식 CARLA 패키지 URL·고정 체크섬. CARLA 본체를 이 Git 저장소에 복사하지 않습니다.
- `map_selection/`: 지도 선택·계획·기본 자산 다운로드 준비 도구. **실행 런처가 아닙니다.**
- `tools/private_assets.py`, `tools/install_assets.py`: 인증된 C-Track 자산·실행 프로필 다운로드, 안전한 새 폴더 설치, 실행 프로필에 맞는 NDT PCD 선택.
- `tools/generate_movements.py`, `tools/overlay_sources.py`: 비공개 지도에서 방향별 차로 연결 생성, 새 소스 트리에 SILS 판단·종료 보정 적용. 생성 결과와 해당 판단 이미지는 비공개 지도 정보를 포함하므로 공개 push하면 안 됩니다.

## 공개 모델

[models-korean-tl-20261030 Release](https://github.com/OSS-TEST-GROUP/katech-autoware-sils/releases/tag/models-korean-tl-20261030)에서 ONNX 4개를 제공합니다. 총 89,468,762 bytes(약 89.47 MB)입니다.

| 모델 | 배치 | 용도 |
|---|---|---|
| YOLOX-S `scale_02` | 1 / 6 | 차량용·보행자용 신호등 검출 |
| MobileNetV2 후보 C | 1 / 6 | 적색·황색·녹색·녹색+좌회전·적색+좌회전·거부 클래스 |

YOLOX의 기존 `car`, `pedestrian` 라벨은 **차량/보행자 객체가 아니라 차량용/보행자용 신호등**을 뜻합니다. 전처리와 출력 해석은 반드시 모델 명세 및 제공 코드를 따르세요.

소유자의 공개 배포 요청에 따라 모델을 게시합니다. 학습 사진·라벨·개인정보·데이터셋 및 이 PC에서 생성한 TensorRT `.engine`은 포함하지 않습니다. ONNX로부터 대상 GPU에서 엔진을 생성하고 수치·판단 결과를 검증해야 합니다. 모델 다운로드가 곧 실차/HIL 사용 승인이나 안전성 보증을 의미하지 않습니다.

## 사용 준비 도구

Ubuntu 22.04 / amd64를 첫 번째 대상 환경으로 합니다. Python 3, PyYAML, Git, vcstool이 필요합니다. 빌드에는 기존 K-Autoware 빌드 문서에 명시된 Docker Buildx 및 NVIDIA 환경 등이 추가로 필요합니다.

```bash
python3 tools/prepare.py plan
python3 tools/prepare.py fetch-models --destination /원하는/새모델폴더
python3 tools/prepare.py fetch-carla --destination /원하는/새CARLA캐시
python3 tools/prepare.py sources --destination /원하는/새빌드작업공간
python3 tools/prepare.py build-base --destination /위에서/준비한빌드작업공간
```

`fetch-*`는 다운로드와 SHA256 검증까지만 수행합니다. CARLA 압축 해제·지도 설치·Autoware 모델 배치·실행은 하지 않습니다. `sources`는 새 폴더만 사용하고 기존 작업 트리를 덮어쓰지 않습니다. `build-base`는 고정 소스로 기본 3개 파티션 이미지를 빌드하는 명령이며, **아래의 SILS 전용 모듈 통합을 완료한 최종 이미지 빌드가 아닙니다.** Docker 이미지는 자동 push하지 않습니다.

CARLA 소스 빌드는 기본값이 아닙니다. 개발자가 필요할 때 Unreal Engine 접근 권한을 준비한 뒤 추가할 선택 기능이며 아직 자동화하지 않았습니다.

## 별도 설치 검증 절차

아래는 검증 중인 준비 절차이며 **최종 SILS 실행 매뉴얼이 아닙니다.** 기존 작업 폴더와 다른 새 경로를 사용하세요. CARLA 설치에는 최소 60 GiB 여유 공간을 요구하며, 소스 컨테이너 빌드 공간은 별도로 필요합니다. Docker 저장 위치도 확인해야 합니다. 소스 폴더만 SSD에 놓아도 Docker 이미지가 자동으로 그 SSD에 저장되는 것은 아닙니다.

`DOWNLOADS`와 `INSTALL`은 사용자가 선택한 새 다운로드·설치 경로입니다. C-Track 다운로드는 GitHub 자격 증명 도우미 또는 `GH_TOKEN`/`GITHUB_TOKEN` 환경의 기존 읽기 권한을 사용합니다. 토큰을 명령 인자나 설정 파일에 직접 적지 마세요. C-Track 저장소가 비공개인지 확인하며 자산 서버로 인증 토큰을 전달하지 않습니다.

```bash
python3 tools/prepare.py fetch-carla --destination "$DOWNLOADS/carla"
python3 tools/prepare.py fetch-models --destination "$DOWNLOADS/models"
python3 tools/private_assets.py --map ctrack --cache "$DOWNLOADS/private"
python3 tools/install_assets.py --map ctrack --downloads "$DOWNLOADS" --destination "$INSTALL"
python3 tools/check_models.py --models "$DOWNLOADS/models" --output "$INSTALL/models-check.json"
```

설치에는 `zstd`와 보안 업데이트된 Python의 `tarfile.data_filter`가 필요합니다. 모델 검사에는 `requirements-inference.txt`의 Python 의존성이 필요합니다. 크기·SHA256이 다르거나 기존 설치 폴더가 있으면 덮어쓰지 않고 중단합니다. 실패한 부분 설치도 자동 삭제하지 않습니다.

NDT에는 보충 프로필의 `sils_map_config/ndt/pointcloud_map.pcd`를 사용합니다. 기본 자산의 이전 PCD와 섞지 않습니다. 설치 결과는 `assets-installation.json`에 기록되며 이 파일의 `runtime_ready`는 아직 `false`입니다.

지도별 계획 소스 준비에는 Native Lanelet2 Python 바인딩과 NumPy가 필요합니다. `SILS_SOURCE`는 `prepare.py sources`로 준비한 새 소스 트리이며 기존 빌드 중인 트리를 사용하지 마세요.

```bash
python3 tools/generate_movements.py --installation "$INSTALL"
python3 tools/overlay_sources.py apply --destination "$SILS_SOURCE" --installation "$INSTALL"
python3 tools/overlay_sources.py verify --destination "$SILS_SOURCE"
python3 tools/prepare.py build-sils --destination "$SILS_SOURCE"
```

일반 Lanelet2에서 지원하지 않는 `speed_bump` 경고는 방향 연결 생성 용도로만 구분해 기록합니다. 다른 해석 오류, 누락된 차로·신호 규칙은 거부합니다. 지도 원본에서 과속방지턱을 삭제하지 않으며 Autoware용 지도는 그대로 유지합니다.

`build-sils`는 준비한 네이티브 소스를 빌드하는 명령입니다. 런처·GPU 엔진·런타임 설정 연결까지 완료했다는 의미는 아닙니다. 빌드 결과는 자동 업로드하지 않습니다.

2026-10-30 별도 설치에서 다운로드 무결성, 모델 4개의 CPU 기본 추론, 지도별 연결 재생성, CARLA 자산 기동·카메라·시험 서버 종료를 확인했습니다. 같은 PC에서의 검증이며 다른 PC 설치나 Autoware 통합 주행 통과로 해석하면 안 됩니다. 검사 범위는 `validation.json`을 참고하세요.

## 비공개 지도와 분리

C-Track 지도, PCD, 신호등·지주 3D 자산, 실제 배치 좌표와 지도별 실행 설정은 [별도 비공개 저장소](https://github.com/OSS-TEST-GROUP/katech-C-Track-Carla-map)에만 보관합니다. 이 공개 저장소에는 해당 파일을 넣지 않습니다. 권한 있는 사용자는 위 다운로드·설치 도구로 가져올 수 있습니다. 지도 선택에서 전체 SILS 실행까지 이어지는 단일 런처는 아직 준비 중입니다.

Town을 선택해도 대응하는 Autoware Lanelet2/PCD/좌표 설정이 있어야 합니다. C-Track 설정을 다른 지도에 대신 적용하지 않습니다.

## 아직 남은 작업

1. 새 경로에 런타임 모듈 연결, 지도별 생성 헤더/설정 주입, 컨테이너 내 설치 위치 정리.
2. 모델 엔진 생성·검증 및 인지 파이프라인 연결. 현재 TRT 어댑터의 기존 엔진 체크섬 허용 목록은 그대로 보존된 참고 코드이며 새 GPU 엔진에 자동 적용할 수 없습니다.
3. 준비된 계획 플러그인·종료 보정의 소스 빌드 완료 및 결과 검증. 지도별 `movement_bindings.hpp`, `movement_test_cases.hpp`는 비공개 입력으로 생성하며 공개하지 않습니다.
4. 지도 선택→다운로드→설치→시작/종료 단일 명령 연결, 새 설치 폴더에서 전체 빌드·주행 검증.

`reference_runtime`는 기존 컨테이너 경로·토픽·도메인 가정을 보존한 참고 구현입니다. 그대로 실행하면 완성된 런처가 되지 않습니다. 시뮬레이션 시작 및 자동 주행 명령은 이번 게시 도구가 수행하지 않습니다.

SILS 변경은 기존 `katech-autoware`의 HIL·실차 배포에 자동 병합하지 않습니다. 공개 여부와 별개로 실차/HIL 검증은 별도입니다.
