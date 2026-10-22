"""Lossless preparation inventories. Inventory presence is never test credit.

The original documents are inventoried at source-line granularity so that a
reviewer can classify every clause without a keyword heuristic dropping prose.
AST decision sites are a review checklist, not measured branch coverage.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import stat
from pathlib import Path


EXCLUDED_ROOTS = frozenset({
    '.git', '.venv', '.validation', '.pytest_cache', 'build', 'dist',
    'bittorrent_lite.egg-info',
})
EXCLUDED_CACHE_DIRS = frozenset({'__pycache__', '.pytest_cache'})
ORIGINALS = {
    'G': 'BitTorrent-Lite-Revised-Project-Guide.md',
    'R': '01-Rishikesh-Individual-Plan.md',
    'D': '02-Debargha-Individual-Plan.md',
    'A': '03-Anik-Individual-Plan.md',
    'P': '04-Prabhat-Individual-Plan.md',
}
ORIGINAL_HASHES = {
    'G': 'dffb144c70dc7dd3a81a2ccacf831e2cfef4bfa03157f4a042eafd4f5b5c70f6',
    'R': '27a55a2b758be5fc7f0ef4afff4f1383a58d0cceaa75cbdd79562d17750dae84',
    'D': '5ee42a0873a20b74e2bdeb49112b77027ddb874a1228ab598eae6598fbb3a04a',
    'A': '6df26c7a8f15e2a03279ea175b8c78179a1f21e8059b6a2b8286344d8d89e7fb',
    'P': '58cd4ff7d6fdc2739b008349777b25652bb5f7efa35ea142def4edbaadfbf5f0',
}


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def is_redirect(path: Path) -> bool:
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        return True
    # pathlib.is_junction is unavailable on the declared minimum Python 3.10.
    try:
        attributes = getattr(path.lstat(), 'st_file_attributes', 0)
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def checked_path(path: Path, *, strict=False) -> Path:
    """Check the supplied path/ancestors before normalization can hide a link."""
    raw = Path(path).absolute()
    for part in (raw, *raw.parents):
        if is_redirect(part):
            raise ValueError(f'path redirection requires explicit review: {part}')
    return raw.resolve(strict=strict)


def source_files(repo: Path):
    """Inventory all files, not only tracked files; reject redirections."""
    repo = checked_path(repo, strict=True)
    def walk(folder):
        for path in sorted(folder.iterdir()):
            relative = path.relative_to(repo)
            if is_redirect(path):
                raise ValueError(f'source redirection requires explicit review: {relative}')
            if len(relative.parts) == 1 and path.name in EXCLUDED_ROOTS and path.is_dir():
                continue
            if path.name in EXCLUDED_CACHE_DIRS and path.is_dir():
                continue
            if path.is_dir():
                yield from walk(path)
            elif path.is_file():
                yield path
            else:
                raise ValueError(f'nonregular source entry: {relative}')
    yield from walk(repo)


def snapshot(repo: Path) -> dict:
    repo = checked_path(repo, strict=True)
    entries = [{'path': p.relative_to(repo).as_posix(), 'size': p.stat().st_size,
                'sha256': digest_file(p)} for p in source_files(repo)]
    exclusions = {'root_directories': sorted(EXCLUDED_ROOTS),
                  'cache_directories': sorted(EXCLUDED_CACHE_DIRS)}
    payload = {'schema': 1, 'files': entries, 'exclusions': exclusions}
    return {**payload, 'sha256': hashlib.sha256(canonical_bytes(payload)).hexdigest()}


def compare_snapshots(expected: dict, actual: dict):
    if expected != actual:
        before = {e['path']: e for e in expected['files']}
        after = {e['path']: e for e in actual['files']}
        changed = [name for name in sorted(before.keys() | after.keys())
                   if before.get(name) != after.get(name)]
        raise ValueError(f'frozen source changed: {changed}; exclusions must also agree')


def write_json_new(path: Path, value):
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write('\n')


def write_csv_new(path: Path, rows, fields):
    with path.open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def requirement_rows(repo: Path):
    base = repo / 'bittorrent_lite/docs/plans'
    docs = [(key, base / 'original' / name) for key, name in ORIGINALS.items()]
    docs += [(f'FU{i}', path) for i, path in enumerate(sorted((base / 'follow-up').glob('*.md')), 2)]
    for doc_id, path in docs:
        digest = digest_file(path)
        if doc_id in ORIGINAL_HASHES and digest != ORIGINAL_HASHES[doc_id]:
            raise ValueError(f'original document hash mismatch: {path}')
        section = ''
        code = False
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if line.startswith('#'):
                section = line
            if line.startswith('```'):
                code = not code
            if not line.strip():
                continue
            yield {'requirement_id': f'{doc_id}-L{lineno:04d}',
                   'document': path.relative_to(repo).as_posix(), 'document_sha256': digest,
                   'line': lineno, 'section': section, 'quote': line,
                   'classification': 'CODE/EXAMPLE—REVIEW' if code else 'CLAUSE—REVIEW',
                   'source_symbol': '', 'current_behavior': '', 'oracle': '',
                   'case_ids': '', 'node_ids': '', 'evidence': '', 'deviation': '',
                   'reviewer': '', 'status': 'BLOCKED',
                   'gap': 'Source clause inventoried; semantic classification and assertion mapping pending'}


def purpose(relative: Path):
    value = relative.as_posix()
    for component, label in [('acceptance_tools', 'acceptance tool'),
                             ('legacy', 'preserved alternative'),
                             ('examples', 'example'), ('experiments', 'experiment tooling')]:
        if component in relative.parts:
            return label
    if relative.name in {'__main__.py', 'cli.py', 'generate_metadata.py'}:
        return 'entry point'
    if relative.name == 'transfer_store.py':
        return 'preserved alternative'
    return 'production; live/standalone classification requires review'


def owner(relative: Path):
    for part in relative.parts:
        if part == 'storage':
            return 'Rishikesh'
        if part in {'discovery', 'experiments'}:
            return 'Debargha'
        if part == 'networking':
            return 'Anik'
        if part == 'scheduling':
            return 'Prabhat'
    return 'Shared/integration; attribution requires review'


def module_rows(repo: Path):
    for path in source_files(repo):
        relative = path.relative_to(repo)
        if relative.suffix != '.py' or 'tests' in relative.parts:
            continue
        text = path.read_text(encoding='utf-8-sig')
        tree = ast.parse(text, filename=str(relative))
        common = {'path': relative.as_posix(), 'sha256': digest_file(path),
                  'purpose': purpose(relative), 'owner': owner(relative), 'node_ids': '', 'assertions': '',
                  'line_coverage': '', 'branch_coverage': '', 'function_coverage': '',
                  'evidence': '', 'status': 'NOT RUN', 'gap': 'No fresh measured coverage/assertion review'}
        yield {**common, 'kind': 'module', 'symbol': '<module>', 'line': 1, 'end_line': len(text.splitlines())}
        def walk(node, scope):
            for child in ast.iter_child_nodes(node):
                nested_scope = scope
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested_scope = (*scope, child.name)
                    yield {**common, 'kind': 'class' if isinstance(child, ast.ClassDef) else 'function',
                           'symbol': '.'.join(nested_scope), 'line': child.lineno, 'end_line': child.end_lineno}
                elif isinstance(child, (ast.If, ast.IfExp, ast.While, ast.For, ast.AsyncFor,
                                        ast.Try, ast.ExceptHandler, ast.BoolOp, ast.Match)):
                    yield {**common, 'kind': f'decision:{type(child).__name__}',
                           'symbol': '.'.join(scope) or '<module>',
                           'line': child.lineno, 'end_line': child.end_lineno}
                yield from walk(child, nested_scope)
        yield from walk(tree, ())


def resource_rows(repo: Path):
    """Config/document/data census; no file gets execution credit from presence."""
    for path in source_files(repo):
        relative = path.relative_to(repo)
        if relative.suffix == '.py':
            continue
        kind = ('documentation' if relative.suffix.lower() == '.md' else
                'configuration' if relative.suffix.lower() in {'.toml', '.ini', '.json', '.cfg'}
                else 'resource; classification requires review')
        yield {'resource_id': relative.as_posix(), 'path': relative.as_posix(), 'kind': kind,
               'sha256': digest_file(path), 'owner': owner(relative),
               'methods': '', 'assertions': '', 'evidence': '', 'status': 'BLOCKED',
               'gap': 'Inventoried only; semantic/resource and installed-package review pending'}


def catalogue_rows(repo):
    import re
    plan = repo / 'bittorrent_lite/docs/integration/FINAL-ACCEPTANCE-TEST-PLAN.md'
    for lineno, line in enumerate(plan.read_text(encoding='utf-8').splitlines(), 1):
        match = re.match(r'^\| ((?:ST|TR|NW|SC|SY|EV|NC|SP)\d{2})(?: [^|]*)? \|', line)
        if match:
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            yield {'case_id': match[1], 'plan_line': lineno, 'required_cases': cells[1],
                   'oracle': cells[2], 'subcases': [], 'methods': [], 'status': 'BLOCKED',
                   'gap': 'Must expand every enumerated partition and review exact assertions/procedure'}


def generate(repo: Path, output: Path):
    repo = checked_path(repo, strict=True)
    output = checked_path(output)
    if output.exists():
        raise FileExistsError('inventory destination must be new')
    output.mkdir(parents=True)
    requirements = list(requirement_rows(repo))
    modules = list(module_rows(repo))
    cases = list(catalogue_rows(repo))
    resources = list(resource_rows(repo))
    if len(cases) != 89 or len({c['case_id'] for c in cases}) != 89:
        raise ValueError('acceptance catalogue changed; review required')
    write_csv_new(output / 'requirements.csv', requirements, list(requirements[0]))
    write_csv_new(output / 'modules.csv', modules, list(modules[0]))
    write_json_new(output / 'catalogue.json', cases)
    if resources:
        write_csv_new(output / 'resources.csv', resources, list(resources[0]))
    write_json_new(output / 'source-snapshot.json', snapshot(repo))
    write_json_new(output / 'inventory-status.json', {
        'status': 'BLOCKED', 'acceptance_started': False,
        'source_clause_rows': len(requirements), 'module_rows': len(modules),
        'resource_rows': len(resources),
        'catalogue_groups': len(cases),
        'meaning': 'Complete source census, not completed semantic mapping or coverage',
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    generate(args.repo, args.out)


if __name__ == '__main__':
    main()
