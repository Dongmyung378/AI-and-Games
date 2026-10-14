# 소스 빌드와 공개 CPU 실행 검증

**한국어** | [English](deep-runtime.md) | [프로젝트 개요](../README.ko.md)

개선한 Hex 에이전트와 기존 알고리즘의 비교용 어댑터는 Windows, Linux 또는 WSL에서 소스로 빌드할 수 있습니다. 두 구현 모두 CPU로 탐색하며 Python 3.10 이상과 C++17 컴파일러가 필요합니다. Python 실행부는 표준 라이브러리를 사용하므로 GPU나 Docker, 학습된 체크포인트가 필요하지 않습니다.

## 두 엔진 빌드

저장소 최상위 폴더에서 다음 명령을 실행합니다.

~~~bash
python -m hexai doctor
python -m hexai build
python scripts/build_legacy_benchmark.py
python -m unittest discover -s tests -v
~~~

doctor 결과의 컴파일러 항목을 확인하고 실제 빌드 성공으로 실행 준비 상태를 판단합니다. 컴파일러를 직접 지정할 수도 있습니다.

~~~bash
python -m hexai build --compiler clang++
python scripts/build_legacy_benchmark.py --compiler clang++
~~~

개선 엔진의 실행 파일은 Windows에서 .local/bin/hex_search.exe, Linux에서 .local/bin/hex_search에 저장됩니다. 기존 알고리즘 어댑터는 모든 환경에서 평가 설정에 명시된 .local/bin/legacy_benchmark를 사용합니다. Windows에서는 확장자가 없어도 PE 실행 파일입니다. 빌더가 임시 .exe 경로에 컴파일한 뒤 정확히 요청한 이름으로 설치하며, Windows CreateProcess로 실제 실행되는지 검증했습니다. 사용자가 .exe 경로를 직접 지정하는 방식도 지원합니다.

두 빌더는 소스, 컴파일러와 실행 파일의 해시를 기록합니다. 비교용 어댑터에는 생성된 C++ 소스와 변경 내역도 함께 저장됩니다. 파일명 처리를 고친 부분은 빌드 계층에 한정되며, 기존 알고리즘의 생성 소스 해시는 f42ab37e1893ba2bf0ac1eb212381803c95132b68d7e2a18a085d46ab240291e로 유지됩니다. 수정 전 빌더도 reports/deep/source/build_legacy_benchmark.frozen.py에 보존했습니다.

## 빠른 통합 실행 확인

~~~bash
python -m hexai evaluate --config configs/deep/public-runtime-smoke.json --output .local/public-runtime-smoke
python -m hexai aggregate --inputs .local/public-runtime-smoke --output .local/public-runtime-summary.json --require-complete
~~~

이 설정은 각 참가자에게 워커 1개와 외부에서 측정하는 판단 시간 5초를 부여하고, 선후공을 교대한 4경기를 실행합니다. 기존 알고리즘 어댑터와 대국하면서 V3 시간 예산 전달과 실행 경로를 확인하는 용도입니다. 4경기가 모두 완료되고 실패와 누락이 없는지 확인합니다. 이 결과는 통합 실행의 근거이며, 대국 4개만으로 경쟁력을 추정하지 않습니다.

## Kaggle CPU 패키지

~~~bash
python scripts/package_kaggle_cpu.py --owner YOUR_KAGGLE_USER --slug hex-public-runtime --config configs/deep/public-runtime-smoke.json --output .local/kaggle-public-runtime --sanitizers
~~~

이 명령은 패키지를 준비하며 노트북을 제출하지 않습니다. kernel.py, kernel-metadata.json, source-inventory.json과 package-receipt.json을 생성합니다. 실행 설정은 비공개 CPU 스크립트이며 GPU, TPU와 인터넷을 끕니다. 검토한 소스, 테스트와 고정 평가 설정 하나만 포함하고, 인증정보나 모델 가중치, 기존 실행 파일은 넣지 않습니다. 출력 폴더에 파일이 있으면 덮어쓰지 않고 중단합니다.

생성된 스크립트를 본인의 Kaggle 계정으로 실행합니다. 스크립트는 압축 파일과 개별 소스의 SHA-256을 확인한 뒤 두 엔진을 컴파일하고, 유지 관리 테스트와 보존한 심판 및 어댑터 테스트를 실행합니다. 이후 고정 설정의 대국을 진행합니다. --sanitizers를 지정하면 두 엔진의 AddressSanitizer와 UndefinedBehaviorSanitizer 검증도 수행합니다.

다음 두 파일을 최상위 출력에 제공하므로 하위 폴더 다운로드 지원 여부에 의존하지 않습니다.

