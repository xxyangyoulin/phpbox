import argparse
import codecs
import json
import os
import selectors
import signal
import subprocess
import sys
import unicodedata
from pathlib import Path

from core.version import VERSION


FORWARD_COMMANDS = ('php', 'composer', 'artisan', 'think')
SERVICES = ('php', 'nginx', 'mysql', 'redis', 'cron')
ROOT_HELP = '''项目选择：
  pbox -p workbench status           在任意目录选择项目
  pbox -C ~/php-dev/projects/demo php -v
  不指定项目时，从当前目录向上识别项目。list 总是列出所有项目；
  status/ps 在项目内显示当前项目，否则显示全部；--all 强制显示全部。
  常规命令也接受命令后的 -p/-C；透传命令的 PHPBox 选项必须放在命令前。

执行与管道：
  pbox php -r 'echo PHP_VERSION;'    参数顺序和内容原样保留
  pbox composer --no-interaction install
  pbox -p workbench exec -T mysql -- mysql --defaults-extra-file=/tmp/client.cnf < backup.sql
  pbox -T php script.php > result.txt
  数据库导入示例要求容器内已准备好 /tmp/client.cnf 客户端凭据配置。
  php/composer/artisan/think 后的 --help 属于目标程序。
  pbox help php                     查看 PHPBox 对 php 命令的说明

生命周期与日志：
  pbox start workbench              启动项目（up 是别名）
  pbox restart                     重启现有容器，不应用新镜像/Compose 配置
  pbox build --no-cache             仅构建镜像（rebuild 是明确的别名）
  pbox recreate                    使用已有镜像和配置重新创建项目容器
  pbox down                        移除项目容器，保留项目文件和命名数据卷
  pbox logs                        输出最近 200 行后退出
  pbox logs -f --service php --tail 100 --since 1h --timestamps
  共享 PHP 不随项目 stop/down/restart/recreate 停止或重启。

共享环境：
  pbox env list                     列出共享 PHP 环境
  pbox env create php84 --php 8.4 --extension redis --extension gd --start
  pbox -p workbench use php84 --check
  pbox -p workbench use php84        切换环境，允许升降 PHP 版本
  pbox env restart php84 --yes       影响使用该环境的所有项目
  pbox recover                      恢复未完成的项目环境切换

脚本、诊断和补全：
  pbox list --json                   机器可读结果；-q 仅输出名称
  pbox status --check                仅在所选项目健康时成功
  pbox doctor --json                 检查 Docker 与 Compose 必要条件
  pbox completion bash              输出 Bash 补全脚本（也支持 zsh/fish）
  pbox help env                     查看命令组；pbox help env create 查看子命令
  pbox help --all                    一次查看全部命令和参数的完整说明

输出与退出码：
  查询结果/容器程序 stdout 写入 stdout；PHPBox 进度、提示和错误写入 stderr。
  0=成功，1=操作失败，2=参数错误，130=Ctrl+C，143=SIGTERM，141=管道关闭。
  exec/php/composer/artisan/think 保留目标命令退出码；状态查询成功不代表运行中，
  如需用于健康判定请加 status --check。停止状态和无法查询状态分别显示。
  --quiet 不隐藏错误和被执行程序的输出；--json 不混入进度文字，JSON 字段名不依赖界面语言。

直接运行 pbox 或 pbox gui 打开图形界面；--hide/--new-project 仅用于图形界面。
'''


