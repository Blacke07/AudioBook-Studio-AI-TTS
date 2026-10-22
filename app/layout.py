"""One installation layout, shared by the application, setup and verification tools."""
from dataclasses import dataclass
from pathlib import Path

LAYOUT_VERSION = 2
PROGRAM = 'Data/Program'
USER = 'Data/User'
STATE = 'Data/State'
MANIFEST = STATE + '/installation-manifest.json'
MARKER = STATE + '/.studio-install-incomplete'
USER_FILES = ('settings.json', 'characters.json', 'volumes.json')


@dataclass(frozen=True)
class Layout:
    root: Path
    installed: bool = True

    @classmethod
    def for_program(cls, program):
        program = Path(program).resolve()
        installed = program.name == 'Program' and program.parent.name == 'Data'
        return cls(program.parent.parent if installed else program, installed)

    @property
    def program(self):
        return self.root / PROGRAM if self.installed else self.root

    @property
    def user(self):
        return self.root / USER if self.installed else self.root

    @property
    def state(self):
        return self.root / STATE if self.installed else self.root

    @property
    def audiobooks(self):
        return self.root / 'Audiobooks' if self.installed else self.root / 'export'

    @property
    def backups(self):
        return self.root / 'Backups' if self.installed else self.root / 'projects-backup'

    @property
    def models(self):
        return self.root / 'models'

    @property
    def manifest(self):
        return self.state / 'installation-manifest.json'

    def prepare(self):
        for path in (self.program, self.user, self.state/'logs', self.audiobooks, self.backups, self.models):
            safe_destination(self.root, path).mkdir(parents=True, exist_ok=True)
        (self.root/'Data/README.txt').write_text(
            'Internal application files. Use the folders next to this one for your audiobooks and backups.\n',
            encoding='utf-8')


def safe_destination(root, path):
    """No links, alternate streams or escape from an installation-owned tree."""
    root, path = Path(root).absolute(), Path(path).absolute()
    if path.resolve() != path or not path.is_relative_to(root) or path == root:
        raise ValueError('Unsafe installation path: ' + str(path))
    return path


def check_path_length(path):
    # The Windows host / external tools do not all support extended-length paths.
    if len(str(Path(path).absolute())) >= 240:
        raise ValueError('This path is too long for the Windows application tools. '
                         'Choose a shorter installation, volume or chapter name: ' + str(path))
