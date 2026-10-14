# 저장된 평가 기록 분석

**한국어** | [English](README.md)

이 선택 도구는 완료된 평가 기록을 Python 표준 라이브러리로 분석합니다. 에이전트를 실행하거나 새 대국을 진행하지 않으며, 고정한 정책을 바꾸거나 현재 장비의 성능을 측정하지 않습니다. 저장소 루트에서 Python 3.10 이상으로 실행합니다.

## 시간과 자원 사용량

```bash
python tools/analysis/analyze_deep_evidence.py --summary reports/deep/aggregates/tactical-ablation.json --runs reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard00 reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard01 --output .local/tactical-costs.json
```

참가자와 장비 할당별로 외부 응답 시간, 네이티브 탐색 기록, 표본으로 측정한 프로세스 RSS와 노드 한도 관측값을 집계합니다. 저장된 집계와 경기 수 및 실행 서명을 대조하고, 없는 측정값은 추정하지 않습니다. 네이티브 처리량은 전체 탐색 반복 횟수를 네이티브 응답 경과 시간의 합으로 나눈 값이며, 워커별 경과 시간의 합과 다릅니다. 워커의 경과 시간은 CPU 사용 시간을 측정한 값이 아닙니다. 비용은 기록된 실행을 설명하며 승리의 원인을 입증하지 않습니다.

## 전술 수순과 조건별 판단 비용

```bash
python tools/analysis/analyze_tactical_traces.py --summary reports/deep/aggregates/tactical-ablation.json --runs reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard00 reports/deep/evaluation/tactical-ablation/hex-tactical-ablation-v1/evaluation-shard01 --output .local/tactical-traces
```

수순 분석인 `analysis.json`과 그래프에서 사용하는 상대별 집계인 `tactical-metrics.json`을 저장합니다. 선후공 교대 쌍 안에서 실제 좌표 수순과 기록된 워커 시드를 비교합니다. 조건별 시간은 같은 보드와 차례 및 색상이 두 경기 모두에 나타난 경우에만 비교하며, 전체 에이전트의 속도 개선 배수로 해석하지 않습니다. 원시 경기 해시도 함께 남깁니다. 시간은 당시 Windows 또는 Kaggle 환경의 측정값이므로 다른 장비에서 같게 재현될 필요는 없습니다.

고정 탐색 횟수의 경기력, 공통 경기 시간 예산과 워커 처리량의 차이는 [실험 설명](../../docs/experiments.ko.md)을 참고해 주세요.

공개한 [전술 비용](../../reports/deep/analysis/tactical-costs.json), [수순 분석](../../reports/deep/analysis/tactical-traces.json)과 [그래프 집계](../../reports/deep/analysis/tactical-metrics.json)는 같은 400경기 기록에서 계산했습니다. 원시 소스 해시는 경기 기록과 공개 자료 목록에서 확인할 수 있습니다.
