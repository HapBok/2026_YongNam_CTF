# 돌아와서 실행할 순서

처음 CLI를 사용하는 경우 [CLI 시작과 운영 매뉴얼](cli-manual-ko.md)을 먼저 읽으세요. PowerShell과 Ubuntu 명령 구분, 별도 모의 환경, 보이는 탭 8개와 실제 모델 실행을 순서대로 안내합니다.

문제별 `challenge.toml`은 [캡처 기반 자동 생성](screenshot-toml-ko.md)을 지원합니다. `make-toml <문제 폴더> --batch` 실행 후 생성 결과를 확인하고 `import-batch <문제 폴더> --skip-existing`으로 등록하세요. 실전용 `scope.toml`은 운영자가 작성합니다.

## 현재 준비된 것

프로젝트 전용 Linux Codex 0.162.1, 기존 계정 로그인 연결, 모델별 Profile, 8 Worker, 취소/교체/복구, 파일 검증과 운영 문서가 준비되어 있습니다. 전역 Windows Codex 0.144.1은 유지했습니다. NTFS의 Flag 파일은 현재 사용자·SYSTEM·관리자 ACL로 보호합니다.

## 실전 전에 입력할 것

config/scope.example.toml을 config/scope.toml로 복사하고 공식 규정, 정확한 날짜/시간, Challenge ID, 대상 hostname/IP/port와 허용 동작을 기입합니다. authorized는 확인한 뒤에만 true로 바꿉니다. 실제 대회 정보는 임의로 채우지 않았습니다.

WSL Ubuntu에서:

```bash
cd '/mnt/c/Users/happy/Ready_Google/CTF/2026_영남권 CTF/Agent Engineering'
python3 ctfctl.py init-run
python3 scripts/acceptance.py --repeat 3
python3 ctfctl.py doctor --live
python3 ctfctl.py import '/문제/파일/경로' --id c001 --title '문제명' --description '문제 설명'
```

PowerShell에서:

```powershell
& 'C:\Users\happy\Ready_Google\CTF\2026_영남권 CTF\Agent Engineering\scripts\launch-8.ps1'
```

문제들을 먼저 여러 개 import 또는 import-batch로 넣으면 8개 슬롯이 자동 분배됩니다. 추가 import도 실행 중 가능합니다. 한 문제가 끝나면 다음 단계나 새 문제가 빈 슬롯에 들어갑니다.

## 팀원이 먼저 Solve했을 때

```bash
python3 ctfctl.py solved c001 --by team
```

해당 Worker의 첫 Ctrl+C도 현재 문제를 일시중단하고 다음 문제를 받습니다. 5초 안에 다시 누르면 강제중단/dirty 처리합니다. Flag 제출은 항상 직접 합니다.

## 실제 모델 사용 없이 다시 시험할 때

```bash
python3 scripts/rehearse.py
```

실제 모델 시험과 리허설 결과는 reports/에 있습니다. Mock은 실제 CTF 난이도나 13문제 Solve를 보장하는 자료가 아닙니다.
