# bash completion for atr. install.sh loads this file; otherwise: eval "$(atr completion bash)"
# Candidates come from `atr __complete`, which reads atr's own parser and your rooms.
_atr() {
    local cur=${COMP_WORDS[COMP_CWORD]} out IFS=$'\n'
    out=$(atr __complete "${COMP_WORDS[@]:1:COMP_CWORD-1}" "$cur" 2>/dev/null) || return 0
    if [[ $out == :dirs* ]]; then
        compopt -o filenames 2>/dev/null
        COMPREPLY=($(compgen -d -- "$cur"))
        return 0
    fi
    COMPREPLY=($(printf '%s\n' "$out" | cut -f1))
}
complete -F _atr atr
