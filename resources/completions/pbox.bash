_pbox_complete() {
    local cur prev cmd='' sub='' word i
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    COMPREPLY=()
    case "$prev" in
        -p|--project)
            mapfile -t COMPREPLY < <(compgen -W "$(command "${COMP_WORDS[0]}" list -q 2>/dev/null)" -- "$cur")
            return ;;
        -C|--directory)
            mapfile -t COMPREPLY < <(compgen -d -- "$cur")
            return ;;
        -s|--service)
            mapfile -t COMPREPLY < <(compgen -W 'php nginx mysql redis cron' -- "$cur")
            return ;;
    esac
    for ((i=1; i<COMP_CWORD; i++)); do
        word="${COMP_WORDS[i]}"
        case "$word" in
            -p|--project|-C|--directory) ((i++)); continue ;;
            -*) continue ;;
        esac
        if [[ -z "$cmd" ]]; then cmd="$word"; else sub="$word"; break; fi
    done
    local words=''
    case "$cmd" in
        '') words='list ps status start up stop restart recreate down build rebuild logs shell exec php composer artisan think env use recover doctor completion help gui --help --version -p --project -C --directory -q --quiet -T --no-tty -t --tty --verbose' ;;
        env)
            if [[ -z "$sub" ]]; then
                words='list inspect create start stop restart rebuild delete'
            else
                words="$(command "${COMP_WORDS[0]}" env list -q 2>/dev/null) --help --yes --json --no-cache --php --extension --proxy --start"
            fi ;;
        use) words="$(command "${COMP_WORDS[0]}" env list -q 2>/dev/null) --check --json --help" ;;
        shell|exec) words='php nginx mysql redis cron --help -T --no-tty -t --tty -u --user -w --workdir' ;;
        completion) words='bash zsh fish' ;;
        php|composer|artisan|think) return ;;
        help) words='list ps status start up stop restart recreate down build rebuild logs shell exec php composer artisan think env use recover doctor completion gui --all' ;;
        *) words="$(command "${COMP_WORDS[0]}" list -q 2>/dev/null) --help --json --check --all --no-cache --follow --no-follow --service --tail --since --timestamps --no-color" ;;
    esac
    mapfile -t COMPREPLY < <(compgen -W "$words" -- "$cur")
}
complete -o default -F _pbox_complete pbox phpbox
