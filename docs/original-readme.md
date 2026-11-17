# SV-Guard

A desktop IDE for people learning SystemVerilog, UVM and FPGA design. It catches common
mistakes when you save, explains why they are mistakes, and shows how to fix them.
Everything runs locally: no code leaves your machine.

> Status: **Step 4 — check on save**: saving a `.sv` file checks the project in a background
> process and shows the results as squiggles, gutter marks and a Problems panel.

## Requirements

- Python 3.11+ (pyslang 12 requires it)
- Optional: Vivado (its bundled UVM 1.2 is detected automatically for UVM checks)

## Setup

On Windows, one double-click does everything: clone the repository (or download it as a ZIP and
extract it) and run **setup.bat**. It installs Python 3.13 for the current user through winget
if no Python 3.11+ is found (no admin rights needed), creates `.venv`, adds an **SV-Guard** icon
to the desktop and Start menu, and starts the IDE. Its messages are in Korean. On Linux,
`make install` does the same with an app-launcher entry.

The IDE runs from this folder, so keep it in place; the folder path must be 83 characters or
less unless Windows long paths are enabled (PySide6 installs very deep files). The icon starts
the IDE without a console window and always runs the current source tree, so a `git pull` takes
effect on the next start. Run setup.bat again only when dependencies change or the folder moves.

```bash
python tasks.py install    # what setup.bat runs: setup + shortcut
python tasks.py setup      # creates .venv and installs sv-guard[gui,dev]
python tasks.py shortcut   # (re)creates the desktop / Start menu icons
python tasks.py test
python tasks.py check      # runs svguard on examples/basic
```

`make install|setup|test|check` does the same on Linux.

## IDE

```bash
svguard-ide                    # or: python -m app — picks up where you left off
svguard-ide examples/basic     # open a project folder (or a file)
```

### Check on save

Saving a `.sv`/`.svh`/`.v`/`.vh` file (`Ctrl+S`, `:w`, `<Space>w`) checks the open folder; with no
folder open, just that file. `<Space>r` checks on demand. Nothing is checked while you type.

- Findings appear as squiggles with a light tint, a colored bar next to the line number, a tooltip,
  and, in vim mode, the message for the cursor line plus `E<n> W<n>` on the status line.
- Edit after a check and the marks turn grey and dotted ("stale", `E0 W1~`) but keep following the
  text; the next save replaces them.
- **Problems panel** (`<Space>p`, `<C-w>j`): grouped by file. `j`/`k`, `Enter`/`o` to jump, `l`/`h`,
  `gg`/`G`, `/` to filter, `q` to hide.
- `]d` / `[d` jump to the next / previous problem across files, `]e` / `[e` to errors only.

The checker runs in a separate worker process: pyslang holds Python's GIL while compiling, so a
thread would still freeze the editor, and a parser crash cannot take the IDE down (the worker
restarts on the next save). Saving again during a check queues one more run, never a backlog.

### Session restore

