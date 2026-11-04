# Prompt Coach (Windows) — PRD v0.1
Owner: Advik Saxena · Date: 2026-11-03 · Scope decisions: **Council** (stack, v1 scope, gate, kill rule, acceptance criteria, risks, out-of-scope).

## 1. Problem
Advik's prompts to Cursor chat, Claude desktop, claude.ai/ChatGPT and Claude Code often lack a goal, a "done when" line, file names, or constraints. That costs extra turns, tokens and rate limits. He wants a "Grammarly for prompts": press a key and get a better prompt to preview, plus a small count of issues.

## 2. Goals / Non-goals
**Goals:** a hotkey that rewrites the prompt with a preview before anything is pasted; free local checks that cost no tokens; local LLM (Ollama) by default; usable within one week.
**Non-goals (Council, out of scope):** hover underlines or per-word rectangles; auto-rewrite while typing or before submit; auto-paste without preview; auto-submit; Cursor/Claude rewrite hooks; a C# port; Electron; a PyInstaller installer (later note only); auto-updates; fine-tuning; analytics; multi-user use or a team rollout; selling it; cloud logging; Gemini as the default; triple-tap Ctrl as the default.

## 3. User stories
- As Advik, in Cursor chat I press Ctrl+Alt+Space, see original vs. rewrite, and press Accept to replace my prompt.
- I press Esc or Reject and my prompt is unchanged, byte for byte.
- I open the badge and see "3 issues: no Done-when, vague verb, no file named".
- If Ollama is off, I get a clear toast telling me to start it, not a silent cloud call.
- In Windows Terminal (Claude Code) I select text myself and use Copy-only.

## 4. Day 0 gate (Council) — before any code
1. **Prior art check (15 min):** look at existing AutoHotkey or PowerToys-style "send selection to Ollama" tools.
2. **UIA test (30 min):** open Accessibility Insights for Windows (Live Inspect) or inspect.exe (Windows SDK). Focus Cursor's chat box, then the Claude desktop input. Run it once normally and once after launching with `--force-renderer-accessibility`. Record:
   - Does the element support TextPattern?
   - Does it return the real typed text?
   - Are the BoundingRectangle and text-range rectangles sensible?
   - Does Cursor feel slower with accessibility forced?
3. **Outcome:**
   - **Pass:** the badge is placed near the input.
   - **Fail:** the badge follows the mouse cursor and works on demand only, using clipboard text.
   - The hotkey path never depends on UIA.

## 5. v1 features
### Must (Council)
1. **Global hotkey**, default `Ctrl+Alt+Space`, configurable.
2. **Capture:** save the clipboard → Ctrl+A → Ctrl+C → read the text → restore the original clipboard.
3. **Rewrite through Ollama** (local) with one versioned system prompt file (`prompts/rewriter_v1.md`).
4. **Preview window:** original vs. rewrite, with **Accept** (paste), **Reject** (no change; Esc = Reject), and **Copy-only**.
5. **Error toast** for every failure.
6. **Local rule checker:** 5–8 no-token checks, defined in config (§8).
7. **Badge:** issue count plus the list. Placed near the input if UIA works, otherwise near the mouse. On demand.
8. **Local log** (JSONL) of original, rewrite and accept/reject. It doubles as the redo log, with a clear-log option.
9. **Autostart** with `pythonw` at login.

### Nice-to-have
- Up to 3 clarifying questions in the preview before the rewrite.
- Gemini API as an opt-in fallback (`gemini-3.1-flash-lite`), asked each time.
- Tray icon with pause.
- Per-app on/off list.
- Live badge polling every 250–500 ms.

## 6. UX flow
1. Hotkey pressed.
2. Record the foreground window handle.
3. Skip if the field is a password field (UIA IsPassword), or empty/unreadable.
4. Capture the text.
5. Run the local checks and update the badge.
6. Show the preview with a spinner and a Cancel button; call Ollama with a ~30 s timeout.
7. Show the rewrite (and clarifying questions if enabled).
8. **Accept:** if the foreground window is unchanged, paste and restore the clipboard. Otherwise show "focus changed" and keep Copy available. **Reject/Esc:** nothing changes.
9. Write the log entry.

