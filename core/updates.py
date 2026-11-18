import re

from core.version import VERSION


REPOSITORY_URL = 'https://github.com/xxyangyoulin/phpbox'
RELEASES_URL = REPOSITORY_URL + '/releases/latest'
RELEASE_API = 'https://api.github.com/repos/xxyangyoulin/phpbox/releases/latest'


def newer_release(data, current=VERSION):
    if not isinstance(data, dict):
        raise ValueError('更新服务返回了无效数据')
    if data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name')
    if not isinstance(tag, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', tag):
        raise ValueError('无法识别发布版本号')
    version = tag.lstrip('v')
    if tuple(map(int, version.split('.'))) <= tuple(map(int, current.split('.'))):
        return None
    return version, REPOSITORY_URL + '/releases/tag/' + tag