| 파일 | 내용 |
| --- | --- |
| hex-public-cpu-results.zip | 로그, 소스 목록, 빌드 기록, 생성된 어댑터 소스, sanitizer 결과와 경기 기록 |
| hex-public-cpu-completion.json | 완료 상태, 평가 설정 해시, 소스 해시와 결과 ZIP 해시 |

실행 시간이 제한된 패키저는 --max-wall-seconds 33000과 --checkpoint-margin-seconds 120을 기본값으로 사용합니다. 빌드와 테스트 시간을 뺀 뒤 평가에 남은 실행 시간을 전달합니다. 경기 사이에서 중단하면 완료한 기록을 같은 최상위 ZIP으로 저장합니다. 상태는 배정된 묶음에 한정합니다. complete는 해당 묶음이 성공적으로 끝났다는 뜻이고, completed_with_failures는 실패한 경기를 유지하며, checkpointed에는 남은 경기와 부분 선후공 쌍을 표시합니다. 전체 400경기 중 40경기만 기록한 결과를 400경기 완료로 표시하지 않습니다.

공통 시간 예산 400경기는 선후공 한 쌍을 유지한 10개 묶음으로 나눕니다. 각 묶음은 40경기와 20쌍입니다. 첫 번째 묶음의 준비 명령은 다음과 같습니다.

~~~bash
python scripts/package_kaggle_cpu.py --owner YOUR_KAGGLE_USER --slug hex-shared-time-cpu-shard-00 --config configs/deep/shared-time.json --output .local/kaggle-shared-time-00 --shard-index 0 --shard-count 10 --max-wall-seconds 33000 --checkpoint-margin-seconds 120 --sanitizers
~~~

나머지는 인덱스 1부터 9까지 사용하고, 작업 이름과 출력 폴더를 각각 다르게 지정합니다. 경기당 두 참가자의 300초 상한을 합하면 40경기의 판단 시간 상한은 24,000초입니다. 빌드와 프로세스 관리, 출력 저장에는 별도 시간이 필요합니다. 400경기 전체를 노트북 하나에서 실행하지 않습니다. 실제 작업별 폴더를 분리하고 중단된 기록을 보존하며, 같은 실행에서 끝난 완전한 선후공 쌍을 집계합니다. 다른 작업의 후반 경기를 옮겨 중단된 한 쌍을 완성한 것처럼 처리하지 않습니다.

실행 시간 제한을 추가한 패키징은 로컬 검증과 별도의 실제 Kaggle 체크포인트 실행으로 확인했습니다. 로컬에서는 최상위 ZIP 저장, 배정 범위와 전체 범위의 완료 판정, 400경기의 10개 묶음 배분을 검증했습니다. Kaggle 체크포인트 작업은 소스 빌드와 테스트를 마친 뒤 평가 대국의 참가자 프로세스를 시작하기 전에 멈췄으며, 결과 ZIP도 저장했습니다. 기록된 대국이 0개인 이 작업은 체크포인트 동작의 근거이며 경기력 집계에서 제외합니다. 400경기를 완료한 결과로 표현하지 않습니다.

결과 ZIP의 build-evidence/legacy_benchmark.cpp와 빌드 및 변경 기록은 실제 비교에 사용한 어댑터 소스를 확인하는 근거입니다. 원본 어댑터 테스트용 실행 파일도 별도의 임시 환경에서 원본 소스로 빌드하고 과거 소스 해시와 대조합니다. 이를 기존에 배포한 원본 실행 파일 자체를 검증한 것으로 표현하지 않습니다.

## 실제 검증 범위

시간 제한 기능을 포함한 최신 공개 도구 v3를 서로 다른 Kaggle CPU 작업 두 개에서 실행했습니다. 두 작업 각각 유지 관리 테스트 64개, 보존한 심판 테스트 18개, 어댑터 및 심판 테스트 25개를 실행해 총 107개가 통과했으며 건너뛴 테스트는 없었습니다. 각 작업의 C++ 자체 검증도 15개 항목을 통과했고, 3×3 보드의 색 배치 19,683개를 독립적인 연결 판정과 대조했습니다. ASan과 UBSan을 적용한 네이티브 프로토콜 테스트 6개도 각각 통과했습니다. 반복한 검증은 해당 작업이 실제로 사용한 소스 압축 파일에 연결해 기록합니다.

| 최신 v3 실제 실행 | 평가 설정과 배정 범위 | 기록된 평가 대국 | 결과 |
| --- | --- | ---: | --- |
| 통합 실행 확인 | 4경기, 선후공 2쌍 | 4 | 모두 정상 완료했으며 저장한 100수를 재생 검증 |
| 체크포인트 전용 | 전체 400경기의 10개 묶음 중 첫 번째에 40경기와 20쌍 배정 | 0 | 첫 평가 대국 전에 checkpointed로 중단했으며 배정한 40경기는 모두 미실행 |

