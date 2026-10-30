"""Map catalog and authenticated pinned assets; session.py handles actual runtime.

This does not start CARLA, connect to existing servers, or engage Autoware.
Private coordinates/settings stay in the private bundle, never this catalog.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


class MapError(ValueError):
    pass


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def valid_artifact(record):
    if not isinstance(record, dict):
        raise MapError('지도 파일 명세가 없습니다.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', record.get('file', '')):
        raise MapError('지도 파일명은 경로나 패턴이 아닌 단일 파일명이어야 합니다.')
    if type(record.get('bytes')) is not int or record['bytes'] <= 0:
        raise MapError('지도 파일 크기가 올바르지 않습니다.')
    if not re.fullmatch('[0-9a-f]{64}', record.get('sha256', '')):
        raise MapError('고정된 SHA256이 필요합니다.')


def read_catalog(path):
    data = json.loads(path.read_text())
    if data.get('schema') != 1 or data.get('carla_version') != '0.9.15':
        raise MapError('지원하지 않는 지도 목록/엔진 버전입니다.')
    seen = set()
    for m in data['maps']:
        if not re.fullmatch('[a-z0-9][a-z0-9_-]*', m['id']) or m['id'] in seen:
            raise MapError('지도 ID가 중복되거나 올바르지 않습니다.')
        seen.add(m['id'])
        if not m['carla_map'].startswith('/Game/') or '..' in PurePosixPath(m['carla_map']).parts:
            raise MapError('CARLA 지도 경로가 올바르지 않습니다.')
        if m['distribution'] == 'private_github_release':
            valid_artifact(m['artifact'])
        elif m['distribution'] != 'official_carla' or m['artifact'] is not None:
            raise MapError('지원하지 않는 지도 배포 유형입니다.')
        ready=m['autoware'].get('ready')
        if type(ready) is not bool:raise MapError('명시적인 ready 값이 필요합니다.')
        if ready and not (m['id']=='ctrack' and m['autoware'].get('runtime_adapter')=='tools/session.py'
            and m['autoware'].get('verification_scope')=='same_pc_headless_low_speed'):
            raise MapError('지원하는 실행 어댑터와 검증 범위가 없는 지도입니다.')
    return data


def choose(catalog, ident=None, input_fn=input):
    maps = catalog['maps']
    if ident is not None:
        found = next((m for m in maps if m['id'] == ident), None)
        if found is None:
            raise MapError('등록되지 않은 지도: '+ident)
        return found
    if not sys.stdin.isatty():
        raise MapError('비대화형 실행에는 --map ID를 지정하세요.')
    for i, m in enumerate(maps, 1):
        status='제한 범위 SILS 실행 지원' if m['autoware']['ready'] else 'Autoware 연동 준비 중'
        print(f'{i}. {m["label"]} — {status}')
    answer = input_fn('지도 번호 (빈 입력은 취소): ').strip()
    if not answer.isdigit() or not 1 <= int(answer) <= len(maps):
        raise MapError('지도 선택을 취소했거나 번호가 잘못되었습니다.')
    return maps[int(answer)-1]


def matching_file(path, record):
    return (not path.is_symlink() and path.is_file()
            and path.stat().st_size == record['bytes'] and digest(path) == record['sha256'])


def private_source(sources, ident):
    if sources is None:
        raise MapError('비공개 저장소 주소가 미설정입니다. --sources 파일을 지정하세요.')
    data = json.loads(sources.read_text())
    if data.get('schema') != 1:
        raise MapError('비공개 저장소 설정 형식이 올바르지 않습니다.')
    row = data.get('sources', {}).get(ident, {})
    repo, tag = row.get('repository'), row.get('release_tag')
    if not isinstance(repo, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', repo):
        raise MapError('repository에 GitHub의 OWNER/REPO를 지정하세요. 토큰/URL은 넣지 마세요.')
    if not isinstance(tag, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', tag) or tag.lower() == 'latest':
        raise MapError('latest 대신 고정된 release_tag를 지정하세요.')
    return repo, tag


def checked_gh(arguments, *, run=subprocess.run):
    # Credentials stay in gh's normal credential store/environment. Do not log
    # auth output, tokens, command stderr, or embed secrets in a saved plan.
    result = run(['gh', *arguments], capture_output=True, text=True, timeout=3600)
    if result.returncode:
        raise MapError('GitHub 접근에 실패했습니다. gh 로그인·저장소 읽기 권한·Release 파일을 확인하세요.')
    return result.stdout.strip()


def fetch(m, cache, sources=None, offline=False, *, run=subprocess.run, which=shutil.which):
    if m['distribution'] == 'official_carla':
        return {'status': 'official_carla_assets', 'downloaded': False, 'private_access': False}
    record = m['artifact'];valid_artifact(record)
    if cache is None:
        raise MapError('--cache에 지도 캐시 경로를 지정하세요. 현재 PC에서는 RAID 사용을 권합니다.')
    cache = cache.expanduser().resolve()
    destination = cache / record['file']
    if destination.exists() or destination.is_symlink():
        if not matching_file(destination, record):
            raise MapError('기존 지도 캐시의 체크섬/크기가 다릅니다. 덮어쓰지 않았습니다: '+str(destination))
        return {'status': 'verified_cache', 'path': str(destination), 'downloaded': False, 'private_access': False}
    if offline:
        raise MapError('오프라인 지도 캐시가 없습니다.')
    repo, tag = private_source(sources, m['id'])
    if not which('gh'):
        raise MapError('GitHub CLI(gh)가 필요합니다. 설치 후 gh auth login으로 인증하세요.')
    checked_gh(['auth', 'status', '--hostname', 'github.com'], run=run)
    private = checked_gh(['repo', 'view', repo, '--json', 'isPrivate', '--jq', '.isPrivate'], run=run)
    if private != 'true':
        raise MapError('C-Track 배포 대상은 비공개 저장소여야 합니다. 다운로드를 중단했습니다.')
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    if shutil.disk_usage(cache).free < record['bytes']+1024**3:
        raise MapError('지도 다운로드 공간이 부족합니다.')
    stage = Path(tempfile.mkdtemp(prefix='.map-download-', dir=cache))
    checked_gh(['release', 'download', tag, '--repo', repo, '--pattern', record['file'], '--dir', str(stage)], run=run)
    downloaded = stage / record['file']
    if not matching_file(downloaded, record):
        raise MapError('다운로드 체크섬/크기 검증 실패. 실패 파일 보존: '+str(stage))
    downloaded.chmod(0o600)
    # link() fails if another process already published this name: never replace.
    try:
        os.link(downloaded, destination)
    except FileExistsError:
        if not matching_file(destination, record):
            raise MapError('동시 다운로드 충돌: 기존 파일을 보존했습니다.')
    downloaded.unlink();stage.rmdir()
    return {'status': 'downloaded_verified', 'path': str(destination), 'downloaded': True,
            'private_access': True, 'repository': repo, 'release_tag': tag}


def plan(m, mode):
    blockers = []
    if mode == 'sils' and not m['autoware']['ready']:
        blockers.append(m['autoware']['reason'])
    return {'map_id': m['id'], 'map_version': m['version'], 'mode': mode,
            'carla_version': '0.9.15', 'carla_map': m['carla_map'],
            'map_selection': 'explicit_load_world_before_autoware',
            'asset_source': m['distribution'], 'artifact': m['artifact'],
            'autoware_contract': m['autoware'], 'blockers': blockers,
            'auto_engage': False, 'changes_existing_simulation': False,
            'runtime_started': False, 'runtime_adapter_connected': False,
            'runtime_adapter_available':m['autoware']['ready']}


def select(m, mode, destination):
    record = plan(m, mode)
    if record['blockers']:
        raise MapError('Autoware 연동 실행 선택 불가: '+' '.join(record['blockers']))
    # Selection never starts a server. Explicit session init/run remains required.
    with destination.open('x', encoding='utf-8') as output:
        json.dump(record, output, indent=2, ensure_ascii=False)
        output.write('\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'plan', 'fetch', 'select'])
    parser.add_argument('--catalog', type=Path, default=HERE/'maps.json')
    parser.add_argument('--map')
    parser.add_argument('--mode', choices=['carla', 'sils'], default='sils')
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--sources', type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        catalog = read_catalog(args.catalog)
        if args.action == 'list':
            print(json.dumps([{'id': m['id'], 'label': m['label'], 'source': m['distribution'],
                               'autoware_ready': m['autoware']['ready'], 'reason': m['autoware']['reason']}
                              for m in catalog['maps']], ensure_ascii=False, indent=2));return
        m = choose(catalog, args.map)
        if args.action == 'plan':
            result = plan(m, args.mode)
        elif args.action == 'fetch':
            result = fetch(m, args.cache, args.sources, args.offline)
        else:
            if args.output is None:raise MapError('선택 결과를 보관할 --output 경로를 지정하세요.')
            result = select(m, args.mode, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (MapError, FileNotFoundError, FileExistsError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print('ERROR:', str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
