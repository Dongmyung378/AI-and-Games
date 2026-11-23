# Hex Search v1.2 기술 아키텍처

[English](architecture.md) | [README](../README.ko.md)

> 버전 진화: `v0.0` (Flat Arena GRAVE-TS 코어) → `v1.0` (MCTS Solver + Two-Distance + Lock-Free Shared-Tree + 6링 패턴) → `v1.1` (내쉬 파이 룰 오프닝 북 + Pondering) → **`v1.2`** (Exact Disjoint-Carrier VC Solver + MoHex 탐색 튜닝).

## 1. 제로 의존성 순수 CPU 시스템 설계 (`native/hex_search.cpp`)

외부 라이브러리 없이 단일 C++17 소스 파일(`-std=c++17 -O3 -pthread`)로 구현해 캐시 지역성과 멀티코어 확장성을 극대화했습니다.

- **O(1) Edge-Bitmask Union-Find**: 각 돌 그룹 루트에 2비트 `edge_flags`(`1 = 시작 변`, `2 = 목표 변`)를 유지해, 롤아웃 매 스텝마다 전체 BFS 없이 `edge_flags[root] == 3` 한 줄로 승리를 즉시 판정합니다.
- **사전 계산 토폴로지 (`BoardTopology`)**: 보드 크기별로 6이웃, 6링 순환 인덱스, 변 비트마스크, 내부·엣지 2브릿지 방어 테이블을 시작 시 한 번만 계산합니다.
- **경량 Flat Arena & Lazy Expansion**: 연속 메모리 아레나(`expand_threshold = 8`)와 별도 Flat AMAF 테이블 풀(RAM의 `65%` AMAF, `35%` 노드)을 사용해 포인터 기반 트리 대비 RSS 메모리를 최대 `4.27×` 절감했습니다.
- **고속 결정적 PRNG**: 인라인 `xoshiro256**`, 나눗셈 없는 Lemire 범위 정수 생성, Marsaglia-Tsang Gamma/Beta 샘플러와 정밀 꼬리 Box-Muller 가우시안 가속($\alpha, \beta \ge 16$).

## 2. 탐색 정책: Variance-Capped GRAVE-TS

각 내부 노드에서 직접 Monte Carlo 통계와 조상 노드 AMAF 통계(GRAVE)를 결합합니다:

$$\beta = \frac{n_{\text{amaf}}}{n_{\text{mc}} + n_{\text{amaf}} + b \cdot n_{\text{mc}} n_{\text{amaf}}}, \qquad b = 0.0005$$

- **분산 상한(Variance Capping)**: 조상 노드에서 AMAF를 빌려올 때 의사 카운트를 `32`로 상한 제한(`eff_n = n_mc + pw + beta * min(amaf_n, 32)`)합니다. 상한이 없을 때는 Beta 사후 분산이 붕괴해 `33.3%`로 하락했으나, `32` 상한 적용 후 `56.7%`로 반전했고 튜닝된 `GRAVE-UCB`도 `56.7%`에서 `73.3%`로 압도했습니다.
- **휴리스틱 프라이어 (`prior_weight = 8.0`)**: 얕은 노드(`depth <= 4`)에서는 4방향 버킷 큐 **Two-Distance 연결 포텐셜**과 학습된 **6링 패턴 로짓**을 결합하고, 깊은 노드에서는 O(1) 6링 로짓과 직전 수 거리 특징을 사용합니다.

## 3. Lock-Free Shared-Tree 병렬 MCTS & 실시간 Pondering

- **원자적 노드 확장**: 워커 스레드가 `state.fetch_or(NODE_EXPANDING, memory_order_acq_rel)`로 확장 권한을 경합 없이 획득하고 `NODE_EXPANDED`(`memory_order_release`)로 게시합니다. 경합 시 뮤텍스 대기 없이 즉시 롤아웃으로 진입합니다.
- **Virtual Loss**: 하강 시 원자적 `vloss`를 증가시켜(`n_mc = visits + 2 * vloss`) 12스레드가 서로 다른 유망 분기로 분산 탐색하며, 역전파 시 정확히 0으로 복구합니다(`--self-test` 전 노드 잔여 `vloss == 0` 검증).
- **1플라이 / 2플라이 서브트리 압축 재사용**: 매 턴 `rebase_subtree`로 살아남은 서브트리를 압축하고 증명 플래그를 상향식 재계산합니다.
- **상대 턴 Pondering (`PONDER;` / `STOP_PONDER`)**: AI가 수를 두자마자 GUI가 상대 턴 보드에 `PONDER;`를 전송해 `node_cap`의 `85%`까지 백그라운드 확장하고, 상대 수가 입력되면 `<1ms` 만에 정지해 1플라이 리베이스로 수백만 방문 수를 그대로 이어받습니다(MoHex 3 77수 승리에서 **`+7,480만` 공짜 방문 수** 재사용).

## 4. Exact Disjoint-Carrier 가상 연결(VC) 솔버 & Mustplay

Shannon Pairing Strategy(Benzene/MoHex 정리 1)에 따라, 시작 변에서 목표 변까지 **서로 겹치지 않는(pairwise disjoint) 빈칸 캐리어 쌍**을 가진 2브릿지 체인이 존재하면 상대 차례라도 **100% 수학적 필승**입니다.

- **루트 VC Win (`find_vc_win_move`)**: 합법 수 중 서로소 캐리어 VC 승리를 만드는 수를 찾고, 캐리어 개수가 최소인 수를 선택해 물리적 완성까지 단조 수렴합니다(MoHex 3 77수 대국의 71~77수 `0.00초` 4연속 필승 마무리).
- **루트 VC Mustplay (`compute_vc_mustplay`)**: 상대의 모든 1수 VC 위협 집합 $\{m\} \cup C(m)$의 교집합을 구해, 교집합 바깥의 패착 수를 루트에서 즉시 차단합니다(Pondering 트리를 리셋하지 않고 `NODE_PROVEN_WIN` 마킹으로 자연 프루닝).
- **트리 내부 VC Solver**: `depth <= 3 || empty_count <= 32`에서 실행해 물리적 연결 10~15플라이 전에 필승/필패를 전파합니다.
- **전수 건전성 증명**: `--self-test`에서 3×3 전체 **19,683개 보드**에 대해 독립 미니맥스 오라클과 전수 대조하여 **오탐 0건**을 검증합니다.

## 5. CPU 자가대국 6링 패턴 학습 & 파이 룰 캘리브레이션

- **6링 패턴**: 10,547개 순수 CPU 자가대국 수에서 216개 4방향 대칭 6이웃 패턴을 볼록 `L-BFGS-B` Plackett-Luce MLE로 학습(`Val Top-1 49.81%`, `Top-5 71.16%`)하여 깊은 노드 프라이어와 O(1) Boltzmann 롤아웃(`pat_temp = 0.35`)에 반영했습니다.
- **11×11 파이 룰 캘리브레이션**: 실측 50.0% 등고선 스윕으로 `should_swap` 경계와 `0.00초` 내쉬 균형 오프닝 북(`h2, i2, d10, c10, e3, g9, f3, f9, j4, b8`)을 정밀 보정해, 선공 1수 중앙 스왑 손실과 초반 12.5초 낭비를 원천 차단했습니다.