def build_parser():
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument('-C', '--directory', metavar='DIR', help='先进入宿主机目录再执行，作用类似 cd DIR')
    common.add_argument('-q', '--quiet', action='store_true', help='隐藏进度；list 仅输出项目名称，env list 仅输出环境 ID')
    common.add_argument('--verbose', action='store_true', help='操作失败时显示完整底层错误，非预期异常显示堆栈')
    selection = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    selection.add_argument('-p', '--project', metavar='NAME', help='项目名称；仅用于项目操作，优先于当前目录识别')
    terminal = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    tty = terminal.add_mutually_exclusive_group()
    tty.add_argument('-T', '--no-tty', dest='tty', action='store_false', help='执行容器命令时禁用伪终端，适合管道和重定向')
    tty.add_argument('-t', '--tty', action='store_true', help='执行容器命令时强制分配伪终端；默认仅在输入和输出都是终端时启用')
    parser = argparse.ArgumentParser(prog='pbox', parents=[common, selection, terminal],
        description='PHPBox：管理项目与共享 PHP 环境；支持交互终端和自动化脚本。',
        epilog=ROOT_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--version', action='version', version='pbox ' + VERSION, help='显示 PHPBox 版本并退出')
    parser.add_argument('--hide', action='store_true', help='打开 GUI 时只显示托盘')
    parser.add_argument('--new-project', action='store_true', help='打开 GUI 的新建项目窗口')
    subs = parser.add_subparsers(dest='command', metavar='COMMAND')

    def command(name, summary, detail='', group=subs, parents=True):
        inherited = [common] if parents else []
        if parents and group is subs and name in ('status', 'ps', 'start', 'up', 'stop', 'restart',
                'recreate', 'down', 'build', 'rebuild', 'logs', 'shell', 'exec', 'use', 'recover'):
            inherited.append(selection)
        if name in ('shell', 'exec'):
            inherited.append(terminal)
        return group.add_parser(name, help=summary, description=summary,
            epilog=detail, parents=inherited,
            formatter_class=argparse.RawDescriptionHelpFormatter)

    def output(p):
        p.add_argument('--json', action='store_true', help='输出 JSON；错误仍写入 stderr，失败返回非零退出码')

    def target(p):
        p.add_argument('name', nargs='?', help='项目名称；也可使用 -p，省略时识别当前目录')

    p = command('list', '列出所有项目', '示例：pbox list\n      pbox list --json\n      pbox list -q\n-q 只读本地项目名称，不查询 Docker；普通输出包含运行状态和 PHP 环境。')
    output(p)
    for name in ('status', 'ps'):
        p = command(name, '查看项目状态' + ('（status 的别名）' if name == 'ps' else ''),
            '示例：pbox status demo --json\n      pbox status --all --check\n项目外且未指定名称时列出全部。--check 在无项目、查询失败或任一项目不健康时返回 1。')
        target(p)
        p.add_argument('--all', action='store_true', help='查看全部项目；不可同时指定项目名称/-p')
        p.add_argument('--check', action='store_true', help='额外检查健康状态，未运行或部分运行返回 1')
        output(p)

    for name, summary, detail in (
        ('start', '启动项目', '执行 up -d，必要时启动绑定的 PHP 环境。'),
        ('up', '启动项目（start 的别名）', '与 start 完全相同。'),
        ('stop', '停止项目容器', '保留容器；共享 PHP 环境继续运行。'),
        ('restart', '重启现有项目容器', '不会重建容器或应用新镜像/Compose 配置。共享 PHP 环境继续运行；重启它请用 env restart。'),
        ('recreate', '重新创建项目容器', '使用现有镜像和 Compose 配置执行 up --force-recreate，不构建镜像。保留命名数据卷；容器可写层会重建。共享 PHP 环境不重建。'),
        ('down', '停止并移除项目容器', '保留代码、配置和命名数据卷；容器可写层会被移除。共享 PHP 环境继续运行。'),
    ):
        p = command(name, summary, detail + '\n示例：pbox ' + name + ' workbench')
        target(p)
    for name in ('build', 'rebuild'):
        p = command(name, '构建独立项目镜像' + ('（build 的别名）' if name == 'rebuild' else ''),
            'build/rebuild 完全相同：只构建，不重启。构建后执行 pbox recreate 应用镜像。\n共享项目需使用 pbox env rebuild ENV。使用应用设置中的构建代理。\n示例：pbox build workbench --no-cache')
        target(p)
        p.add_argument('--no-cache', action='store_true', help='禁用 Docker 构建缓存')
    p = command('logs', '查看项目或共享 PHP 日志',
        '默认输出最近 200 行后退出，-f 持续跟踪；Ctrl+C 停止跟踪。\n共享项目默认包含项目 Compose 和共享 PHP 环境日志；共享 PHP 日志可能来自其他项目，不能按项目隔离。\n--service php/cron 在共享模式下读取同一个环境容器日志。\n示例：pbox logs demo -f --service php --tail 100 --since 1h --timestamps')
    target(p)
    p.add_argument('--service', '-s', choices=SERVICES, help='仅查看指定服务；省略表示全部')
    follow = p.add_mutually_exclusive_group()
    follow.add_argument('-f', '--follow', action='store_true', help='持续跟踪，默认不跟踪')
    follow.add_argument('--no-follow', dest='follow', action='store_false', help='输出快照后退出（默认）')
    p.set_defaults(follow=False)
    p.add_argument('--tail', default='200', type=_tail, metavar='N|all', help='每个日志来源最后 N 行，或 all；默认 200')
    p.add_argument('--since', help='起始时间：如 30m、1h 或 RFC3339 时间')
    p.add_argument('--timestamps', action='store_true', help='显示日志时间戳')
    p.add_argument('--no-color', action='store_true', help='禁用 Compose 日志颜色；重定向时自动禁用')
    for name in ('shell', 'exec'):
        p = command(name, '进入容器终端' if name == 'shell' else '在容器中执行命令并返回其退出码',
            '示例：pbox -p demo shell php\n      pbox exec -T mysql -- mysql --defaults-extra-file=/tmp/client.cnf < backup.sql\n      pbox exec -u root -w /tmp php -- ls -la\n数据库示例需预先准备容器内 /tmp/client.cnf 客户端凭据配置。\nPHPBox 参数放在服务名之前；服务名后的参数属于目标命令。PHP 工作目录自动映射当前代码目录，其他服务使用容器默认工作目录。')
        p.add_argument('-u', '--user', help='容器用户，支持 UID:GID；默认遵循项目/共享环境配置')
        p.add_argument('-w', '--workdir', help='容器内绝对工作目录；不会改变宿主机目录')
        if name == 'shell':
            p.add_argument('service', nargs='?', default='php', choices=SERVICES, help='服务，默认 php；PHP 优先使用 zsh/bash/sh')
        else:
            p.add_argument('service', choices=SERVICES, help='服务名称')
            p.add_argument('args', nargs=argparse.REMAINDER, help='目标命令及其参数，可使用 -- 分隔')
    for name in FORWARD_COMMANDS:
        # 不解析 '-' 开头的选项，避免 argparse 截获或重排目标程序的参数。
        p = subs.add_parser(name, add_help=False, prefix_chars='\0',
            help='原样执行 ' + ('php ' + name if name in ('artisan', 'think') else name),
            description='执行 ' + name + '，保留参数顺序、标准输入输出和退出码。',
            epilog=('PHPBox 的 -p/-C/-T/-t 等选项必须放在此命令之前。\n'
                    '--help/-h 传给目标程序；本页通过 pbox help ' + name + ' 查看。\n'
                    '可在参数前加一个 -- 分隔符，PHPBox 会移除它。\n'
                    + ('始终在项目代码根目录执行框架入口文件。\n' if name in ('artisan', 'think') else '保留当前代码子目录的对应容器工作目录。\n')
                    + '示例：pbox -p workbench ' + name + (' -r \'echo PHP_VERSION;\'' if name == 'php' else ' --help')),
            formatter_class=argparse.RawDescriptionHelpFormatter)
        p.add_argument('args', nargs=argparse.REMAINDER, help='原样传给目标程序的全部参数')

    p = command('env', '管理共享 PHP 环境',
        '环境可通过完整 ID 或唯一名称选择；名称重复时必须使用 ID。\n停止、重启、重建会影响所有绑定项目：交互终端显示确认，脚本必须传 --yes。\n示例：pbox env list\n      pbox help env create')
    envs = p.add_subparsers(dest='env_command', required=True, metavar='ACTION')
    p = command('list', '列出共享 PHP 环境', '示例：pbox env list --json\n-q 仅输出环境 ID，不查询 Docker。', envs)
    output(p)
    p = command('inspect', '查看环境配置和绑定项目', '示例：pbox env inspect php84 --json\n代理仅显示是否配置，不输出代理凭据。', envs)
    p.add_argument('environment', help='环境名称或完整 ID')
    output(p)
    p = command('create', '创建并构建共享 PHP 环境',
        '默认不启动；--start 构建后启动。失败时保留环境文件，可用 env rebuild 重试。\n扩展按 PHP 版本由安装器选择兼容版本。代理用于构建和终端代理快捷命令，不自动设置运行时全局代理。\n示例：pbox env create php84 --php 8.4 --extension redis --extension gd --start', envs)
    p.add_argument('name', help='环境显示名称')
    from core.config import PHP_VERSIONS
    p.add_argument('--php', required=True, choices=PHP_VERSIONS, help='PHP 版本')
    p.add_argument('--extension', action='append', default=[], metavar='EXT', help='安装扩展，可重复；省略时不额外安装扩展')
    p.add_argument('--proxy', default='', metavar='URL', help='构建代理 URL；127.0.0.1/localhost 自动转换为宿主机地址')
    p.add_argument('--start', action='store_true', help='构建完成后启动环境')
    for name, summary in (('start', '启动共享环境'), ('stop', '停止共享环境'),
                          ('restart', '重启共享环境'), ('rebuild', '重建共享环境镜像'), ('delete', '删除未绑定项目的共享环境')):
        p = command(name, summary,
            '示例：pbox env ' + name + ' php84' + (' --yes' if name != 'start' else '')
            + '\n重建会更新运行中的环境；停止/重启/重建前会检查正在执行的定时任务。'
            + '\n删除会移除环境容器及环境配置，存在项目绑定时拒绝删除。', envs)
        p.add_argument('environment', help='环境名称或完整 ID')
        if name != 'start':
            p.add_argument('-y', '--yes', action='store_true', help='确认影响范围；非交互运行时必须显式确认有影响的操作')
        if name == 'rebuild':
            p.add_argument('--no-cache', action='store_true', help='禁用镜像构建缓存')
    p = command('use', '切换当前项目绑定的 PHP 环境',
        '允许升降 PHP 版本，不按 composer.json/lock 阻止切换，不导入旧项目 php.ini。\n沿用现有迁移检查、路由验证和失败恢复；目标未启动时会启动。\n--check 执行兼容性检查但不切换绑定，可能启动目标环境并生成项目身份文件。\n示例：pbox -p workbench use php72 --check\n      pbox -p workbench use php72')
    p.add_argument('environment', help='目标环境名称或完整 ID')
    p.add_argument('--check', action='store_true', help='仅检查迁移与运行条件，不切换绑定')
    output(p)
    p = command('recover', '恢复项目未完成的环境切换', '读取已保留的切换记录并恢复原环境；没有恢复记录时失败。\n示例：pbox recover workbench')
    target(p)
    p = command('doctor', '检查 CLI 所需运行条件', '检查 Docker 命令、Compose、Docker 守护进程；任一必要检查失败返回 1。\n无图形桌面也可使用 CLI，终端模拟器和系统打开器不作为必要条件。\n示例：pbox doctor --json')
    output(p)
    p = command('completion', '输出 Shell 补全脚本',
        'Bash：source <(pbox completion bash)\nZsh：先执行 autoload -Uz compinit && compinit，再 source <(pbox completion zsh)\nFish：pbox completion fish | source\n持久安装可将输出保存到对应 Shell 的用户补全目录；支持 phpbox 与 pbox。\n项目/环境候选只读本地元数据，不启动 Docker。', parents=False)
    p.add_argument('shell', choices=('bash', 'zsh', 'fish'))
    p = command('help', '查看命令帮助或完整 CLI 手册', '示例：pbox help exec\n      pbox help env create\n      pbox help --all', parents=False)
    p.add_argument('topic', nargs='*', help='命令及子命令名称')
    p.add_argument('--all', action='store_true', help='输出所有命令及子命令的完整帮助')
    p = command('gui', '打开图形界面', '示例：pbox gui --new-project', parents=False)
    p.add_argument('--hide', action='store_true', default=argparse.SUPPRESS, help='只显示托盘')
    p.add_argument('--new-project', action='store_true', default=argparse.SUPPRESS, help='打开新建项目窗口')
    return parser


def _tail(value):
    if value != 'all' and (not value.isdecimal() or int(value) < 0):
        raise argparse.ArgumentTypeError('必须是非负整数或 all')
    return value


def _children(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def parse_args(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    for key, default in (('project', None), ('directory', None), ('quiet', False), ('verbose', False), ('tty', None)):
        if not hasattr(args, key):
            setattr(args, key, default)
    if args.command == 'help':
        if args.all and args.topic:
            parser.error('help --all 不接受命令名称')
        selected = parser
        for topic in args.topic:
            if topic not in _children(selected):
                parser.error('不存在的帮助主题: ' + ' '.join(args.topic))
            selected = _children(selected)[topic]
        def show(p):
            p.print_help()
            if args.all:
                for child in _children(p).values():
                    print('\n' + '=' * 72)
                    show(child)
        show(selected)
        parser.exit()
    if args.command not in (None, 'gui') and (args.hide or args.new_project):
        parser.error('--hide/--new-project 仅用于 GUI')
    if args.project and args.command in ('list', 'env', 'doctor', 'completion'):
        parser.error('-p/--project 仅用于单个项目操作；查询指定项目请使用 status')
    if args.command in (None, 'gui') and (args.project or args.tty is not None or args.quiet or args.verbose):
        parser.error('项目与执行选项需要指定 CLI 命令；使用 pbox --help 查看用法')
    if getattr(args, 'json', False) and args.quiet:
        parser.error('--json 和 --quiet 不能同时使用')
    if args.command in ('status', 'ps') and args.all and (args.project or args.name):
        parser.error('--all 不能与项目名称或 -p 同时使用')
    if args.command in ('exec', *FORWARD_COMMANDS):
        if args.args[:1] == ['--']:
            args.args = args.args[1:]
        if args.command == 'exec' and not args.args:
            parser.error('exec 需要命令，例如 pbox exec php -- php -v')
    if getattr(args, 'workdir', None) and not args.workdir.startswith('/'):
        parser.error('--workdir 必须是容器内的绝对路径')
    return args


def _progress(text):
    print(text, end='', file=sys.stderr, flush=True)


def _table(rows):
    def width(text):
        return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('F', 'W') else 1 for c in text)
    rows = [[str(cell).replace('\n', ' ').replace('\t', ' ') for cell in row] for row in rows]
    widths = [max(width(row[i]) for row in rows) for i in range(len(rows[0]))]
    print('\n'.join('  '.join(cell + ' ' * (widths[i] - width(cell)) for i, cell in enumerate(row)).rstrip() for row in rows))


def _json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _project(args, manager, with_status=False, required=True):
    from core.config import BASE_DIR
    name = getattr(args, 'name', None)
    if name and args.project and name != args.project:
        raise ValueError('项目名称与 -p 指定的项目不一致')
    name = args.project or name
    if not name:
        cwd = Path.cwd().resolve()
        for path in (cwd, *cwd.parents):
            if path.parent == BASE_DIR.resolve():
                name = path.name
                break
    project = manager.get_project(name, with_status=with_status) if name else None
    if project is None and (required or name):
        raise ValueError(('未找到项目: ' + name if name else '当前目录不属于项目，请使用 -p NAME 或 -C DIR') + '\n使用 pbox list 查看项目。')
    return project


def _project_data(project, status_error=''):
    return dict(name=project.name, path=str(project.path), php_version=project.php_version,
        port=project.port, environment_id=project.environment_id, environment_name=project.environment_name,
        status='unknown' if status_error else project.health_status,
        error=project.runtime_error or None, auto_restart=project.auto_restart,
        services={service: (None if status_error else getattr(project, service + '_running'))
                  for service in SERVICES if service in ('php', 'nginx') or project.has_service(service)})


def _environment(manager, name):
    environments = manager.list()
    matches = [env for env in environments if env.id == name]
    if not matches:
        matches = [env for env in environments if env.name == name]
    if len(matches) != 1:
        raise ValueError('环境名称不唯一，请使用 ID' if matches else '未找到 PHP 环境: ' + name + '；使用 pbox env list 查看')
    return matches[0]


def _confirm(message, yes):
    print(message, file=sys.stderr)
    if yes:
        return
    if not sys.stdin.isatty():
        raise ValueError('非交互模式需要 --yes 明确确认')
    print('确认继续？[y/N] ', end='', file=sys.stderr, flush=True)
    if input().strip().lower() not in ('y', 'yes'):
        raise ValueError('操作已取消')


def _docker_running():
    result = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or '无法查询 Docker 容器状态')
    return set(result.stdout.splitlines())


def _run_environment(args):
    from core.environment import EnvironmentManager
    manager = EnvironmentManager(on_output=None if args.quiet else _progress)
    action = args.env_command
    if action in ('list', 'inspect'):
        environments = manager.list() if action == 'list' else [_environment(manager, args.environment)]
        if args.quiet:
            for env in environments:
                print(env.id)
            return 0
        error = ''
        try:
            running = _docker_running() if environments else set()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            error, running = str(exc), set()
        rows = [dict(id=env.id, name=env.name, php_version=env.php_version,
                     extensions=env.extensions, proxy_configured=bool(env.proxy), path=str(env.path),
                     projects=[p.name for p in manager.bindings(env.id)],
                     status='unknown' if error else 'running' if env.container in running else 'stopped') for env in environments]
        if args.json:
            _json(rows if action == 'list' else rows[0])
        else:
            _table([('名称', 'ID', 'PHP', '状态', '项目')] + [(r['name'], r['id'], r['php_version'], r['status'], ', '.join(r['projects']) or '-') for r in rows])
            if action == 'inspect':
                print('目录: ' + rows[0]['path'])
                print('扩展: ' + (', '.join(rows[0]['extensions']) or '-'))
                print('构建代理: ' + ('已配置' if rows[0]['proxy_configured'] else '未配置'))
        if error:
            print(error, file=sys.stderr)
        return int(bool(error))
    if action == 'create':
        env = manager.create(args.name, args.php, args.extension, args.proxy)
        print('已创建环境 ' + env.name + '，ID: ' + env.id, file=sys.stderr)
        manager.build(env)
        if args.start:
            manager.start(env)
        print(env.id)
        return 0
    env = _environment(manager, args.environment)
    bound = manager.bindings(env.id)
    if action == 'delete' or (bound and action in ('stop', 'restart', 'rebuild')):
        _confirm('将' + action + '环境 ' + env.name + '；绑定项目: ' + (', '.join(p.name for p in bound) or '无'), args.yes)
    if action == 'rebuild':
        manager.build(env, no_cache=args.no_cache)
    else:
        getattr(manager, action)(env)
    if not args.quiet:
        print('环境操作完成: ' + action + ' ' + env.name, file=sys.stderr)
    return 0


def _run_logs(args, project):
    from core.runtime import logs_args
    from core.environment import EnvironmentManager, read_binding
    binding = read_binding(project.path)
    services = [args.service]
    if binding and args.service is None:
        services.append('php')
    if binding and (args.service is None or args.service in ('php', 'cron')):
        env = EnvironmentManager().load(binding['environment_id'])
        print('包含共享环境 ' + env.name + ' 的日志，可能来自其他绑定项目。', file=sys.stderr)
    processes = []
    try:
        with selectors.DefaultSelector() as selector:
            for service in services:
                command = logs_args(project.path, service, args.follow, args.tail, args.since,
                                    args.timestamps, args.no_color or not sys.stdout.isatty())
                process = subprocess.Popen(command, cwd=str(project.path), stdout=subprocess.PIPE, start_new_session=True)
                processes.append(process)
                selector.register(process.stdout, selectors.EVENT_READ, codecs.getincrementaldecoder('utf-8')(errors='replace'))
            while selector.get_map():
                for key, _ in selector.select(0.2):
                    data = os.read(key.fd, 65536)
                    text = key.data.decode(data, final=not data)
                    if text:
                        print(text, end='', flush=True)
                    if not data:
                        selector.unregister(key.fileobj)
            codes = [process.wait() for process in processes]
            return next((code for code in codes if code), 0)
    finally:
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
            process.stdout.close()


def _run_container(args, project):
    from core.project import get_project_code_path
    from core.environment import read_binding, container_workdir
    from core.runtime import exec_args
    from core.process import run_attached
    service = getattr(args, 'service', 'php')
    base = container_workdir(project.path) if read_binding(project.path) else '/var/www/html'
    workdir = getattr(args, 'workdir', None)
    if not workdir and service == 'php':
        workdir = base
        if args.command not in ('artisan', 'think'):
            try:
                relative = Path.cwd().resolve().relative_to(get_project_code_path(project.path, project.name).resolve())
                workdir = base + ('/' + relative.as_posix() if relative.parts else '')
            except ValueError:
                pass
    if args.command == 'shell':
        command = ['sh', '-c', 'if command -v zsh >/dev/null 2>&1; then exec zsh; elif command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi']
    elif args.command == 'exec':
        command = args.args
    elif args.command in ('artisan', 'think'):
        command = ['php', args.command] + args.args
    else:
        command = [args.command] + args.args
    tty = args.tty if args.tty is not None else sys.stdin.isatty() and sys.stdout.isatty()
    command = exec_args(project.path, service, command, user=getattr(args, 'user', None), tty=tty, workdir=workdir)
    return run_attached(command, cwd=str(project.path), tty=tty)


def _doctor(args):
    import shutil
    checks = []
    available = shutil.which('docker')
    checks.append(dict(name='docker', ok=bool(available), detail=available or '未找到 docker 命令'))
    compose = ''
    detail = ''
    for command in (['docker', 'compose', 'version'], ['docker-compose', 'version']):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                compose = ' '.join(command[:-1])
                break
            detail = result.stderr.strip() or result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            detail = str(exc)
    checks.append(dict(name='compose', ok=bool(compose), detail=compose or detail or '未找到 Docker Compose'))
    try:
        result = subprocess.run(['docker', 'info'], capture_output=True, text=True, timeout=10)
        checks.append(dict(name='daemon', ok=result.returncode == 0, detail='Docker 服务正常' if result.returncode == 0 else result.stderr.strip() or result.stdout.strip()))
    except (OSError, subprocess.TimeoutExpired) as exc:
        checks.append(dict(name='daemon', ok=False, detail=str(exc)))
    ok = all(check['ok'] for check in checks)
    if args.json:
        _json(dict(ok=ok, checks=checks))
    elif not args.quiet:
        for check in checks:
            print(check['name'] + ': ' + ('正常' if check['ok'] else '异常') + ' · ' + check['detail'])
    if not ok:
        print('运行条件检查未通过: ' + ', '.join(check['name'] for check in checks if not check['ok']), file=sys.stderr)
    return 0 if ok else 1


def dispatch(args):
    if args.directory:
        os.chdir(Path(args.directory).expanduser())
    if args.command == 'completion':
        print((Path(__file__).parent.parent / 'resources/completions' / ('pbox.' + args.shell)).read_text(), end='')
        return 0
    if args.command == 'doctor':
        return _doctor(args)
    if args.command == 'env':
        return _run_environment(args)
    from core.project import ProjectManager
    manager = ProjectManager()
    if args.command in ('list', 'status', 'ps'):
        if args.command == 'list' and args.quiet:
            for project in manager.get_all_projects(with_status=False):
                print(project.name)
            return 0
        project = None
        if args.command != 'list' and not args.all:
            project = _project(args, manager, with_status=True, required=False)
        projects = [project] if project else manager.get_all_projects()
        rows = [_project_data(p, manager.status_error) for p in projects]
        if args.json:
            _json(rows[0] if project else rows)
        elif not args.quiet:
            _table([('名称', '状态', 'PHP', '端口', 'PHP 环境')] + [
                (p.name, '未知' if manager.status_error else p.status_text, p.php_version, p.port, p.environment_name or '独立') for p in projects])
            if project:
                print('路径: ' + str(project.path))
                print('服务: ' + ('无法查询' if manager.status_error else project.health_summary))
                if project.runtime_error:
                    print('详情: ' + project.runtime_error)
        if manager.status_error:
            print(manager.status_error, file=sys.stderr)
            return 1
        if getattr(args, 'check', False):
            return 0 if projects and all(p.health_status == 'healthy' for p in projects) else 1
        return 0
    project = _project(args, manager)
    if args.command in ('shell', 'exec', *FORWARD_COMMANDS):
        return _run_container(args, project)
    if args.command == 'logs':
        return _run_logs(args, project)
    if args.command in ('use', 'recover'):
        from core.environment import EnvironmentManager
        from core.runtime import ProjectRuntime
        runtime = ProjectRuntime(project.path, on_output=None if args.quiet else _progress)
        if args.command == 'recover':
            runtime.recover()
        else:
            env = _environment(EnvironmentManager(), args.environment)
            preview = runtime.preview(env)
            if args.check:
                runtime.check(env)
            else:
                runtime.switch(env)
            if args.json:
                _json(dict(project=project.name, environment_id=env.id, environment=env.name, php_version=env.php_version,
                           checked=True, switched=not args.check, preview=preview))
                return 0
        if not args.quiet:
            print('环境检查通过' if getattr(args, 'check', False) else '环境操作完成', file=sys.stderr)
        return 0
    from core.docker import DockerManager
    docker = DockerManager(project.path, on_output=None if args.quiet else _progress)
    if args.command in ('build', 'rebuild'):
        from core.settings import Settings
        return docker.build_live(proxy=Settings().get_proxy(), no_cache=args.no_cache)
    if args.command in ('start', 'up'):
        result = docker.up_with_port_check(project.name)
    else:
        result = getattr(docker, args.command)()
    if not result.success:
        print((result.raw_error if args.verbose else '') or result.error, file=sys.stderr)
        return 1
    if not args.quiet:
        print('项目操作完成: ' + args.command + ' ' + project.name, file=sys.stderr)
    return 0


class Terminated(BaseException):
    pass


def run_cli(args):
    def terminate(signum, frame):
        raise Terminated()
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        code = dispatch(args)
        sys.stdout.flush()
        return 128 - code if code < 0 else code
    except KeyboardInterrupt:
        print('操作已中断', file=sys.stderr)
        return 130
    except Terminated:
        return 143
    except BrokenPipeError:
        # 避免解释器退出时再次刷新已关闭的 stdout 管道。
        with open(os.devnull, 'w') as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 141
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, EOFError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        if args.verbose:
            import traceback
            traceback.print_exc()
        else:
            print(str(exc) + '\n使用 --verbose 查看异常详情。', file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)
