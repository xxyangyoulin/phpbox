#compdef pbox phpbox
_pbox() {
    local context state state_descr line
    typeset -A opt_args
    local -a commands environments projects
    commands=(list ps status start up stop restart recreate down build rebuild logs shell exec php composer artisan think env use recover doctor completion help gui)
    _arguments -C \
        '(-h --help)'{-h,--help}'[显示帮助]' \
        '--version[显示版本]' \
        '(-p --project)'{-p,--project}'[选择项目]:项目:->projects' \
        '(-C --directory)'{-C,--directory}'[切换目录]:目录:_directories' \
        '(-q --quiet)'{-q,--quiet}'[隐藏进度]' \
        '(-T --no-tty -t --tty)'{-T,--no-tty}'[禁用终端]' \
        '(-T --no-tty -t --tty)'{-t,--tty}'[强制终端]' \
        '--verbose[显示完整错误]' \
        '1:命令:->commands' '*::参数:->args'
    case $state in
        projects)
            projects=("${(@f)$(command pbox list -q 2>/dev/null)}")
            _describe '项目' projects ;;
        commands) _describe '命令' commands ;;
        args)
            case $words[1] in
                env)
                    if (( CURRENT == 2 )); then
                        _values '环境操作' list inspect create start stop restart rebuild delete
                    else
                        environments=("${(@f)$(command pbox env list -q 2>/dev/null)}")
                        _describe '环境 ID' environments
                        _values '选项' --yes --json --no-cache --php --extension --proxy --start
                    fi ;;
                use)
                    environments=("${(@f)$(command pbox env list -q 2>/dev/null)}")
                    _describe '环境 ID' environments
                    _values '选项' --check --json ;;
                shell|exec) _values '服务/选项' php nginx mysql redis cron -T -t -u --user -w --workdir ;;
                completion) _values 'Shell' bash zsh fish ;;
                php|composer|artisan|think) _files ;;
                help) _describe '命令' commands; _values '选项' --all ;;
                *)
                    projects=("${(@f)$(command pbox list -q 2>/dev/null)}")
                    _describe '项目' projects
                    _values '选项' --json --all --check --no-cache --follow --no-follow --service --tail --since --timestamps --no-color ;;
            esac ;;
    esac
}
compdef _pbox pbox phpbox
