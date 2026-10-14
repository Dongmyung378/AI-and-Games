# 재현 가이드

**한국어** | [English](reproducibility.md) | [프로젝트 개요](../README.ko.md)

## 검증할 수 있는 범위

탐색 소스, 고정 대국 목록, 평가 코드와 저장된 경기 결과를 제공합니다. 아래 세 가지 검증은 서로 다른 질문에 답합니다.

1. 새로운 장비에서 현재 에이전트를 빌드하고 실행합니다.
2. 저장된 수를 재생해 합법성, 파이 룰에 따른 플레이어 신원, 최종 보드와 승리 연결 경로를 확인합니다.
3. 명시한 대국을 다시 실행하고 실행 조건과 표본 범위 안에서 통계를 비교합니다.

재생 검증은 탐색을 다시 수행하거나 수의 전략적 최적성을 증명하는 작업이 아닙니다. 컴파일러, C++ 표준 라이브러리와 장비가 달라지면 탐색 경로가 완전히 같지 않을 수 있습니다. 같은 소스, 실행 파일, 시드와 워커 설정의 고정 횟수 반복 검사는 시간 예산 실험과 별도로 확인합니다.

## 준비와 빌드

Python 3.10 이상과 `g++`, `clang++` 또는 `zig c++`로 실행할 수 있는 C++17 컴파일러가 필요합니다. 현재 Python 실행기는 추가 패키지가 필요하지 않습니다. 소스 저장소나 ZIP으로 로컬 검증을 수행할 수 있으며 Kaggle과 Docker는 필수가 아닙니다.

저장소 루트에서 다음 명령을 실행합니다.

```bash
python -m hexai doctor
python -m hexai build
python -m unittest discover -s tests -v
```

`doctor`는 운영체제와 Python, 표시되는 논리 CPU 수, Linux CPU affinity와 읽을 수 있는 cgroup 제한을 출력합니다. 컴파일러 검색 결과도 제공합니다. 종료 코드가 0이어도 JSON의 `compiler.error`가 있으면 컴파일러를 찾지 못한 상태이므로 출력 내용을 확인하고 실제 `build`를 수행합니다.

컴파일러를 직접 선택하는 예시는 다음과 같습니다.

```bash
python -m hexai doctor --compiler clang++
python -m hexai build --compiler clang++
```

빌드는 `-std=c++17 -O3 -pthread`를 사용하고 네이티브 자체 검사를 수행합니다. 실행 파일과 빌드 기록은 `.local/bin/`에 저장하며 `engine/`, `deployment/`나 기존 실행 파일을 덮어쓰는 출력 위치를 거부합니다. 기록에는 컴파일러 버전, 빌드 명령과 소스, 컴파일러, 실행 파일의 해시가 포함됩니다.

대국 실행기와 별개로 짧은 탐색을 확인하려면 다음 명령을 사용합니다.

```bash
python -m hexai predict --board "R00,000,000" --colour B --turn 2 --policy rave_ts --iterations 1000 --workers 1 --swap 0
```

보드는 `R`, `B`, `0`으로 표현한 행을 쉼표로 구분하고, 좌표는 0부터 시작합니다. `predict`는 특정 보드의 탐색을 확인하는 명령입니다. 전체 평가에서는 대국 실행기가 스왑, 플레이어 신원과 누적 경기 시간을 관리합니다.

## 고정 대국 목록과 평가 분리

평가 목록에는 참가자 설정, 보드 크기, 예산, 경기 ID, 시드, 강제 시작 수와 선후공 교대 쌍 ID를 고정합니다. 정규화한 목록의 해시를 경기와 출력 디렉터리에 저장합니다. 각 쌍은 같은 시드와 시작 조건으로 참가자의 시작 순서만 바꾼 두 경기입니다.

개발 평가 목록은 다음과 같습니다.

| 목록 | 목적 | 명시한 규모 |
| --- | --- | --- |
| `configs/development-policy.json` | 네 정책 비교 | 96경기, 선후공 교대 48쌍 |
| `configs/development-features.json` | 브리지, 수 정렬과 RAVE 가중치 비교 | 64경기, 선후공 교대 32쌍 |

