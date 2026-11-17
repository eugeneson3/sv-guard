# SV-Guard 로드맵: 다음에 할 일

> 마지막 갱신: 2026-10-08 · 기준: Step 4 완료 시점 (테스트 509개 통과)
> 진행 원칙: 한 번에 한 단계만, 사용자가 "step N 진행해"라고 할 때 시작한다.

## 1. 지금까지 끝난 것

| 단계 | 내용 | 커밋 |
|---|---|---|
| Step 0–1 | 환경 확인, 엔진 코어(pyslang 래퍼), `svguard check` CLI | `9a59661` |
| Step 2 | IDE 셸: 파일 트리, 탭 에디터, SV 문법 강조, settings.yaml | `2f447d7` |
| Step 2.5–2.6 | vimcore V1(순수 Python), 한글 IME 처리, 커맨드 팔레트, leader 키, keymap.yaml, `<C-w>` 패널 이동 | `2b51c5b` |
| Step 3 | 세션 복원: 폴더·탭·커서·스크롤·창 배치·vim 레지스터/기록 | `19759df` |
| (보완) | FSM 상태 누락(CaseEnum) 검출, 팔레트 바깥 클릭 시 닫힘 | `5a6fe3d` |
| Step 4 | 저장 시 검사: 별도 워커 프로세스, 밑줄·거터·상태줄, Problems 패널, stale 표시, `]d` `[d` `]e` `[e` | `ebb9727` |
| (보완) | 실수 예제 mistake01~10을 `examples/basic`에 추가 | `d5d45c5` |
| (보완) | 원클릭 설치 `setup.bat`: Python 자동 설치(winget, 사용자 범위), 바탕화면 아이콘, 한국어 안내. PySide6 → PySide6-Essentials(설치 670MB → 215MB) | 이번 커밋 |

## 2. 남은 단계 (명세 10장 순서)

### Step 5 — 규칙 프레임워크 + 정확성 규칙 + ExplainPanel ← 다음 차례

- [ ] `svguard/rules/base.py`: `Rule` 베이스와 자동 등록 레지스트리, `AnalysisContext`(Step 1의 `ParsedDesign` 위에 구성)
- [ ] **slang 매핑 규칙**(Step 0 합의: 하이브리드): slang 진단을 우리 규칙 ID와 설명 문서로 연결
  - [ ] SVG-C001 래치 추론 ← `InferredLatch`
  - [ ] SVG-C003 미연결 포트 ← `EmptyInputPortConn`, `UnconnectedInputPort`
  - [ ] 다중 드라이버 ← `MultipleAlwaysAssigns`, FSM 상태 누락 ← `CaseEnum`, 포트 폭 불일치 ← `PortWidthExpand/Truncate` (ID 부여)
- [ ] **AST 자체 규칙**(slang이 안 잡는 것)
  - [ ] SVG-C002 `always_ff` 안의 blocking `=` (Step 0에서 AST 프로토타입 확인함)
  - [ ] `always_comb` 안의 nonblocking `<=`
  - [ ] 한 블록 안의 `=` / `<=` 혼용 (`always @(posedge ...)` 포함)
- [ ] `svguard/explain/<rule_id>.md` 한국어 설명: 왜 문제인지, 짧은 예제, 고치는 법
- [ ] ExplainPanel(`<Space>x`): Problems 패널이나 커서 위치의 진단을 설명으로 표시하고, 키보드로 조작
- [ ] 규칙마다 `tests/rules/<rule_id>/{bad_*.sv, good_*.sv, test_*.py}`
- [ ] 완료 기준: `examples/basic`의 mistake03·04·05가 잡히고, 10번(정답 코드)에서는 아무것도 나오지 않음

### Step 6 — 설정 파일 + 스타일 규칙 + SettingsDialog

- [ ] 프로젝트 루트의 `.svguard.yaml`: `preset`, `exclude`, `rules.<ID>.enabled/params`. 이 값을 `AnalysisRequest`(exclude, include_dirs, defines, uvm_home)에 연결
- [ ] 프리셋 `presets/default.yaml`, `presets/strict.yaml`
- [ ] 스타일 규칙 SVG-S### (포트 접미사, active-low 표기 등): 설정으로 켜고 끄기. 정확성 규칙은 끌 수 없음
- [ ] SettingsDialog: 규칙 체크박스와 yaml을 양방향으로 동기화, 키보드만으로 조작, Esc로 닫기
- [ ] 에디터 설정도 GUI 탭으로 제공하고, 프로젝트별 `editor:` 덮어쓰기 지원 (Step 2에서 약속한 항목)

### Step 7 — UVM 구조 규칙 + 스캐폴딩

- [ ] SVG-U###: `super.new()`·`super.build_phase()` 호출 누락, `uvm_component_utils`/`uvm_object_utils` 누락, `run_phase`에 `raise_objection` 없음
- [ ] (후반) `uvm_config_db` set/get 불일치
- [ ] agent/driver/monitor/sequencer/env/test 생성 마법사 (키보드로 조작)
- [ ] 참고: `practice2.sv`(UVM 연습 파일, 예전 PC에만 있음)를 실전 테스트로 활용

### Step 8 — xsim 연동

- [ ] `svguard/backends/sim_base.py` 인터페이스, `xsim.py` (Vivado 2020.2: `xvlog`/`xelab`/`xsim`, 이 PC의 PATH에 있음)
- [ ] SimService(QProcess), OutputPanel(vim 키 조작), `UVM_ERROR`/`UVM_FATAL` 요약, 로그 줄 → 소스 위치로 점프
- [ ] UVM 컴포넌트 트리 복원
- [ ] 선택: Icarus(`iverilog`가 이 PC에 있음) 백엔드

