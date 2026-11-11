# Dependencies and distribution boundary

Atr source includes Python standard-library modules, templates, a self-contained browser page, SVG asset and workflow documentation. Runtime needs Python 3.13 on POSIX with `fcntl.flock`, filesystem syncing and timezone data. No pip dependencies, frontend build or CDN are required.

T3 Code and its public CLI are a required prerequisite, installed separately; atr itself keeps recording without it. Claude Code and Codex are authenticated providers configured through T3; atr does not supply provider credentials. The tested bridge baseline was T3 CLI v0.1.2; version discovery alone is not runtime acceptance and newer versions need a dispatch/communication check.

| Component | Separate terms/source |
| --- | --- |
| Python | [PSF license and incorporated notices](https://docs.python.org/3.13/license.html) |
| T3 Code | [Upstream MIT license](https://github.com/pingdotgg/t3code/blob/main/LICENSE); retain its incorporated-software notices when packaging |
| Claude Code, Codex and provider services | Install/configure separately through their own distribution and account terms |
| Browser, system fonts, timezone data and operating system | Supplied by the user's system; retain relevant notices if redistributed |
| Node.js and browser automation tools | Verification tools where used, not atr runtime requirements |

Git and external integration clients are absent from the core runtime dependency set. Historical workflows and optional integration implementations have been preserved outside the source tree for possible future plugins. There is no plugin loading framework in this core.

Atr itself is licensed under the [Functional Source License 1.1, Apache 2.0 future license](../LICENSE.md) (FSL-1.1-ALv2); dependency licenses do not license atr. Never distribute private room data, attachments, hidden `.atr` state, operator configuration, credentials or provider logs as part of a core source package.
