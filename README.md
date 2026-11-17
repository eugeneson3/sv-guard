# SV-Guard 검증 지원 IDE

SystemVerilog 파일 저장 시 pyslang 검사를 실행하고, 오류 위치와 진단 내용을 편집기 및 Problems 패널에 표시하는 도구입니다.

- 수행 시기 2026.11 기준
- 참여 형태 개인
- 담당 범위 SystemVerilog 검사 흐름, 진단 표시 및 편집기 기능 구성

[포트폴리오 상세 페이지](https://eugeneson3.github.io/projects/sv-guard/)

## 프로젝트 목표

SystemVerilog 학습 및 RTL 편집 과정에서 저장 후 진단 확인과 오류 위치 이동을 반복할 수 있는 로컬 개발 환경을 구성하는 것을 목표로 하였습니다.

## 설계 및 구현

- 파일 저장 이벤트에서 프로젝트 검사를 실행하고 파일별 진단 정보를 편집기에 반영합니다.
- pyslang 컴파일은 Worker process에서 실행하며, 검사 중 추가 저장 요청은 다음 실행으로 병합합니다.
- 편집 이후 이전 진단을 stale 상태로 표시하고 다음 검사에서 갱신합니다.
- Problems 패널, Vim 키 입력, 명령 팔레트 및 세션 복원을 구성하였습니다.

## Troubleshooting

### 검사 중 편집기 응답성

컴파일 작업 중 편집기 입력과 화면 갱신이 영향을 받을 수 있습니다.

기존 README는 pyslang 컴파일이 Python GIL을 유지하는 점을 설계 근거로 기록하고 있습니다.

검사를 별도 프로세스에서 실행하고 Worker 종료 후 다음 저장에서 재실행하도록 구성하였습니다.

검사 상태와 진단 결과를 GUI 이벤트 흐름에 연결하였습니다.

## 검증 및 결과

- 현재 구현 단계는 저장 시 검사와 진단 표시입니다.
- 저장소에 편집기·검사기 테스트 및 Windows·Ubuntu CI 설정이 포함되어 있습니다.
- 2026.11.18 공개 스냅샷의 기존 테스트를 Windows·Python 3.12·Qt offscreen 환경에서 실행하여 507개 통과, 2개 건너뜀을 확인하였습니다.

## 소스코드 구조

현재 구현 범위와 향후 기능은 원본 README 및 ROADMAP에 기재되어 있습니다. 이번 공개본의 소스는 easySV 작업 폴더를 기준으로 구성하였습니다.

| 경로 | 내용 |
| --- | --- |
| [app/](app/) | PySide6 편집기 및 진단 UI |
| [svguard/](svguard/) | pyslang 검사 및 CLI |
| [vimcore/](vimcore/) | Vim 입력 처리 |
| [tests/](tests/) | 기존 테스트 |
| [pyproject.toml](pyproject.toml) | 의존성 및 실행 진입점 |

## 실행 방법

1. Python 3.11 이상 환경에서 python tasks.py setup으로 가상환경과 의존성을 설치합니다.
2. python tasks.py run으로 GUI를 실행하거나 python tasks.py check로 예제 검사를 수행합니다.
3. python tasks.py test로 기존 테스트를 실행합니다.

## 소스 이력

2026년 11월 18일 로컬 프로젝트에서 구성한 공개 스냅샷입니다. 원본 파일의 상대 경로와 SHA-256은 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)에 기록하였습니다. 빌드 산출물과 로컬 개발 환경은 제외하였습니다. 파일별 저작권 및 라이선스 고지를 유지하였습니다.

기존 프로젝트 설명은 [원본 README](docs/original-readme.md)에 보존하였습니다.
