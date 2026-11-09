# zsh completion for atr. install.sh loads this file; otherwise: eval "$(atr completion zsh)"
# Needs the completion system (compinit) loaded first, as most zsh setups do.
# Candidates come from `atr __complete`, which reads atr's own parser and your rooms.
_atr() {
    local line
    local -a lines cands
    lines=("${(@f)$(atr __complete "${(@Q)words[2,CURRENT-1]}" "${(Q)words[CURRENT]}" 2>/dev/null)}")
    if [[ $lines[1] == :dirs ]]; then
        _files -/
        return
    fi
    for line in $lines; do
        [[ -n $line ]] || continue
        if [[ $line == *$'\t'* ]]; then
            cands+=("${${line%%$'\t'*}//:/\\:}:${line#*$'\t'}")
        else
            cands+=("${line//:/\\:}")
        fi
    done
    _describe -t atr atr cands
}
(( $+functions[compdef] )) && compdef _atr atr
