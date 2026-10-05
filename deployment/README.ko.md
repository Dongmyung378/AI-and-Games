# Linux 배포 환경과 최종 에이전트

**한국어** | [English](README.md) | [포트폴리오 홈](../README.ko.md)

이 디렉터리는 CPU만 사용하는 최종 C++17 에이전트와 Python 심판을 제공합니다. 네이티브 보드는 **11 x 11**을 지원하며, 제공된 실행 파일은 **Linux x86_64**용입니다. Windows에서는 x86_64 WSL, macOS에서는 Linux/amd64 컨테이너를 사용할 수 있습니다. 크기를 바꿔 실험하는 Python 연구 에이전트는 [`../engine/README.ko.md`](../engine/README.ko.md)에 설명했습니다.

## 제공된 실행 파일로 실행

Python 3.10 이상이 설치된 Linux x86_64에서 이 디렉터리로 이동한 뒤 실행합니다.

```bash
chmod +x agents/Group026/RAVE_TS
python3 Hex.py -l game.log
```

기본 선공·후공은 모두 `agents.Group026.RAVE_TS RAVE_TS`입니다. 각 수에서 네이티브 탐색 워커 8개를 사용하고 플레이어별 전체 시간 예산은 5분입니다. 셀프플레이에는 메모리 약 8 GiB를 확보하는 것을 권장합니다. 이 실행에는 모델, 학습 데이터, API 키, GPU, 별도 Python 패키지가 필요하지 않습니다. 어댑터는 자신의 소스 옆에서 실행 파일을 찾아 현재 디렉터리의 영향을 받지 않습니다.

로그에는 수, 플레이어별 누적 수 계산 시간, 승자와 종료 사유가 기록됩니다. 보드 상세 출력은 `-v`, 호환되는 에이전트 선택은 `-p1`·`-p2`를 사용합니다. C++ 배열과 휴리스틱이 11로 고정되어 있으므로 `python3 Hex.py -b 7`은 두 네이티브 프로세스를 생성하기 전에 거부합니다. 다른 크기의 비교 실험은 Python 연구 엔진에서 실행합니다.

제공된 바이너리는 `x86_64-linux-musl` 대상의 정적 실행 파일입니다. 컴파일러, 빌드 명령, 소스·실행 파일 체크섬은 [`build-info.json`](agents/Group026/build-info.json)에 기록했습니다. 소스나 어댑터를 변경하면 바이너리도 함께 다시 빌드해야 합니다.

## 소스 재빌드

Linux C++17 컴파일러와 pthread 지원이 필요합니다.

```bash
g++ -std=c++17 -O3 -pthread agents/Group026/RAVE_TS.cpp -o agents/Group026/RAVE_TS
chmod +x agents/Group026/RAVE_TS
```

이 명령은 현재 Linux 컴파일러의 런타임을 사용합니다. 저장소의 정적 실행 파일은 Zig 0.15.2와 `build-info.json`의 명령으로 만들었습니다. Windows 대상 컴파일러가 생성한 실행 파일은 형식이 달라 Linux 바이너리를 대체할 수 없습니다.

## 네이티브 프로토콜

[`RAVE_TS.py`](agents/Group026/RAVE_TS.py)는 수마다 버전이 명시된 한 줄을 보냅니다.

```text
V2;current-colour;11;command;opponent;board;turn
```

`current-colour`는 `R` 또는 `B`, `command`는 `START`·`CHANGE`·`SWAP`입니다. `CHANGE`는 `opponent`에 `x,y`를 넣고 다른 명령은 해당 칸을 비웁니다. `board`는 `0`·`R`·`B`로 구성된 길이 11의 행 11개를 쉼표로 구분합니다. `turn`은 양의 정수입니다. 응답은 `x,y`이며 합법적인 오프닝 스왑은 `-1,-1`입니다.

