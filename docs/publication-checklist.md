# Publication Checklist

[한국어](#한국어) | [Documentation](README.md)

Before publishing or promoting this repository:

- confirm that no student IDs, private meeting logs, shell history, credentials, or personal assessment files remain in the working tree;
- obtain agreement from project collaborators on attribution and public release;
- choose a license only after ownership is confirmed;
- run both Python test suites and the C++17 syntax check;
- verify that recorded results remain clearly labeled as individual games rather than aggregate win rates;
- inspect the full Git history, not only the current files.

Important: sensitive files removed from the current tree can still exist in earlier commits. The safest publication path is to create a new clean repository from the reviewed working tree. Rewriting the existing history with `git filter-repo` is another option, but it changes commit IDs and requires coordination with every collaborator and remote clone.

## 한국어

저장소를 공개하거나 포트폴리오에 연결하기 전에 다음을 확인하세요.

- 현재 파일에 학번, 비공개 회의 기록, 셸 히스토리, 인증정보, 개인 평가 자료가 없는지 확인합니다.
- 팀원과 기여 표기 및 공개 범위를 합의합니다.
- 소유권을 확인한 뒤 라이선스를 선택합니다.
- 두 Python 테스트 스위트와 C++17 구문 검사를 실행합니다.
- 기록 결과가 전체 승률이 아닌 개별 경기라는 점을 유지합니다.
- 현재 파일뿐 아니라 전체 Git 이력을 검사합니다.

현재 트리에서 제거한 민감 파일도 과거 커밋에는 남아 있을 수 있습니다. 검토된 현재 파일로 새 저장소를 만드는 방법이 가장 안전합니다. `git filter-repo`로 기존 이력을 다시 작성할 수도 있지만 커밋 ID가 바뀌므로 모든 팀원 및 원격 복제본과의 조율이 필요합니다.
