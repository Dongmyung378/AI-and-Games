# Python 연구 환경

**한국어** | [English](README.md) | [포트폴리오 홈](../README.ko.md)

이 디렉터리는 제공된 Hex 심판과 MCTS 선택 정책을 비교하기 위한 Python 에이전트를 포함합니다. 포트폴리오의 핵심 연구 변형은 [`agents/Group26/`](agents/Group26/)에 있습니다.

## 요구 사항

- Python 3.10 이상
- 심판과 `Group26` 에이전트는 외부 패키지 불필요

`agents/Hex/`의 신경망 실험은 과거 자료이며 NumPy와 PyTorch가 필요합니다. 아래 예제를 실행하는 데는 필요하지 않습니다.

## 경기 실행

이 디렉터리에서 실행합니다.

```bash
python Hex.py
```

기본 설정은 두 naive 에이전트의 11 x 11 경기입니다. 에이전트 인자는 `module.path ClassName` 형식입니다.

```bash
python Hex.py -b 7 -v \
  -p1 "agents.Group26.Agent_RAVE_TS Agent_RAVE_TS" \
  -p2 "agents.Group26.Agent_UCB Agent_UCB"
```

PowerShell에서는 줄 끝의 `\`를 백틱으로 바꾸면 됩니다. 전체 옵션은 `python Hex.py --help`에서 확인할 수 있습니다.

## 연구 에이전트

| 모듈 | 선택 정책 |
| --- | --- |
| `Agent_UCB.py` | 직접 MCTS 통계 기반 UCB1 |
| `Agent_TS.py` | 직접 통계 기반 톰슨 샘플링 |
| `Agent_RAVE_UCB.py` | RAVE 근거를 혼합한 UCB1 |
| `Agent_RAVE_TS.py` | RAVE 근거를 혼합한 톰슨 샘플링 |
| `mcts_core.py` | 공통 트리, 롤아웃, 역전파, 시간 관리 |

각 에이전트는 5분의 경기 예산으로 시작하고 매 수마다 남은 시간의 3.5%를 할당합니다. 파란색 플레이어는 2턴에 `(-1, -1)`을 반환해 파이 룰을 사용할 수 있습니다.

## 테스트

```bash
python -m unittest discover -s test -v
```

18개 테스트가 보드 생성, 수 검증, 색 처리, 타임아웃, 불법 수, 승리 판정, 스왑 규칙을 다룹니다.

## 토너먼트 실행기

[`HexTournament.py`](HexTournament.py)는 설정된 에이전트를 찾고 멀티프로세스로 순서가 있는 대진을 실행한 뒤 경기별·집계 CSV를 생성합니다. 원래 과제 디렉터리 규칙을 따르므로 토너먼트 검색 대상 에이전트 패키지에는 올바른 `cmd.txt`가 필요합니다.

## 실험 경로

정리된 정책 비교는 `Group26`에 있습니다. `Hex` 디렉터리는 별도의 신경망 탐색을 보존하며 최종 최적화 네이티브 구현은 [`../deployment/`](../deployment/README.ko.md)에 있습니다. 대체된 네이티브 프로토타입은 포트폴리오 트리에서 제거했으며 Git 이력에서 복구할 수 있습니다.

외부 연구 자료는 포트폴리오의 [참고문헌](../docs/references.md)에 정리되어 있습니다.