두 목록 모두 수당 전체 탐색 4,000회와 워커 두 개를 사용합니다. [실험 계획](../reports/study-plan.json)에는 결과를 확인하기 전에 정한 채택 기준이 있습니다. 정책은 선후공을 균형 있게 배치한 완료 경기 점수와 명시한 동률 규칙으로 선택합니다. 선택 가능한 설정 변경은 점수가 50%보다 최소 5%포인트 높고, 쌍 단위 부트스트랩 구간의 하한도 50%보다 높아야 합니다. 기준을 통과하지 못한 후보는 결과를 남기고 중단합니다. 정확성 수정은 승률에 따라 선택하는 실험 항목이 아닙니다.

최종 설정은 새로운 시드를 평가하기 전에 [`reports/selection.json`](../reports/selection.json)에 고정합니다. [`configs/final-policy.json`](../configs/final-policy.json)은 선택하지 않은 세 정책과 `legacy_ts`를 상대로 256경기, 선후공 교대 128쌍을 배정합니다. 선택한 정책은 자신의 상대 목록에서 제외합니다. [최종 계획의 보충 기록](../reports/final-plan-addendum.json)에 이 범위를 남기며 기존 계획을 다시 쓰지 않습니다.

최종 탐색 시드와 시작 조건 시드는 개발 목록과 겹치지 않습니다. 다만 새로운 시작 시드가 다른 보드 좌표나 처음 보는 시작 위치를 보장하지는 않습니다. 최종 결과를 본 뒤 다른 정책을 다시 선택하지 않습니다.

```bash
python -m hexai validate --config configs/final-policy.json --development configs/development-policy.json configs/development-features.json
python -m hexai evaluate --config configs/final-policy.json --output .local/final-policy
```

공개 집계는 [평가 집계 디렉터리](../reports/aggregates/)에, 원본 경기는 [실행별 기록 디렉터리](../reports/evaluation/)에 있습니다. 기본 목록은 `development-policy`, `development-features`, `final-policy`, `final-time-reference`이고 추가 목록은 `supplemental-time-policy`, `supplemental-workers`입니다. 개발과 기본 최종 정책의 실행은 `windows-shard0`, `windows-shard1`, `kaggle-shard2`, `kaggle-shard3`로 구분하며 원본 시간 기준과 추가 목록은 Kaggle 기록입니다. 각 실행의 `manifest.json`, `metadata.json`, `games/`를 보존합니다. 원시 네이티브의 `rave_k=300` 기본값과 선정 설정 `1000`은 구분합니다.

## 한 장비에서 실행하고 이어 실행하기

추가 시간 기준 목록은 [추가 계획](../reports/supplemental-plan.json)에 별도로 고정했습니다. 같은 엔진의 정책은 워커 두 개, 수당 0.25초로 비교하고, 워커 수별 목록은 RAVE-TS의 1·2·4·8워커를 고정된 UCB 두 워커와 비교합니다. 기본 최종 평가가 시작된 뒤 선언한 탐색적인 측정으로 구분하며 정책을 다시 선택하지 않습니다.

```bash
python -m hexai evaluate --config configs/supplemental-time-policy.json --output .local/supplemental-time-policy
python -m hexai evaluate --config configs/supplemental-workers.json --output .local/supplemental-workers
```

각 목록의 경기 쌍은 같은 장비에서 순차 실행합니다. 서로 다른 목록을 동시에 실행해 CPU 경합이 생긴 시간을 같은 단독 실행 결과로 해석하지 않습니다. 워커 비교는 벽시계 시간을 맞추며 총 CPU 작업량을 맞춘 비교는 아닙니다.

```bash
python -m hexai evaluate --config configs/development-policy.json --output .local/development-policy
python -m hexai evaluate --config configs/development-policy.json --output .local/development-policy --resume
```

첫 명령은 새로운 출력 디렉터리를 사용합니다. 두 번째 명령은 고정 평가 목록, 장비 메타데이터, 실행기 해시, 실행 파일 해시와 작업 분배 설정을 확인한 뒤 이어 실행합니다. 하나라도 달라지면 호환되지 않는 결과를 합치지 않고 별도 출력 디렉터리를 사용합니다.

경기가 끝날 때마다 JSON 결과, JSONL 수 기록과 진단 정보, CSV와 갱신된 요약을 저장합니다. 기존 경기 파일은 재생 검증 후 건너뜁니다. 결과 파일이 저장되기 전에 중단된 경기는 다시 실행합니다. 기록된 실패 경기를 더 좋은 결과로 자동 교체하지 않으며 기존 실패도 결과로 유지합니다.

