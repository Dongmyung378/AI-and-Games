"""Translate the linked fixed-iteration figure, preserving all plotted geometry.

python tools/figures/localize_final_policy.py

The Korean source and historical figure receipts are left unchanged. Only the
English derivative used by README.md is written; no games are replayed or run.
"""
from pathlib import Path
import hashlib
import json
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
TRANSLATIONS = {
 '새 시드의 최종 정책 평가':'Final policy evaluation on held-out seeds',
 '개발 자료로 고정한 RAVE-TS를 세 정책과 통계 미갱신 진단용 제어에 비교합니다. 완결된 선후공 교대 쌍의 점수와 95% 부트스트랩 구간 및 완료 경기의 승패를 표시합니다. 실패는 승리로 계산하지 않습니다. 내부 상대와 명시한 CPU 예산 범위의 결과입니다.':'RAVE-TS fixed on development data is compared with three policies and an update-disabled diagnostic control. Scores and 95% bootstrap intervals use complete alternating pairs; wins and losses use completed games. Failures are not wins. Results apply to the declared internal opponents and CPU budgets.',
 '개발 자료로 선택한 RAVE-TS, 수당 전체 16,000회, 워커 2개, 11×11 보드':'Development-selected RAVE-TS, 16,000 simulations per move, 2 workers, 11×11 board',
 '완료 256 / 계획 256경기, 완결 128쌍, 실패 0건':'256 / 256 games, 128 complete pairs, 0 failures',
 '집계 완료':'Complete', '선택 정책의 내부 상대':'Internal opponents', '승 / 패, 95% 구간':'Wins / losses, 95% interval',
 '완결 32쌍, 실패 0건':'32 pairs, 0 failures', '톰슨 샘플링':'Thompson sampling',
 '통계 미갱신 제어':'No-update control', '점수 (%)':'Score (%)', '실행 조건과 장비':'Execution conditions and hardware',
 '노드 상한 100,000, 경기 300초, 응답 제한 60초':'Node cap 100,000, game budget 300 seconds, response limit 60 seconds',
 '로컬 Windows, 16 논리 CPU, 완료 128 / 기록 128경기':'Local Windows, 16 logical CPUs, completed 128 / recorded 128 games',
 'Kaggle Linux, 4 vCPU 할당, 완료 128 / 기록 128경기':'Kaggle Linux, 4 allocated vCPUs, completed 128 / recorded 128 games',
 '점수와 구간은 완결된 교대 쌍, 승패는 완료 경기 기준입니다. 실패를 승리로 계산하지 않습니다.':'Scores and intervals use complete alternating pairs; wins/losses use completed games. Failures are not wins.',
 '모든 쌍에서 승리해 100–100% 구간이 나와도 앞으로의 100% 승리를 보장하지 않습니다.':'A 100–100% interval after winning every pair does not guarantee 100% future wins.',
 '통계 미갱신 제어는 같은 수정 엔진의 진단 조건입니다. 실제 과거 실행 파일과 별도 시간 기준 비교를 구분합니다.':'The control disables updates in the same corrected engine; original binaries and separate time budgets differ.',
 '외부 Davis와 HexHex의 승률이나 전체 Hex 에이전트 순위를 뜻하지 않습니다. 새로운 시드는 새 시작 좌표를 보장하지 않습니다.':'Not Davis/HexHex win rates or an overall Hex ranking. New seeds may reuse opening coordinates.',
}

def main():
    source=ROOT/'assets/figures/ko/hex-final.svg'
    target=ROOT/'assets/figures/en/hex-final.svg'
    tree=ET.parse(source)
    for element in tree.getroot().iter():
        if element.tag.rsplit('}',1)[-1] in {'title','desc','text'} and element.text:
            if re.search('[가-힣]',element.text) and element.text not in TRANSLATIONS:
                raise ValueError('Untranslated text: '+element.text)
            element.text=TRANSLATIONS.get(element.text,element.text)
    tree.getroot().set('lang','en')
    target.parent.mkdir(parents=True,exist_ok=True)
    tree.write(target,encoding='utf-8',xml_declaration=True)
    receipt={'source':source.relative_to(ROOT).as_posix(),'target':target.relative_to(ROOT).as_posix(),
      'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'target_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
      'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'scope':'English labels only; all original numerical values, drawn shapes and historical receipts are preserved.'}
    (target.parent/'localization.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))

if __name__=='__main__': main()
