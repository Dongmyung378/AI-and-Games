# 재현 가능한 배포 환경과 최종 에이전트

**한국어** | [English](README.md) | [포트폴리오 홈](../README.ko.md)

이 디렉터리는 Linux 토너먼트 환경과 최적화된 최종 에이전트를 보존합니다. [`agents/Group026/RAVE_TS.py`](agents/Group026/RAVE_TS.py)가 심판 인터페이스를 구현하고, 컴파일된 C++17 탐색 엔진 [`RAVE_TS`](agents/Group026/RAVE_TS)를 실행합니다.

## 이미지 빌드

Linux, macOS 또는 WSL에서 실행합니다.

```bash
docker build --build-arg UID="$(id -u)" -t hex-ai .
```

이미지는 Python 3.11이 포함된 Ubuntu 22.04를 기반으로 합니다. 제공된 과제 환경을 재현하기 위해 CPU 버전 TensorFlow 2.19.0, PyTorch 2.5.1, NumPy, pandas, scikit-learn을 설치합니다. 최종 RAVE-TS 에이전트 자체는 CPU만 사용합니다.

## 컨테이너 시작

```bash
docker run --cpus=8 --memory=8g \
  -v "$(pwd):/home/hex" \
  --name hex-ai --rm -it hex-ai /bin/bash
```

현재 디렉터리는 `/home/hex`에 마운트됩니다. Windows에서 저장소를 체크아웃했다면 컨테이너 안에서 실행 권한을 복원합니다.

```bash
chmod +x agents/Group026/RAVE_TS
```

## 최종 에이전트 실행

```bash
python3 Hex.py \
  -p1 "agents.Group026.RAVE_TS RAVE_TS" \
  -p2 "agents.Group026.RAVE_TS RAVE_TS"
```

어댑터는 네이티브 프로세스에 `START`, `CHANGE`, `SWAP` 메시지를 보내고 `x,y` 응답을 읽습니다. 토너먼트 진입점은 [`agents/Group026/cmd.txt`](agents/Group026/cmd.txt)에 기록되어 있습니다.

## 테스트

```bash
python3 -m unittest discover -s test -v
```

## 소스 및 산출물

| 경로 | 역할 |
| --- | --- |
| `agents/Group026/RAVE_TS.cpp` | 탐색, 휴리스틱, 프로토콜 처리를 구현한 C++17 소스 |
| `agents/Group026/RAVE_TS` | 미리 빌드된 Linux 토너먼트 실행 파일 |
| `agents/Group026/RAVE_TS.py` | `AgentBase`를 구현한 Python 어댑터 |
| `agents/Group026/cmd.txt` | 토너먼트 검색 진입점 |
| `Dockerfile` | 재현 가능한 과제 실행 환경 |

탐색 설계와 트레이드오프는 [아키텍처 문서](../docs/architecture.ko.md)에서 확인할 수 있습니다.
