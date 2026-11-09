# NixOS installation and return to work

The target is to install the software, restore durable data and resume with Claude Code, Codex and atr on required T3. Nix describes software; private workflow/conversation state remains writable data outside the Nix store.

## Software

Use a pinned nixpkgs revision that provides `claude-code`, `codex`, `t3code` and `python313`. Current nixos-unstable has these packages. The T3 wrapper supports `enableClaude = true` and `enableCodex = true`; Claude Code requires the applicable unfree-package allowance. Pin versions and follow provider account terms.

A Home Manager launcher for a pinned atr source can use:

```nix
let
  # Replace with your reviewed pinned source input or checkout.
  atrSource = pkgs.lib.cleanSource /path/to/atr;
  t3 = pkgs.t3code.override { enableClaude = true; enableCodex = true; };
  atr = pkgs.writeShellScriptBin "atr" ''
    export ATR_SOURCE=${atrSource}
    exec ${pkgs.python313}/bin/python3 -I ${atrSource}/bin/atr "$@"
  '';
in {
  home.packages = [ pkgs.claude-code pkgs.codex t3 atr ];
  home.sessionVariables = {
    ATR_SOURCE = "${atrSource}";
    ATR_DATA_DIR = "${config.home.homeDirectory}/.local/share/atr";
    T3CODE_CLI_PATH = "${t3}/bin/t3";
    ATR_T3_PROJECT = "${config.home.homeDirectory}/projects/my-project";
  };
  home.file.".claude/skills/atr-lead".source = "${atrSource}/skills/lead";
  home.file.".agents/skills/atr-lead".source = "${atrSource}/skills/lead";
}
```

This fragment belongs inside a Home Manager module with `config` and `pkgs` arguments. Include all bundled atr resources alongside `bin/`; copying only the executable breaks templates/docs/web. Project and data directories must be writable. Choose a real T3-registered project, not the read-only installed source. A pinned source must be fetchable through the chosen private repository authentication without embedding credentials in a Nix expression/store.

Do not manage provider credentials as Nix string values: the Nix store is not a secret store. Run `claude` and `codex` interactively to authenticate after installation. Start T3 and verify both configured providers there. Shell session variables must also be supplied explicitly if you later configure a user service.

## Before wiping the old installation

Make an off-machine backup, with Unix metadata preserved, of:

- The entire selected atr store: `rooms/`, attachments and hidden `.atr/` recovery, delivery, migration and operator state.
- T3's configured runtime base directory and its `userdata/` database, conversations and associated artifacts, following T3's backup procedure with writers stopped. Confirm the actual base directory; do not assume every installation uses the same default.
- All project repositories, local branches, ignored/untracked work and preserved checkouts. Source remotes omit unpushed commits and untracked files.
- Provider settings, custom skills, approved local instructions and needed agent history from the actual Claude/Codex configuration directories. Secrets require a private backup or fresh login; don't put them in this repo.
- The reviewed configuration revision and source pins used for installation.

A parking directory on the machine being wiped is not an off-machine backup. Copy preservation archives and their manifests to another disk or private backup destination and verify extraction/hashes before erasing. Keep a recovery copy unchanged while testing the restore.

## Restore and verify

1. Rebuild the declared software using the saved configuration/pins. Restore private data with ownership and modes intact while writers are stopped.
2. Restore projects, T3 runtime and atr store to their intended writable locations. If paths changed, inspect recorded project/checkouts and T3 routing; do not blindly reuse old absolute paths or invent replacement thread IDs.
3. Reauthenticate providers as needed. Start the restored T3 runtime with its chosen base directory. Confirm project registration and historical threads before new dispatch.
4. Set `ATR_DATA_DIR`, `T3CODE_CLI_PATH`, `ATR_T3_PROJECT` and, when needed, `ATR_T3_BASE_DIR` consistently for CLI and web. Run `atr setup --check`, `atr status ROOM`, `atr check ROOM` and `atr delivery list` against the restored store.
5. Read an existing room and its attachments. Check pending/uncertain delivery against current T3 history before retrying. Restoring an older backup can omit later external acceptance; preserve the original ledger and reconcile the evidence.
6. Run `atr setup` (or `atr service install`) for the web page service, or declare an equivalent user unit in your home-manager configuration if you manage units declaratively; then open `http://127.0.0.1:8787/`. Rehearse a local decision save and a bounded T3 launch/message in a separate disposable room after its gates. Verify the returned thread and actual response through T3 before returning to production work.

Use [operations](OPERATIONS.md) for recovery and [migration](MIGRATION.md) for rehearsing old layouts. Source cleanup does not switch live stores or services. A disposable fresh-home rehearsal on the current host is not proof of a NixOS installation; full NixOS activation, provider authentication and restored real T3 conversations must be checked on the target system.

Package references checked during cleanup: [Claude Code](https://github.com/NixOS/nixpkgs/blob/nixos-unstable/pkgs/by-name/cl/claude-code/package.nix), [Codex](https://github.com/NixOS/nixpkgs/blob/nixos-unstable/pkgs/by-name/co/codex/package.nix), [T3](https://github.com/NixOS/nixpkgs/blob/nixos-unstable/pkgs/by-name/t3/t3code/package.nix). These moving links explain the package interfaces; deployment uses a pinned revision.