## 7. Architecture (modules)
| Module | Responsibility |
|---|---|
| `hotkey.py` | pynput `GlobalHotKeys`. The callback only puts an event on a `queue.Queue` and must return in under 10 ms. |
| `worker.py` | Queue thread / `QThread`. Runs capture → check → LLM and emits Qt signals to the UI. |
| `clipboard.py` | pywin32 `win32clipboard`: save and restore all formats, 3 retries if locked, send Ctrl+A/C/V with short delays (~50–150 ms, tune). |
| `focus.py` | uiautomation `GetFocusedControl()`, IsPassword, BoundingRectangle, foreground window handle. |
| `checker.py` | Pure functions, no I/O, rules from `config/rules.yaml`. |
| `llm/ollama.py` | POST `http://localhost:11434/api/chat`, `stream:false`, optional `format` JSON schema. |
| `llm/gemini.py` | Optional fallback. `google-genai` SDK (`pip install -U google-genai`) or REST POST `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` with header `x-goog-api-key`. Key from the `GEMINI_API_KEY` env var. Request JSON output (`mime_type: application/json` + schema). Runs only after the user clicks "Ollama failed: send to Gemini?" in the preview, every time. |
| `ui/preview.py`, `ui/badge.py`, `ui/toast.py` | PySide6 frameless tool windows. |
| `config.py` | `config.toml`: hotkey, model, timeouts, size cap, app list. |
| `log.py` | `%APPDATA%/PromptCoach/log.jsonl`. |

**Threading rule:** never block the pynput callback. pynput warns that on Windows blocking there "risks freezing input for all processes." UI updates happen only on the Qt main thread, via signals.

## 8. Tech stack (versions seen in sources)
- Python 3.12+ (assumed; not verified).
- PySide6 (Qt 6.12 docs).
- pynput 1.8.2.
- uiautomation 2.0.29.
- pywin32 (version not checked).
- httpx or requests (not checked).
- pytest.
- Ollama with a default model of `qwen2.5:3b` (1.9 GB) or `llama3.2` (3B, 2.0 GB). Lighter option: `gemma3:1b` (806 MB).
- Optional fallback: Gemini API, `gemini-3.1-flash-lite` (alt `gemini-2.5-flash-lite`; Gemma `gemma-4` is listed on the pricing page, free tier only).

## 9. Local rules (config-defined; Council list)
| id | Fails when |
|---|---|
| R1 no_done_when | no "done when" / "acceptance" / "should pass" line |
| R2 no_target | no file path, filename-like token (`\w+\.\w{1,5}`), page or URL |
| R3 too_short | fewer than ~15 words |
| R4 vague_verb | matches "fix it", "make it better", "clean up", "improve this" with no object |
| R5 no_dont | no "don't" / "do not" / "avoid" / "never" line |
| R6 multi_task | more than one imperative task (for example "and also", numbered list of unrelated asks) |
| R7 (opt) no_output_format | no stated output shape (diff, list, file) |
| R8 (opt) no_context | no why or background sentence |

These map to the common guidance in Anthropic/OpenAI/Google prompting guides: give context, be specific, state the output format and success criteria. I did not re-open those guides this round, so cite them only after re-checking.

## 10. Rewriter system prompt (`prompts/rewriter_v1.md`)
```
You rewrite a developer's prompt for an AI coding assistant. Output JSON:
{"rewrite": str, "questions": [str] (0-3), "changes": [str]}.
Rules: keep every file name, path, identifier, constraint and code block exactly.
Never invent files, APIs, facts or requirements. If key info is missing, ask
(max 3 short questions) instead of guessing. Structure: Goal, Context,
Constraints/Don't, Output format, Done when. Keep the user's voice; be concise.
```
Pass this as an Ollama `format` JSON schema with `rewrite`, `questions` and `changes` as required fields. If questions are returned, show them in the preview; answers are added and the rewrite is regenerated once.