파이 룰 이후에는 **두 플레이어의 색이 모두 바뀝니다**. 스왑한 플레이어의 다음 입력은 `CHANGE`이므로 어댑터는 모든 요청에 심판이 지정한 현재 색을 포함합니다. 운영 파서는 각 필드를 검증하고 전술 검사와 MCTS보다 먼저 현재 역할을 적용합니다. 버전이 없는 과거 메시지는 프로토콜 오류로 종료합니다. 토너먼트 진입점은 [`cmd.txt`](agents/Group026/cmd.txt)를 유지합니다.

## 테스트

Python 어댑터·심판 검사는 별도 패키지 없이 실행합니다. Linux x86_64에서는 제공된 바이너리의 오프닝 스왑과 색 변경 후 빠른 전술 수까지 검사합니다.

```bash
python3 -m unittest discover -s test -v
```

양쪽 스왑 참여자의 역할 추적에 실제 운영 C++ 파서를 연결하려면 다음과 같이 실행합니다.

```bash
g++ -std=c++17 -O2 -pthread test/native_protocol.cpp -o /tmp/hex-native-protocol
/tmp/hex-native-protocol
HEX_PROTOCOL_TEST_BINARY=/tmp/hex-native-protocol python3 -m unittest discover -s test -v
```

CI는 결합 프로토콜 검사, 네이티브 스모크 검사, 연구 엔진 테스트를 실행합니다. 이 검사는 실행 가능성과 게임·프로토콜 동작을 확인하며 경기력 측정이나 과거 토너먼트 재현을 의미하지 않습니다.

## 이미지 빌드

보존한 과제용 컨테이너는 선택 사항입니다. Docker가 설치된 Linux 셸, macOS 또는 WSL에서 실행합니다.

```bash
docker build --platform linux/amd64 --build-arg UID="$(id -u)" -t hex-ai .
```

이미지는 Ubuntu 22.04 CUDA 12.3 런타임을 기반으로 Python 3.11, g++, TensorFlow 2.19.0, PyTorch 2.5.1, NumPy, pandas, scikit-learn을 설치해 폭넓은 과제 환경을 제공합니다. 최종 RAVE-TS 실행에는 Python 표준 라이브러리와 CPU C++ 코드만 사용합니다. 일부 과거 환경 의존성은 버전이 고정되지 않아 당시 토너먼트 환경의 완전한 동결본은 아닙니다.

## 컨테이너 시작

```bash
docker run --platform linux/amd64 --cpus=8 --memory=8g \
  -v "$(pwd):/home/hex" \
  --name hex-ai --rm -it hex-ai /bin/bash
```

현재 디렉터리는 `/home/hex`에 마운트됩니다. Windows에서 저장소를 체크아웃했다면 컨테이너 안에서 실행 권한을 복원합니다.

```bash
chmod +x agents/Group026/RAVE_TS
```

컨테이너 안에서 위의 경기 실행, 소스 재빌드, 테스트 명령을 사용할 수 있습니다. 최종 네이티브 에이전트에 CUDA 하드웨어는 필요하지 않습니다.

## 소스 및 산출물

| 경로 | 역할 |
| --- | --- |
| `agents/Group026/RAVE_TS.cpp` | 탐색, 휴리스틱, 프로토콜 처리를 구현한 C++17 소스 |
| `agents/Group026/RAVE_TS` | 미리 빌드된 정적 Linux x86_64 실행 파일 |
| `agents/Group026/build-info.json` | 컴파일러, 대상, 명령, 실행 파일·소스 체크섬 |
| `agents/Group026/RAVE_TS.py` | `AgentBase`를 구현한 Python 어댑터 |
| `agents/Group026/cmd.txt` | 토너먼트 검색 진입점 |
| `test/native_protocol.cpp` | 운영 파서와 스왑한 양쪽 플레이어의 역할 회귀 검사 |
| `test/test_native_adapter.py` | 심판·어댑터 계약과 제공된 네이티브 실행 검사 |
| `Dockerfile` | 네이티브 빌드 도구를 포함한 과제 실행 환경 |

탐색 설계와 트레이드오프는 [아키텍처 문서](../docs/architecture.ko.md)에서 확인할 수 있습니다.