```text
.local/development-policy/
├── manifest.json            고정 입력
├── metadata.json            장비, 실행기와 실행 파일 해시
├── games.csv                경기별 결과와 실패 상태
├── summary.json             기록 범위와 비교 통계
└── games/
    ├── GAME_ID.json          수, 결과, 명령과 진단 정보
    └── GAME_ID.jsonl         심판과 엔진 이벤트 기록
```

## 로컬과 Kaggle CPU에 나누어 실행하기

같은 평가 목록을 두 장비에 나눌 수 있습니다. 선후공을 교대한 두 경기는 쌍 전체를 한 장비에 배정합니다. 로컬에서는 다음과 같이 실행합니다.

```bash
python -m hexai evaluate --config configs/development-policy.json --output .local/development-policy-local --shard-index 0 --shard-count 2
```

CPU 전용 Kaggle 세션에서는 동일한 소스를 풀고 실행 파일을 빌드한 뒤 다른 분량을 실행합니다.

```bash
python -m hexai doctor
python -m hexai build
python -m hexai evaluate --config configs/development-policy.json --output .local/development-policy-kaggle --shard-index 1 --shard-count 2
```

이번 실험의 실제 Kaggle 점검에서는 논리 CPU 네 개와 네 CPU에 대한 affinity가 확인됐습니다. cgroup CPU quota는 `400000 100000`으로 CPU 네 개에 해당하는 시간 할당이며, 메모리 제한은 30GiB였습니다. x86_64 Linux에서 Python 3.13.15와 g++ 13.3.0을 사용했고 GPU는 요청하지 않았습니다. 이는 해당 세션의 측정 결과이며 앞으로 모든 Kaggle 세션의 자원을 보장하는 정보는 아닙니다. 새 실행에서는 `doctor`로 표시되는 CPU 수와 quota를 다시 확인합니다.

Kaggle 출력 디렉터리를 가져올 때 `games/` 구조와 평가 목록, 메타데이터를 그대로 유지합니다. 이후 다음 명령으로 집계합니다.

```bash
python -m hexai aggregate --inputs .local/development-policy-local .local/development-policy-kaggle --output .local/development-policy-combined.json --require-complete
```

집계는 서로 다른 목록, 중복 경기 ID와 재생 검증 실패를 거부합니다. `--require-complete`는 예정한 모든 경기의 결과가 기록됐다는 뜻이며 모든 경기가 성공적으로 완료됐다는 뜻은 아닙니다. 장비별 요약도 별도로 제공하므로 고정 예산의 대국 점수를 함께 설명하더라도 처리량과 시간 측정은 장비별로 구분합니다.

Kaggle 세션이 다시 시작되면 장비 메타데이터가 달라질 수 있습니다. 호환되지 않는 장비는 별도 실행으로 구분하고, 중복되지 않는 경기 배정을 명시해야 합니다. 이어 실행 검사를 우회하려고 메타데이터를 직접 바꾸거나 중복 결과를 함께 집계하지 않습니다.

## 저장된 경기 재생

로컬 정책 비교의 첫 경기를 확인하는 예시는 다음과 같습니다.

```bash
python -m hexai replay --input .local/development-policy-local/games/development-policy-ucb-vs-ts-000-0.json
```

재생 검증은 차례, 참가자 신원, 현재 색상, 승인한 수, 스왑과 최종 보드를 확인합니다. 완료 결과는 기록된 승리와 연결 경로가 일치해야 하며, 실패 경기에는 만들어 낸 승리가 없어야 합니다. 평가 실행기와 집계기는 읽는 경기마다 이 검증을 수행합니다.

## 워커 수와 시간 예산

```bash
python -m hexai benchmark --workers 1 2 4 8 --iterations 10000 --repeats 3 --board-size 11 --policy rave_ts --output .local/worker-benchmark.json
```

같은 종료 전 보드에서 전체 탐색 횟수를 맞추고 외부 응답 시간, 초당 탐색 횟수, 워커별 진단 정보와 프로세스 최대 RSS를 측정합니다. 승률 실험은 아니며 RSS는 Python 실행기를 제외합니다. 메모리 측정값이 없다는 것을 메모리 사용량이 0이라는 뜻으로 해석하지 않습니다.

장비마다 벤치마크를 따로 실행합니다. CPU 네 개를 할당받은 환경에서 워커 여덟 개를 실행해도 같은 자원을 나눠 사용합니다. 워커 설정은 스레드 수가 아니라 실제 처리량과 실행 안정성으로 결정합니다.