Start the IDE and everything is where you left it: the last folder, its open tabs and the active
one, every tab's cursor and scroll position, the window size and panel layout, and vim's registers,
search and `:` history (like vim's viminfo). Each folder keeps its own tabs, so switching folders
(`Ctrl+Shift+O`, `<Space>o`) brings back that folder's tabs. The state is saved on exit, on `:qa!`,
and every couple of seconds while you work, so a crash loses little. It lives in `state.json` next
to settings.yaml; `session.restore_tabs` / `session.restore_vim_state` turn the parts off.

Everything works from the keyboard. Every feature is a named command: the **command palette**
(`Ctrl+Shift+P`, or `<Space><Space>`) lists them all with their keys and runs them by fuzzy name,
and `:command.id` runs one from the vim command line (e.g. `:file.find`).

| Action | Qt shortcut | vim / leader (`<Space>`) |
|---|---|---|
| Command palette | `Ctrl+Shift+P` | `<Space><Space>` |
| Go to file (fuzzy) | `Ctrl+P` | `<Space>f` |
| Switch tab (fuzzy) / alternate tab | | `<Space>b` / `<C-^>` |
| Next / previous tab | `Ctrl+Tab` / `Ctrl+Shift+Tab` | `gt` / `gT` / `{N}gt`, `:bn` / `:bp` |
| Open folder / recent folder | `Ctrl+Shift+O` | `<Space>o` |
| Toggle explorer | | `<Space>e` |
| Move focus between panels | | `<C-w>h/j/k/l`, `<C-w>w` |
| Focus explorer / editor | `Ctrl+Shift+E` / `Ctrl+1` | |
| Save / save all / close tab | `Ctrl+S` / `Ctrl+Shift+S` / `Ctrl+F4` | `:w` `<Space>w` / `:wa` / `:q` `<C-w>q` |
| Settings / keymap | `Ctrl+,` / palette "Open User Keymap" | |

`<Space>x` `<Space>t` `<Space>s` are reserved for the explain panel, simulation and synthesis;
until those steps land they say which step brings them.

Explorer keys: `j`/`k` move, `l` expands / opens, `h` collapses / goes to the parent, `Enter`/`o`
open, `gg`/`G`, `/` search (`n`/`N` repeat), `q` hide, `Esc` back to the editor. Leader and `<C-w>`
sequences work there too. Qt shortcuts stay clear of keys vim needs (`Ctrl-W/O/R/V/A/X/B/F/D/U`).

### Key mappings (keymap.yaml)

Defaults live in [config/keymap.default.yaml](config/keymap.default.yaml). Your own `keymap.yaml`
(next to settings.yaml; palette → "Open User Keymap") is merged on top and applied when saved:

```yaml
leader: ","             # default "<Space>"
timeoutlen: 800         # ms to wait when keys could still grow into a longer mapping
normal:
  "<leader>q": app.quit # target: a command id from the palette ...
  "H": {keys: "^"}      # ... or keys to replay (not remapped)
  "<leader>p": null     # remove a default
```

### Settings

`Ctrl+,` opens `settings.yaml` (`%LOCALAPPDATA%\SV-Guard` on Windows, `~/.config/SV-Guard`
on Linux) in the editor. Saving it applies changes immediately:

```yaml
editor:
  tab_width: 4          # Tab key indents to the next multiple of this
  insert_spaces: true   # false = insert a real tab character
  font_family: ""       # empty = D2Coding / Cascadia Mono / Consolas / ...
  font_size: 11
  auto_indent: true
  highlight_current_line: true
  show_whitespace: false
```

Files keep their encoding (UTF-8, UTF-8 with BOM, cp949) and line endings (LF/CRLF) when saved.

### Vim mode

On by default (`vim.enabled: false` in settings.yaml turns it off). The engine is `vimcore`, a
pure-Python package with no Qt dependency, tested key sequence by key sequence. The status line under
each editor shows the mode, pending keys (`"a2d`) and messages. Keys vimcore does not support yet are
reported there instead of being silently ignored.

| Area | Supported (Phase V1) |
|---|---|
| Modes | Normal, Insert, Visual, Visual-Line, Command-line |
| Motions | `h j k l` `w b e W B E` `0 ^ $` `gg G` `f F t T` `; ,` `%` `N%` `+ - <CR>` `n N`, counts, arrows |
| Operators | `d c y > <` with any motion, `dd cc yy >> <<`, `x X D C s S Y`, `cw` = `ce` |
| Put / registers | `p P` with counts; `"a`–`"z`, `"A`–`"Z` (append), `"0`, `"_`, `"+`/`"*` (system clipboard) |
| Insert | `i a I A o O` (with counts), autoindent, `<Tab>` (expandtab), `<BS> <Del> <C-w> <C-u>`, `<C-v>` paste |
| Visual | motions, `o`, `d x c s y > < p P`, `D X C S Y` (whole lines), `<C-c>` copies to the clipboard |
| Undo / repeat | `u` `<C-r>` (with counts), `.` (incl. Visual changes and insert text) |
| Search | `/text` `?text` `n N` (plain text), `ignorecase` / `smartcase`, wrap-around |
| Scrolling | `<C-d> <C-u> <C-f> <C-b>` |
| Ex | `:w :q :q! :wq :x :wa :qa :qa! :e file :e! :N :$ :set ts= sw= et/noet ai ic scs ws`, `ZZ ZQ`, history with `<Up>/<Down>` |

Korean input: the editor tells the platform IME to switch off in Normal/Visual mode, so `j`/`k`/`dd`
act immediately even with the Hangul layout on, and the IME comes back (still in Hangul) in Insert and
command-line mode. If an input method composes anyway, the composition is turned into the QWERTY keys
at once (`ㅓ` → `j`) and cancelled, so commands never wait for the next key.

Planned for Phase V2/V3 (Step 12): text objects (`iw`, `i(`, …), Visual-Block, macros, marks, `:s`,
`* # ~ J r R`, SV-aware `%`, `]d`/`[d`, `gd`. Split views and project grep are planned with the
bottom panels (Step 4 onward).

## CLI

```bash
svguard check path/to/project            # a directory: discovers .sv/.v/.svh/.vh
svguard check top.sv sub.sv -I include -D SIM
svguard check proj --exclude 'third_party/**' --format json
```

```text
examples/basic/top.sv:16:13: warning: latch inferred for 'hold' because it is not assigned on all control paths [SVG-C000 InferredLatch]
examples/basic/top.sv:28:10: warning: input port 'en' is explicitly connected to nothing [SVG-C000 EmptyInputPortConn]
2 file(s) checked: 0 error(s), 2 warning(s), 0 info
```

Exit codes: `0` nothing at or above `--fail-on` (default `error`), `1` findings, `2` usage error.

### How files are treated

- `.sv`/`.v` files are compilation units, unless another file `` `include``s them
  (common in UVM packages). Those become headers, like `.svh`/`.vh`.
- Every directory that holds a header is an include directory.
- Excluded by default: hidden directories, `__pycache__`, and Vivado outputs (`*.cache`,
  `*.runs`, `*.sim`, `*.gen`, `*.hw`, `*.ip_user_files`, `*.srcs/*/ip/**`).
- Files saved as cp949 (the legacy Korean Windows encoding) are decoded transparently.

### UVM

The UVM library is found in this order: `--uvm-home`, `$UVM_HOME`, `$XILINX_VIVADO`, `vivado`
on `PATH`, then common Vivado install paths. If nothing is found, files that use UVM get one
info finding and their slang checks are skipped. Diagnostics inside the UVM library itself
are never shown.

## Roadmap

What is done and what comes next (in Korean): [docs/ROADMAP.md](docs/ROADMAP.md).

## Layout

```text
svguard/    engine core (no GUI): model, project, parser (pyslang), uvm, textio, cli
vimcore/    vim engine (no GUI): buffer, modes, keyparser, motions, operators, registers, undo,
            search, excmd, mapping (key trie + timeouts), viminfo
app/        PySide6 IDE: main window, commands (registry, keymap, palette, fuzzy), editor (tabs,
            highlighter, vim adapter, status line), panels (explorer, fuzzy finder), services (session)
config/     keymap.default.yaml
tests/      pytest suite + SV fixtures
examples/   demo projects
scripts/    Step 0 environment / API exploration scripts
```
