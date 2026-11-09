#!/bin/sh
# Installs atr: fetches the source (or uses the checkout this script sits in), checks Python, picks a data
# directory, puts `atr` on your PATH through your shell's startup file, offers to install the T3 CLI,
# then runs `atr setup`. Needs sh, Python 3.13+, and git or curl/wget + tar.
#
#   curl -fsSL https://raw.githubusercontent.com/mvexel/atr/main/install.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/mvexel/atr/main/install.sh | sh -s -- --yes
#   ./install.sh [--yes]          from a checkout: installs that checkout
#   ... | sh -s -- --uninstall    or `atr uninstall`: remove the startup-file block and the fetched
#                                 source; your data directory and T3 stay
#
# Environment:
#   ATR_HOME       where a fetched source goes (default: ~/.atr; source in $ATR_HOME/src)
#   ATR_REPO       git repository to fetch (default: https://github.com/mvexel/atr)
#   ATR_REF        branch to fetch (default: main)
#   ATR_DATA_DIR   data directory (default: $XDG_DATA_HOME/atr, i.e. ~/.local/share/atr)
#   PYTHON         Python 3.13+ to use (default: python3.13, else python3)
#
# Nothing in your startup file changes without a yes (--yes answers yes to everything). Rerunning
# updates the fetched source and replaces the atr block in your startup file.
set -eu

# Everything runs from main(), called on the last line, so a half-downloaded script does nothing.
main() {
T3_INSTALLER=https://t3.codes/install.sh
BEGIN='# >>> atr >>>'
END='# <<< atr <<<'
repo=${ATR_REPO:-https://github.com/mvexel/atr}
ref=${ATR_REF:-main}
atr_home=${ATR_HOME:-$HOME/.atr}

yes=false uninstall=false
for arg in "$@"; do
  case "$arg" in
    -y|--yes) yes=true ;;
    --uninstall) uninstall=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'install.sh: unknown option %s (try --help)\n' "$arg" >&2; exit 2 ;;
  esac
done

# Prompts read the terminal, not stdin: under `curl | sh` stdin is this script.
interactive=false
if [ -t 1 ] && (exec </dev/tty) 2>/dev/null; then interactive=true; fi

if "$uninstall"; then do_uninstall; return; fi

# --- source -----------------------------------------------------------------
# Under `curl | sh` $0 is the shell, not this file: only a real install.sh path means a checkout.
here=
if [ "$(basename -- "$0")" = install.sh ] && [ -f "$0" ]; then
  here=$(CDPATH='' cd -P -- "$(dirname -- "$0")" && pwd)
fi
if [ -n "$here" ] && [ -f "$here/bin/atr" ]; then
  src_dir=$here
  echo "Source: $src_dir (this checkout)"
else
  src_dir=$atr_home/src
  fetch_source
fi
atr_bin="$src_dir/bin/atr"
[ -f "$atr_bin" ] || die "$atr_bin not found"

# --- Python -----------------------------------------------------------------
py_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 13))' 2>/dev/null; }
py=
for c in ${PYTHON:-} python3.13 python3; do
  if command -v "$c" >/dev/null 2>&1 && py_ok "$c"; then py=$c; break; fi
done
[ -n "$py" ] || die "atr needs Python 3.13 or newer; set PYTHON=/path/to/python3.13"
echo "Python: $py ($("$py" -c 'import sys; print(sys.version.split()[0])'))"

