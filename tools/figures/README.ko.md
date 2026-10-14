# 그림 재생성

[English](README.md) | **한국어**

이 선택 도구는 공개한 실제 측정값을 Matplotlib으로 그립니다. 고정한 시각화 환경은 Python 3.11 이상이 필요하며, 표준 라이브러리만 사용하는 에이전트 실행 환경은 Python 3.10 이상과 C++17 컴파일러를 사용합니다.

저장소 루트에서 별도의 환경을 만듭니다.

```bash
python -m venv .local/figure-env
.local/figure-env/bin/python -m pip install -r tools/figures/requirements.txt
.local/figure-env/bin/python tools/figures/render_hex_deep_scientific.py --data assets/figures/deep-visual-input.json --output .local/figures --language both
.local/figure-env/bin/python tools/figures/render_hex_thumbnail.py --data assets/figures/deep-visual-input.json --output .local/figures --language both
```

Windows에서는 `.local/figure-env/bin/python` 대신 `.local/figure-env/Scripts/python.exe`를 사용합니다.

공개한 입력은 저장소 기준 상대 경로와 원시 SHA-256으로 실제 집계, 비용 매핑, 워커 측정 및 썸네일 경기 하나를 연결합니다. `reports/deep/**`는 Git에서도 CRLF가 있는 보고서를 포함한 측정 당시의 바이트를 보존합니다. 기록이 바뀌면 입력 검사를 통과하지 못합니다. 렌더링은 새 출력 폴더에 그림을 저장하며, 경기를 다시 실행하거나 엔진, 선정 정책, 평가 설정 및 원시 기록을 수정하지 않습니다.

출력 폴더 `en/`과 `ko/`에는 `hex-shared-time.svg`, `hex-tactical-ablation.svg`, `hex-worker-positions.svg`, `hex-deep-thumbnail.svg`가 생성됩니다. 영어 기본 그림은 `assets/figures/`, 한국어 그림은 `assets/figures/ko/`에 있습니다. `assets/figures/deep-figure-manifest.json`에 새 그림과 생성 코드, 입력 및 글꼴의 해시를 기록합니다. 기존 SVG 일곱 개는 수치와 형상을 보존한 별도의 이전 평가 자료입니다.

공유 시간 그림은 실제 상대 식별자로 선정 정책의 승률을 대응합니다. 구간은 기록된 장비 및 어댑터 조건 안에서 완결된 선후공 교대 쌍을 재추출한 값입니다. 참가자별 300초는 시간 상한이며 실제 소비 시간을 의미하지 않습니다. 완료 경기, 실행 실패와 미기록 경기의 분모는 구분합니다. 전술 그림의 50–50% 구간은 관측한 쌍의 점수가 모두 같아 생긴 결과이며 두 정책의 동등함을 입증하지 않습니다. 워커 그림은 Windows와 Kaggle의 요청 중앙값, 7회 반복의 기술 통계인 p95 및 네이티브 프로세스 RSS를 각각 표시하며 승률을 나타내지 않습니다. 보드 세 개는 합법적인 적색 선공 수순을 재생했고, 나머지 세 개는 전치와 색 교환을 적용한 비종료 정적 상태입니다. 정적 상태의 적색 선공 경기 도달 가능성은 주장하지 않습니다.

썸네일은 실제 종료 보드와 기록된 승리 색상의 연결 경로를 확인하며, 같은 집계에서 승률 막대를 읽습니다. 보드와 수치를 예시로 만들지 않습니다.

영어는 DejaVu Sans를 사용합니다. 한국어는 맑은 고딕, Noto Sans CJK 또는 NanumGothic이 필요합니다. 글꼴이 자동으로 검색되지 않으면 두 렌더러에 `--korean-font PATH_TO_FONT_FILE`을 추가합니다. 글자는 SVG 경로로 저장하며 글꼴 파일은 배포하지 않습니다. 생성 영수증에 정확한 글꼴 해시, Matplotlib 버전, 입력 해시와 글자의 캔버스 범위 검사 결과를 기록합니다. 브라우저 확인은 별도의 시각적 검사입니다.

이미 공개한 기록에서 공유 시간 매핑과 입력 연결을 다시 만들려면 다음 명령을 실행합니다.

```bash
python tools/figures/prepare_hex_visual_inputs.py
```

표준 라이브러리만 사용하는 이 명령은 `reports/deep/analysis/shared-time-metrics.json`, `assets/figures/deep-metric-provenance.json`, `assets/figures/deep-visual-input.json`을 생성합니다. 고정된 평가 파일을 보존하며 불완전한 평가는 거부하고, 원시 경기 400개의 경로 및 해시를 남깁니다. 그림의 바이트 해시까지 재현하려면 기록된 글꼴과 고정한 시각화 라이브러리도 필요합니다. 다른 지원 글꼴은 측정값을 유지하지만 글자 경로의 바이트를 바꿉니다.