### Step 9 — 파형 뷰어

- [ ] VCD 파싱, 신호 선택, 확대/축소, 커서. 모든 조작을 키보드로 (`h`/`l` 시간 이동, `+`/`-` 확대 등)

### Step 10 — 관습 추론(infer)

- [ ] 포트 접미사, active-low 표기, 리셋 방식의 지배 비율과 근거 표시, 외부 코드 제외, 표본이 부족하면 비활성
- [ ] 추론 결과를 SettingsDialog 체크박스에 미리 채우고 사용자가 확정

### Step 11 — Yosys 합성 + RTL 뷰어

- [ ] **이 PC에 Yosys가 없음**: OSS CAD Suite 설치 여부부터 결정 (yosys-slang 포함)
- [ ] 합성 리포트 파싱, RTL 뷰어(Yosys JSON → elkjs/SVG 또는 Graphviz), 미연결 포트/신호 강조, XDC 핀 검사

### Step 12 — vimcore V2/V3 (중간에 앞당겨도 됨)

- [ ] **텍스트 오브젝트** `iw aw i" a" i( a( i{ a{ i[ a[ ip ap`: `ciw`, `di(`는 자주 쓰니 먼저 당길 후보
- [ ] Visual-Block(`<C-v>`, 블록 `I`/`A`), 매크로 `q`/`@`/`@@`, 마크 `m`/`` ` ``/`'`, 점프 리스트 `<C-o>`/`<C-i>`
- [ ] `:s` / `:%s` / 범위 / `:g` 일부, `*` `#` `~` `J` `r` `R` `<C-a>` `<C-x>`
- [ ] SV 키워드 쌍 `%` (begin/end, module/endmodule, …), SV 텍스트 오브젝트 `im` `ic` `ib` `ia`
- [ ] `gd`(선언으로 이동) / `gr`(참조 목록): 엔진의 심볼 정보 활용
- [ ] 세션 복원에 마크 추가 (Step 3에서 "선택"으로 남긴 항목)

## 3. 진행 중에 미뤄 둔 것

| 항목 | 메모 |
|---|---|
| 분할 화면 `<C-w>v` / `<C-w>s` | 명세 8-2. EditorTabs를 분할 가능한 구조로 바꾸는 작업이 필요 |
| 프로젝트 전체 텍스트 검색(grep) 패널 | 명세 8-2. Problems 패널과 같은 하단 패널 형태로 |
| `:w 경로`(다른 이름으로 저장), `:e 새파일` | 지금은 "not supported yet" 메시지만 나옴 |
| 파일 트리에서 파일 만들기·이름 바꾸기·삭제 | 키보드 조작(`a`, `r`, `d`)으로 |
| 검색 결과 강조(hlsearch) | `:noh`는 받기만 하고 아무 일도 하지 않음 |
| 디스크의 파일이 바깥에서 바뀌었을 때 | 다시 읽을지 묻기 (QFileSystemWatcher) |
| 파일 트리 펼침 상태 복원 | 세션 복원 범위 밖으로 남겨 둠 |
| leader 안내 팝업(which-key) | `<Space>`를 누르고 기다리면 다음 키 목록 표시 |
| 오래 걸리는 검사 취소 / 시간 제한 | 지금은 최신 요청 하나만 대기열에 남기는 방식만 있음 |
| README 마무리 | 탐지 화면 GIF, 아키텍처 그림, 키 치트시트 정리 (명세 12장 품질 기준) |
| 설치 파일(.exe) 배포 | 지금은 소스 폴더를 받아 setup.bat 실행. PyInstaller + Inno Setup으로 `SV-Guard-Setup.exe`를 GitHub Releases에 올리면 폴더를 지울 걱정도 없음. 서명이 없으면 SmartScreen 경고("추가 정보 → 실행") |

## 4. 확인이 필요한 것

- [ ] **실제 Windows 한글 입력기**: Normal 모드에서 `j`/`k`/`dd`가 바로 동작하는지, Insert로 돌아갈 때 한글 상태가 유지되는지. 자동 테스트로는 OS 입력기를 흉내 낼 수 없음
- [ ] **GitHub Actions CI 결과**: `gh` CLI가 없어서 확인하지 못함 → 저장소 Actions 탭에서 확인 (Ubuntu·Windows × Python 3.11·3.13)
- [ ] **Linux(Ubuntu) 실행**: 지금은 CI로만 검증. 실제 GUI와 ibus/fcitx 한글 입력은 미확인
- [ ] Step 4 체크리스트: 저장 → 밑줄·패널, 편집 → 회색(stale), `]d` 이동, 검사 중에도 타이핑이 끊기지 않는지

## 5. 테스트용 자료

- `examples/basic/mistake01~10*.sv`: 흔한 실수 예시 (각 파일 맨 위 주석에 설명). 저장소에 있으므로 어느 PC에서든 `python tasks.py check`로 확인
  - 지금 잡힘: 01·02 래치, 06 다중 드라이버, 07 미연결 포트, 08 폭 불일치, 09 FSM 상태 누락
  - Step 5에서 잡을 것: 03 `always_ff`의 `=`, 04 `always_comb`의 `<=`, 05 `=`/`<=` 혼용
  - 10번은 정답 코드: 어떤 단계에서도 아무것도 나오면 안 됨
- `practice2.sv`, `tb_counter.sv`는 사용자의 연습 파일 (수정하지 않음). 저장소에는 없고 예전 PC의 `C:\Users\kccistc\Desktop\새 폴더`에만 있음