# --- data directory ---------------------------------------------------------
data=${ATR_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/atr}
case "$data" in \~/*) data="$HOME/${data#\~/}" ;; esac
if "$interactive" && ! "$yes"; then
  printf 'Data directory [%s]: ' "$data"
  read -r reply </dev/tty || reply=
  [ -n "$reply" ] && data=$reply
  case "$data" in \~/*) data="$HOME/${data#\~/}" ;; esac
fi
case "$data" in /*) ;; *) die "the data directory must be an absolute path: $data" ;; esac
case "$data/" in "$src_dir"/*) die "keep the data directory outside the source: $data" ;; esac
echo "Data: $data"

# --- shell startup file -----------------------------------------------------
shell=$(basename -- "${SHELL:-sh}")
case "$shell" in
  fish) rc="${XDG_CONFIG_HOME:-$HOME/.config}/fish/config.fish"
        lines="set -gx ATR_DATA_DIR $(q "$data")
alias atr $(q "$py -I $atr_bin")" ;;
  zsh)  rc="${ZDOTDIR:-$HOME}/.zshrc" ;;
  bash) rc="$HOME/.bashrc" ;;
  *)    rc= ;;
esac
[ "$shell" = fish ] || lines="export ATR_DATA_DIR=$(q "$data")
alias atr=$(q "$py -I $atr_bin")"
block="$BEGIN
$lines
$END"

if [ -z "$rc" ]; then
  printf '\nUnknown shell (%s). To put atr on your PATH, add these lines to its startup file:\n%s\n' "$shell" "$lines"
elif [ -f "$rc" ] && [ "$(awk -v b="$BEGIN" -v e="$END" '$0 == b { on = 1 } on { print } $0 == e { on = 0 }' "$rc")" = "$block" ]; then
  echo "Shell: $rc already has atr"
else
  printf '\nThese lines put atr on your PATH (%s):\n%s\n' "$shell" "$block"
  if ask "Add them to $rc?"; then
    if [ -f "$rc" ] && grep -qxF "$BEGIN" "$rc"; then
      # replace the old block in place
      BLK=$block; export BLK
      # shellcheck disable=SC2016
      rewrite_rc "$rc" '$0 == b { print ENVIRON["BLK"]; skip = 1; next } skip && $0 == e { skip = 0; next } !skip'
    else
      BLK=$block; export BLK
      # shellcheck disable=SC2016
      rewrite_rc "$rc" '{ print; last = $0; n++ } END { if (n && last != "") print ""; print ENVIRON["BLK"] }'
    fi
    echo "Shell: added atr to $rc; open a new terminal to use it"
  else
    echo "Shell: not changed; add the lines above yourself, or rerun the installer"
  fi
fi

# --- T3 CLI -----------------------------------------------------------------
t3=
for c in ${T3CODE_CLI_PATH:-} "$HOME/.t3/bin/t3" "$HOME/.local/bin/t3" "$(command -v t3 2>/dev/null || true)"; do
  if [ -n "$c" ] && [ -f "$c" ]; then t3=$c; break; fi
done
if [ -n "$t3" ]; then
  echo "T3: $t3"
else
  printf '\nThe T3 CLI is not installed. Without it atr only records: no agent starts or hears back.\n'
  if ask "Install it with T3 Code's official installer ($T3_INSTALLER, into ~/.t3 and ~/.local/bin/t3)?"; then
    tmp=$(mktemp -d)
    ok=false
    download "$T3_INSTALLER" "$tmp/install.sh" || true
    if [ -s "$tmp/install.sh" ]; then
      if "$interactive"; then sh "$tmp/install.sh" </dev/tty && ok=true; else sh "$tmp/install.sh" && ok=true; fi
    fi
    rm -rf "$tmp"
    if "$ok"; then
      echo "T3: installed. Next: sign in to a provider (e.g. claude auth login), start t3 once, and register a project."
    else
      echo "T3: install failed; try it yourself: curl -fsSL $T3_INSTALLER | sh"
    fi
  else
    echo "T3: not installed; later: curl -fsSL $T3_INSTALLER | sh  (or set T3CODE_CLI_PATH)"
  fi
fi

# --- atr setup --------------------------------------------------------------
printf '\n'
if "$interactive"; then
  exec "$py" -I "$atr_bin" --data-dir "$data" setup </dev/tty
fi
exec "$py" -I "$atr_bin" --data-dir "$data" setup
}

usage() {
  cat <<'USAGE'
Install atr: fetch the source, put `atr` on your PATH, offer to install the T3 CLI, run `atr setup`.

  curl -fsSL https://raw.githubusercontent.com/mvexel/atr/main/install.sh | sh
  curl -fsSL https://raw.githubusercontent.com/mvexel/atr/main/install.sh | sh -s -- --yes
  ./install.sh [--yes]     from a checkout: installs that checkout

  -y, --yes      answer yes to every question
  --uninstall    remove the atr block from your shell startup files and the fetched source;
                 keeps your data directory and T3 (also: atr uninstall)

Environment: ATR_HOME (~/.atr), ATR_REPO, ATR_REF (main), ATR_DATA_DIR (~/.local/share/atr), PYTHON.
USAGE
}

# rewrite_rc file awk-program: run the program (b, e = block markers) over the file and replace it
# atomically, keeping its mode and following a symlinked dotfile.
rewrite_rc() {
  target=$1
  [ -L "$target" ] && target=$(readlink -f -- "$target")
  mkdir -p "$(dirname -- "$target")"
  [ -f "$target" ] || : > "$target"
  tmp=$(mktemp "$(dirname -- "$target")/.atr-rc.XXXXXX")
  awk -v b="$BEGIN" -v e="$END" "$2" "$target" > "$tmp" || { rm -f "$tmp"; die "could not rewrite $target"; }
  chmod "$(stat -c %a "$target" 2>/dev/null || stat -f %Lp "$target")" "$tmp"
  mv -f "$tmp" "$target"
}

# Undo what the installer did: the atr block in shell startup files and a source it fetched.
# The data directory and T3 are left alone.
do_uninstall() {
  data=
  found=false
  for rc in "$HOME/.bashrc" "${ZDOTDIR:-$HOME}/.zshrc" "${XDG_CONFIG_HOME:-$HOME/.config}/fish/config.fish"; do
    if [ ! -f "$rc" ] || ! grep -qxF "$BEGIN" "$rc"; then continue; fi
    found=true
    [ -n "$data" ] || data=$(awk -v b="$BEGIN" -v e="$END" '$0 == b { on = 1 } on && /ATR_DATA_DIR/ { sub(/.*ATR_DATA_DIR[= ]/, ""); gsub(/\047/, ""); print; exit } $0 == e { on = 0 }' "$rc")
    if ask "Remove the atr block from $rc?"; then
      # drop the block and the blank line the installer put before it
      # shellcheck disable=SC2016
      rewrite_rc "$rc" '$0 == b { skip = 1; held = 0; next } skip { if ($0 == e) skip = 0; next }
        held { print ""; held = 0 } $0 == "" { held = 1; next } { print } END { if (held) print "" }'
      echo "Shell: removed atr from $rc"
    else
      echo "Shell: kept atr in $rc"
    fi
  done
  "$found" || echo "Shell: no atr block in your startup files"

  src_dir=$atr_home/src
  if [ -f "$src_dir/.atr-tarball" ] || [ -d "$src_dir/.git" ]; then
    if [ -d "$src_dir/.git" ] && [ -n "$(git -C "$src_dir" status --porcelain 2>/dev/null)" ]; then
      echo "Source: $src_dir has local changes; kept (delete it yourself if you mean to)"
    elif ask "Delete the atr source in $src_dir?"; then
      rm -rf "$src_dir"
      rmdir "$atr_home" 2>/dev/null || true
      echo "Source: deleted $src_dir"
    else
      echo "Source: kept $src_dir"
    fi
  elif [ -e "$src_dir" ]; then
    echo "Source: $src_dir was not made by this installer; kept"
  else
    echo "Source: nothing fetched by the installer (a checkout you cloned yourself stays)"
  fi

  data=${data:-${ATR_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/atr}}
  echo "Data: kept $data (your rooms and records); delete it yourself if you no longer want them"
  echo "T3: not touched"
}

die() { printf 'install.sh: %s\n' "$1" >&2; exit 1; }

# ask "question" -> 0 for yes. --yes answers yes; no terminal answers no.
ask() {
  if "$yes"; then return 0; fi
  if ! "$interactive"; then return 1; fi
  printf '%s [y/N] ' "$1"
  read -r reply </dev/tty || return 1
  case "$reply" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

# Quote a value for sh and fish alike: single quotes, with ' written as '\''.
q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

download() {   # url file
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then wget -q "$1" -O "$2"
  else die "curl or wget is required"; fi
}

# Put the source in $src_dir: clone or fast-forward with git, else unpack a tarball of $ref.
fetch_source() {
  mkdir -p "$atr_home"
  if [ -d "$src_dir/.git" ] && command -v git >/dev/null 2>&1; then
    echo "Source: updating $src_dir"
    git -C "$src_dir" pull --ff-only --quiet origin "$ref" \
      || die "could not update $src_dir (local changes?); fix it or remove it and rerun"
  elif [ -e "$src_dir" ] && [ ! -f "$src_dir/.atr-tarball" ]; then
    die "$src_dir exists and is not an atr source this installer made; move it away and rerun"
  elif command -v git >/dev/null 2>&1 && [ ! -e "$src_dir" ]; then
    echo "Source: cloning $repo into $src_dir"
    git clone --quiet --branch "$ref" "$repo" "$src_dir" || die "could not clone $repo"
  else
    echo "Source: downloading $repo ($ref) into $src_dir"
    command -v tar >/dev/null 2>&1 || die "git, or tar with curl/wget, is required"
    tmp=$(mktemp -d "$atr_home/.download.XXXXXX")
    download "${repo%.git}/archive/refs/heads/$ref.tar.gz" "$tmp/src.tar.gz" || { rm -rf "$tmp"; die "download failed"; }
    mkdir "$tmp/src"
    tar -xzf "$tmp/src.tar.gz" -C "$tmp/src" --strip-components=1 || { rm -rf "$tmp"; die "could not unpack the source"; }
    : > "$tmp/src/.atr-tarball"
    rm -rf "$src_dir.old"
    [ -e "$src_dir" ] && mv "$src_dir" "$src_dir.old"
    mv "$tmp/src" "$src_dir"
    rm -rf "$tmp" "$src_dir.old"
  fi
}

main "$@"
