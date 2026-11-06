for cmd in pbox phpbox
    complete -c $cmd -s h -l help -d '显示帮助'
    complete -c $cmd -l version -d '显示版本'
    complete -c $cmd -s p -l project -r -f -a '(pbox list -q 2>/dev/null)' -d '选择项目'
    complete -c $cmd -s C -l directory -r -a '(__fish_complete_directories)' -d '切换目录'
    complete -c $cmd -s q -l quiet -d '隐藏进度'
    complete -c $cmd -s T -l no-tty -d '禁用终端'
    complete -c $cmd -s t -l tty -d '强制终端'
    complete -c $cmd -l verbose -d '显示完整错误'
    complete -c $cmd -n 'not __fish_seen_subcommand_from list ps status start up stop restart recreate down build rebuild logs shell exec php composer artisan think env use recover doctor completion help gui' -f -a 'list ps status start up stop restart recreate down build rebuild logs shell exec php composer artisan think env use recover doctor completion help gui'
    complete -c $cmd -n '__fish_seen_subcommand_from start up stop restart recreate down build rebuild logs status ps recover' -f -a '(pbox list -q 2>/dev/null)'
    complete -c $cmd -n '__fish_seen_subcommand_from env; and not __fish_seen_subcommand_from list inspect create start stop restart rebuild delete' -f -a 'list inspect create start stop restart rebuild delete'
    complete -c $cmd -n '__fish_seen_subcommand_from use; or begin; __fish_seen_subcommand_from env; and __fish_seen_subcommand_from inspect start stop restart rebuild delete; end' -f -a '(pbox env list -q 2>/dev/null)'
    complete -c $cmd -n '__fish_seen_subcommand_from exec shell' -f -a 'php nginx mysql redis cron'
    complete -c $cmd -n '__fish_seen_subcommand_from logs' -l service -s s -r -a 'php nginx mysql redis cron'
    complete -c $cmd -n '__fish_seen_subcommand_from logs' -s f -l follow
    complete -c $cmd -n '__fish_seen_subcommand_from logs' -l no-follow
    complete -c $cmd -n '__fish_seen_subcommand_from logs' -l tail -r
    complete -c $cmd -n '__fish_seen_subcommand_from logs' -l since -r
    complete -c $cmd -n '__fish_seen_subcommand_from logs' -l timestamps
    complete -c $cmd -n '__fish_seen_subcommand_from logs' -l no-color
    complete -c $cmd -n '__fish_seen_subcommand_from env' -s y -l yes
    complete -c $cmd -n '__fish_seen_subcommand_from env; and __fish_seen_subcommand_from create' -l php -r -a '8.4 8.3 8.2 8.1 8.0 7.4 7.3 7.2'
    complete -c $cmd -n '__fish_seen_subcommand_from env; and __fish_seen_subcommand_from create' -l extension -r
    complete -c $cmd -n '__fish_seen_subcommand_from env; and __fish_seen_subcommand_from create' -l proxy -r
    complete -c $cmd -n '__fish_seen_subcommand_from env; and __fish_seen_subcommand_from create' -l start
    complete -c $cmd -n '__fish_seen_subcommand_from list status ps inspect doctor use' -l json
    complete -c $cmd -n '__fish_seen_subcommand_from status ps use' -l check
    complete -c $cmd -n '__fish_seen_subcommand_from status ps help' -l all
    complete -c $cmd -n '__fish_seen_subcommand_from build rebuild' -l no-cache
    complete -c $cmd -n '__fish_seen_subcommand_from exec shell' -s u -l user -r
    complete -c $cmd -n '__fish_seen_subcommand_from exec shell' -s w -l workdir -r
    complete -c $cmd -n '__fish_seen_subcommand_from completion' -f -a 'bash zsh fish'
    complete -c $cmd -n '__fish_seen_subcommand_from help' -f -a 'list ps status start up stop restart recreate down build rebuild logs shell exec php composer artisan think env use recover doctor completion gui'
end
