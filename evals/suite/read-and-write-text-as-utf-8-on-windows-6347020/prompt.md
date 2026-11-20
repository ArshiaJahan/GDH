Read and write text as UTF-8 on Windows

Windows decodes text with the ANSI code page (cp1252) by default, so a
UTF-8 SKILL.md with a curly quote stopped Claude Code sessions from
starting: "'charmap' codec can't decode byte 0x9d".

- Every read_text/write_text/open/fdopen and text-mode subprocess in the
  backend and scripts now names its encoding (subprocess output: replace)
- [hidden test] walks the source so a new call without
  encoding= fails on every platform
- The frozen backend runs in Python UTF-8 mode
- Windows CI runs the new tests and reads every bundled skill through the
  frozen backend
