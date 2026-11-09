# fish completion for atr. install.sh loads this file; otherwise: atr completion fish | source
# Candidates come from `atr __complete`, which reads atr's own parser and your rooms.
function __atr_complete
    set -l tokens (commandline -opc)
    set -e tokens[1]
    set -l cur (commandline -ct)
    set -l out (atr __complete $tokens "$cur" 2>/dev/null)
    if test "$out[1]" = ":dirs"
        __fish_complete_directories "$cur"
        return
    end
    printf '%s\n' $out
end
complete -c atr -f -a '(__atr_complete)'