장비별 측정값과 반복별 진단 정보는 [Windows 벤치마크](../reports/benchmarks/windows.json)와 [Kaggle 벤치마크](../reports/benchmarks/kaggle.json)에 있습니다. [실험 기록](experiments.ko.md)의 표는 같은 장비 내 비교입니다.

고정 횟수는 탐색 작업량을 맞추는 비교이며, 시간 예산은 해당 장비의 처리 속도에서 실용적인 결정을 비교하는 방식입니다. 두 모드 모두 네이티브 경기 제한과 외부 응답 제한을 적용합니다. 전술이나 시작 수 규칙으로 탐색 0회에 수를 선택할 수도 있습니다. 시간 모드에서 매번 같은 탐색 횟수나 승리 경로가 나온다고 보장하지 않습니다.

## 기존 실행 파일의 시간 기준 비교

[`configs/final-time-reference.json`](../configs/final-time-reference.json)은 Kaggle/Linux에서 기존 소스를 별도 실행 파일로 다시 빌드해 수행하는 4경기 기준 비교입니다. 두 참가자 모두 워커 여덟 개와 플레이어당 경기 제한 300초를 사용합니다. 현재 참가자는 수당 추가 제한 5초를 적용하고, 기존 참가자는 원래의 적응형 시간 배분을 유지합니다. 따라서 수당 예산을 동일하게 맞춘 정책 비교나 기존 제출본보다 강하다는 통계적 근거로 해석하지 않습니다.

Linux에서 현재 실행 파일을 먼저 빌드한 뒤 다음과 같이 실행합니다.

```bash
python -m hexai build --legacy
python -m hexai evaluate --config configs/final-time-reference.json --output .local/final-time-reference
```

`--legacy`는 `deployment/agents/Group026/RAVE_TS.cpp`를 `.local/bin/` 아래에 빌드하고 기존 배포 실행 파일은 보존합니다. 실제 기존 소스와 비교하는 이 항목은 최종 고정 횟수 평가에서 사용하는 현재 엔진의 `legacy_ts` 제어 조건과 다릅니다. 기존의 11×11 지원 범위만 사용하며 Davis나 HexHex 상대를 다른 에이전트로 대신하지 않습니다.

원래 배포한 Linux 실행 파일의 해시와 실행 호환성은 별도로 확인합니다. 이 확인을 새 대국 결과에 합치거나 다시 빌드한 원본과의 네 경기 결과로 바꾸지 않습니다.

## 결과 묶음의 무결성 검증

공개 릴리스의 `reports/release-manifest.json`은 소스, 평가 목록, 집계와 저장 경기의 연결을 고정합니다. 다음 명령은 빌드나 새 대국 없이 저장 자료를 확인합니다.

```bash
python scripts/verify_release.py --manifest reports/release-manifest.json --output .local/release-verification.json
```

검증기는 원본 보존 목록의 해시, 실행 환경별 목록과 실행기·소스 해시, 중복 또는 누락 경기, 모든 수 기록의 심판 재생과 집계의 일치를 확인합니다. 이는 저장 자료의 무결성 검증이며 새 대국이나 외부 상대의 성능 평가를 수행하지 않습니다.

## 통계 해석과 자료 출처

주된 신뢰구간은 완결된 선후공 교대 쌍을 고정된 부트스트랩 시드로 다시 추출해 계산합니다. 경기별 Wilson 구간도 제공하지만 같은 쌍 안의 의존성을 반영하지 않으므로 보조 지표입니다. 승률에는 실패율, 미기록 경기, 완료 경기와 완료 쌍 수를 함께 제시합니다. 완료 경기 점수가 높더라도 실패가 잦으면 실행이 안정적이라고 판단할 수 없습니다.

과거 Davis와 HexHex 이미지는 새로운 내부 평가와 구분합니다. 외부 상대의 실행 파일과 당시 전체 조건은 제공되지 않습니다. `legacy_ts`는 현재 엔진을 공유하는 제어 조건이며 과거 경기의 정확한 재현이 아닙니다.

[기존 소스 목록](../reports/baseline/original-source-inventory.json)은 프레임워크, 배포 자료와 경기 근거의 보존 상태를 확인하는 자료입니다. 공개 결과에는 재현 명령과 해시를 상대 경로와 함께 제공하며, 인증 파일과 개인 활동 기록은 소스 ZIP이나 공개 결과에 포함하지 않습니다.
