# Third-party notices

GameDevWorkstation adapts formats/ideas from [SethGammon/Citadel](https://github.com/SethGammon/Citadel), licensed under the MIT License: campaign file sections, exit-evidence table, discovery records, scope claims, lifecycle hook ideas, and postmortem format.

Two bundled skills come from other projects:

- `skills/graphify/` is adapted from [graphify](https://github.com/Graphify-Labs/graphify) by Safi Shamsi and the
  Graphify contributors (Apache License 2.0; earlier portions MIT). It was split into `SKILL.md` plus
  `references/` files for progressive disclosure.
- `skills/unity-mcp-orchestrator/` is adapted from the `unity-mcp-skill` in
  [CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) (MIT License), the MCP for Unity project.

## FFmpeg (not bundled)

The `trailer-maker` skill's scripts run [FFmpeg](https://ffmpeg.org) (`ffmpeg`, `ffprobe`) as an external program
found on your PATH (for example Homebrew's `ffmpeg`, a GPL-3.0-or-later build). GameDevWorkstation does not include, link
against or redistribute FFmpeg; you install it yourself (`brew install ffmpeg`) under its own license.

## Citadel — MIT License

Copyright (c) 2026 Seth Gammon

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## graphify — Apache License 2.0

`skills/graphify/` is adapted from https://github.com/Graphify-Labs/graphify (changes: the skill was split into
`SKILL.md` and `references/*.md` files for progressive disclosure). The full license text is in
[LICENSES/graphify-Apache-2.0.txt](LICENSES/graphify-Apache-2.0.txt). graphify's NOTICE file:

```
Graphify
Copyright 2026 Safi Shamsi and the Graphify contributors.

This product is licensed under the Apache License, Version 2.0 (see LICENSE).

Portions of this software were contributed under the MIT License prior to the
relicensing and remain available under those terms. The original MIT license
text is retained in LICENSE-MIT.
```

## MCP for Unity (CoplayDev/unity-mcp) — MIT License

`skills/unity-mcp-orchestrator/` is adapted from the `unity-mcp-skill` in https://github.com/CoplayDev/unity-mcp.

MIT License

Copyright (c) 2025 CoplayDev

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Claude Code Prompt Improver (severity1/claude-code-prompt-improver) — MIT License

The game-dev prompt improver (evaluation template, clarify-before-acting pattern and research-then-ask flow) is
adapted from [severity1/claude-code-prompt-improver](https://github.com/severity1/claude-code-prompt-improver) at
commit `50aae187bb4f08b852f318234b654df3332726a4`. It is reimplemented for Unity projects; the upstream
project is the pattern and template inspiration.

MIT License

Copyright (c) 2025 severity1

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