## 11. Edge cases and risks (Council)
- **Password fields:** if UIA reports IsPassword, or the field is empty or unreadable → do nothing. Never log or send it.
- **Focus loss:** if the foreground window changed before Accept → don't paste; show "focus changed"; Copy stays available.
- **Clipboard locked or clipboard history:** retry 3×, then abort cleanly. Preserve non-text formats or warn.
- **Ollama down or model missing:** GET `localhost:11434` / `/api/tags` → toast "Start Ollama / pull model". Never fall back to Gemini silently: the preview shows "Ollama failed: send to Gemini?" with a warning not to send client code or secrets, because free-tier prompts may be used to improve Google products. ~30 s timeout.
- **Claude Code terminal:** Ctrl+A doesn't select the prompt, and a multi-line paste can submit early. Use manual-select plus Copy-only; account for bracketed paste; or leave the terminal out of v1.
- **Elevated (admin) windows:** synthetic keys can't reach them. Detect and tell the user.
- **Huge prompts:** size cap on local checks; warn before sending large text.
- **Forced accessibility** may slow Cursor; measure it at the gate.
- **Cursor updates** may break UIA; the hotkey path is independent of UIA.

## 12. Privacy
Local by default. Text goes only to Ollama on localhost. Gemini is opt-in and needs confirmation each time. On the free tier Google uses submitted content to improve its products, and human reviewers may read it, so don't send client code on the free key. The log is local only and can be cleared. Password fields are never captured.

## 13. Acceptance criteria (Council)
- **Hotkey:** fires only on the combo. 0 false triggers in a day of normal Ctrl+C/V/Z use. Callback under 10 ms.
- **Clipboard:** copy X → trigger → accept or reject → the clipboard still holds X. Tested with text, an image, and an empty clipboard.
- **Reject/Esc:** the prompt is byte-identical. **Accept:** replaces only the prompt.
- **Rewrite** on a 10-real-prompt test set: every file name, constraint and code block kept; nothing invented. Result in under ~5 s on a mid-range laptop, or a spinner with Cancel.
- **Rules:** each has one pass fixture and one fail fixture. The badge count equals the checker's output.
- **Apps:** works in Cursor chat, Claude desktop, Chrome (claude.ai, ChatGPT), and Windows Terminal + Claude Code (copy-only or manual-select).
- **Kill rule at day 7:** stop if fewer than 50% of rewrites are accepted, or he uses it less than once a day.

## 14. Test plan
- `pytest`: `tests/test_checker.py` with parametrized pass/fail fixtures in `tests/fixtures/rules/`. `tests/test_ollama.py` mocks HTTP: down, timeout, bad JSON. `tests/test_clipboard.py` (Windows-only marker). Golden set `tests/fixtures/prompts/*.txt` with checks that file names and code blocks are preserved.
- Manual checklist for each app in §13. A one-day dogfood log for false triggers.

Layout:
```
prompt-coach/  PRD.md  pyproject.toml  config/{config.toml,rules.yaml}
  prompts/rewriter_v1.md  src/prompt_coach/{main,hotkey,worker,clipboard,focus,checker,config,log}.py
  src/prompt_coach/llm/{ollama,gemini}.py  src/prompt_coach/ui/{preview,badge,toast}.py  tests/
```

## 15. Milestones
- **Day 0:** prior art check (15 min) and the UIA gate (30 min); record the results here.
- **Week 1:** hotkey → capture → Ollama → preview → Accept/Reject/Copy, plus clipboard restore, toasts and the log. **Kill rule:** if the rewrite isn't working by the end of week 1 (Council), stop.
- **Week 2:** rule checker and on-demand badge, autostart. Then the nice-to-haves.
- **Later note:** PyInstaller one-file build (`pyinstaller --onefile --windowed`). The docs recommend getting one-folder mode working first.