통합 확인 작업은 기본 실행 시간 33,000초와 중단 여유 120초를 사용했습니다. 빌드와 테스트에 쓴 시간을 뺀 뒤 평가에는 32,931.367초가 전달됐습니다. 체크포인트 작업은 의도적으로 실행 시간 1초와 여유 0초를 지정했습니다. 소스 빌드와 테스트를 마친 뒤 평가에는 최소값인 0.001초가 전달됐고, 평가기가 첫 경기의 예상 최대 시간 600초를 확보할 수 없어 결과 ZIP을 저장하고 멈췄습니다. 전체 작업이 1초 안에 끝나는지 확인한 실험은 아닙니다. 단위 및 프로토콜 테스트에서는 네이티브 프로세스를 실행했지만 평가 대국의 참가자 프로세스는 시작하지 않았습니다. 기록된 경기가 0개인 체크포인트 결과를 완료된 경기 실험으로 표시하거나 경기력 집계에 더하지 않습니다.

최신 두 작업은 Linux x86_64, Python 3.13.15와 g++ 13.3.0을 사용했습니다. 보이는 CPU와 프로세스에 허용된 CPU가 각각 4개였고 cpu.max=400000 100000으로 CPU 4개 분량의 시간 할당을 확인했습니다. 포함한 소스 목록과 생성된 기존 알고리즘 소스, 빌드 기록과 결과 ZIP은 고정 해시로 대조했습니다. Windows 파일명 수정은 실제 빌드와 프로세스 실행 테스트 5개로 별도 검증했으며 생성된 알고리즘 소스 해시를 유지했습니다.

과거 검증 기록도 구분해 보존합니다. 최초 공개 도구 v1은 Python 테스트 96개와 4경기 98수, v2b는 Python 테스트 103개와 4경기 92수를 검증했습니다. 해당 결과를 최신 v3 소스의 검증으로 바꾸거나 최신 통합 경기 4개에 더해 집계하지 않습니다.

컴파일러와 표준 라이브러리, 장비가 바뀌면 실행 파일의 바이트와 확률적 탐색 경로가 달라질 수 있습니다. 소스 및 실행 파일 해시, 난수 시드, 워커 수와 예산을 기록해 비교 조건을 확인할 수 있게 합니다. 시간 제한 기반 실행은 같은 설정이라도 시뮬레이션 횟수가 달라질 수 있습니다.

## 고정된 확장 실험

~~~bash
python -m hexai evaluate --config configs/deep/shared-time.json --output .local/deep-shared-time --max-wall-seconds 39600 --checkpoint-margin-seconds 120
python -m hexai evaluate --config configs/deep/tactical-ablation.json --output .local/deep-tactical-ablation
~~~

전체 실행 시간 제한은 경기 사이에서 중단해 완료한 경기 파일을 보존합니다. 공통 시간 예산 설정은 참가자마다 외부에서 측정하는 300초 상한을 적용합니다. 이는 사용할 수 있는 시간이며 모든 참가자가 매 경기 300초를 소비했다는 의미는 아닙니다.

--resume은 평가 설정, 실행 파일과 기록한 환경이 동일할 때만 사용합니다. 로컬과 Kaggle을 병행할 때는 --shard-index와 --shard-count로 선후공 한 쌍을 통째로 배분하고, 중복이 없는 결과를 aggregate로 합칩니다. 환경별 처리 시간과 장비 정보도 따로 제공합니다. 중단되거나 누락된 실험을 최종 성능 결과로 간주하지 않습니다.

자원 할당 해시는 물리적 장비를 고유하게 식별하지 않습니다. 실제 작업마다 실행 폴더와 선후공 한 쌍의 출처를 보존합니다. 서로 다른 두 작업의 CPU와 빌드 정보가 같더라도, 공개 검증기는 한 쌍의 두 경기가 같은 실행 폴더에 있어야 통과시킵니다.

## 저장된 근거 검증

~~~bash
python scripts/verify_release.py --output .local/release-verification.json
~~~

reports/release-manifest-v2.json이 있으면 해당 목록을 사용합니다. 파일 해시와 원본 64개 파일, 등록된 평가 설정과 경기 기록, 집계 결과의 일치 여부를 확인합니다. 기존 6개 실험은 그대로 유지하고, 당시 엔진과 실행부 소스를 담은 reports/historical/release-v1-source.zip으로 검증합니다. 저장된 수의 재생은 규칙과 기록된 승자를 확인하는 절차이며, 탐색을 다시 수행하거나 일반적인 Hex 경쟁력을 입증하는 절차는 아닙니다.