## 16. Open questions
- Which app passes the UIA gate?
- Which default model gives the best balance of speed and quality on his laptop (qwen2.5:3b vs. llama3.2 vs. gemma3:1b)?
- Is `Ctrl+Alt+Space` free in his setup? I found no source on conflicts. Microsoft lists Ctrl+Spacebar for input-method switching, and AltGr sends Ctrl+Alt on some layouts (Qt docs). Test it.
- Include the terminal in v1 or not?

## 17. Sources (opened)
- pynput keyboard docs (GlobalHotKeys, HotKey, threading warning): https://pynput.readthedocs.io/en/latest/keyboard.html
- pynput 1.8.2 on PyPI: https://pypi.org/project/pynput/
- uiautomation 2.0.29 on PyPI: https://pypi.org/project/uiautomation/ ; source file: https://raw.githubusercontent.com/yinkaisheng/Python-UIAutomation-for-Windows/master/uiautomation/uiautomation.py
- UIA property IDs (IsPassword 30019, BoundingRectangle 30001): https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-automation-element-propids
- Accessibility Insights for Windows: https://accessibilityinsights.io/docs/windows/overview/
- Ollama /api/chat: https://docs.ollama.com/api/chat
- Ollama model pages: https://ollama.com/library/qwen2.5 , https://ollama.com/library/llama3.2 , https://ollama.com/library/gemma3
- Gemini quickstart (official docs, opened 2026-11-03): "pip install -U google-genai"; `export GEMINI_API_KEY`; curl uses `-H "x-goog-api-key: $GEMINI_API_KEY"`. Note: its examples now use the newer `/v1beta/interactions` endpoint. https://ai.google.dev/gemini-api/docs/quickstart
- generateContent reference (official, 2026-11-03): "POST /v1beta/models/{model}:generateContent". https://ai.google.dev/api/generate-content
- Models (official, 2026-11-03): lists `gemini-3.1-flash-lite`, `gemini-2.5-flash-lite`, `gemini-2.5-flash`, `gemini-3-flash-preview`. https://ai.google.dev/gemini-api/docs/models
- Pricing (official, 2026-11-03), per 1M tokens: 3.1 Flash-Lite paid $0.25 in / $1.50 out; 2.5 Flash-Lite $0.10 / $0.40; free tier "Free of charge"; Gemma 4 free only, paid "Not available"; free tier "Used to improve our products: Yes". https://ai.google.dev/gemini-api/docs/pricing
- Rate limits (official, 2026-11-03): limits are RPM, TPM and RPD; exceeding any one returns an error. I could not extract per-model numbers; check AI Studio. https://ai.google.dev/gemini-api/docs/rate-limits
- Structured output (official, 2026-11-03): `"mime_type": "application/json", "schema": Recipe.model_json_schema()`. https://ai.google.dev/gemini-api/docs/structured-output
- Gemini API terms (legal, 2026-11-03): on Unpaid Services "Google uses the content you submit ... to provide, improve, and develop Google products"; "Do not submit sensitive, confidential, or personal information to the Unpaid Services." https://ai.google.dev/gemini-api/terms
- PySide6 Qt namespace (window flags, WA_TranslucentBackground, connection types): https://doc.qt.io/qtforpython-6/PySide6/QtCore/Qt.html ; Qt C++: https://doc.qt.io/qt-6/qt.html
- PyInstaller operating mode: https://pyinstaller.org/en/stable/operating-mode.html ; troubleshooting: https://pyinstaller.org/en/stable/when-things-go-wrong.html
- pywin32 GetClipboardData: https://timgolden.me.uk/pywin32-docs/win32clipboard__GetClipboardData_meth.html
- Windows keyboard shortcuts: https://support.microsoft.com/en-us/windows/keyboard-shortcuts-in-windows-dcc61a57-8ff0-cffe-9796-cb9706c75eec
